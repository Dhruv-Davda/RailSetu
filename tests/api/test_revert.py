"""Edge cases for revert / restore."""
import os
import shutil

from harness import ROOT, bootstrap

bootstrap("revert")

PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  — ' + str(detail)[:110]) if detail else ''}")


from fastapi.testclient import TestClient
from app.main import app
from app.policy import documents as DOCS
from app.policy.diff import reverse_patch

c = TestClient(app)
acc = c.post('/api/session', json={'email': 'edge@ir.gov.in'}).json()['account']
c.headers.update({'X-RailSetu-User': acc['email']})

K = 'crowd-safety'
def text(k=K):    return c.get(f'/api/policy/documents/{k}').json()['text']
def hist(k=K):    return c.get(f'/api/policy/documents/{k}/history').json()['versions']
def vseq(n, k=K): return next(v for v in hist(k) if v['seq'] == n)
def act(new, title, k=K):
    return c.post(f'/api/policy/documents/{k}/activate', json={'text': new, 'title': title})
def revert(vid, k=K): return c.post(f'/api/policy/documents/{k}/revert', json={'version_id': vid})
def restore(vid, k=K): return c.post(f'/api/policy/documents/{k}/rollback', json={'version_id': vid})

# ---------------------------------------------------------------- 1. guards
print("\n=== 1. GUARDS ===")
check("revert needs a signed-in caller",
      TestClient(app).post(f'/api/policy/documents/{K}/revert',
                           json={'version_id': 'x'}).status_code == 401)
check("revert of an unknown id is refused",
      revert('deadbeefdead').status_code == 400)
check("revert on an unknown document is refused",
      revert(vseq(1)['id'], k='no-such-doc').status_code in (400, 404))
r = revert(vseq(1)['id'])
check("the initial text cannot be reverted (no parent)", r.status_code == 400,
      r.json().get('detail'))
check("...and the message points at restore instead",
      'restore' in str(r.json().get('detail', '')).lower())

# --------------------------------------------------- 2. the core behaviour
print("\n=== 2. REVERT KEEPS LATER CHANGES ===")
act(text().replace('crush_above: 5.0', 'crush_above: 4.0'), 'v2 crush 4.0')
act(text().replace('metered_holding_release_density: 2.5',
                   'metered_holding_release_density: 3.0'), 'v3 metering 3.0')
r = revert(vseq(2)['id'])
check("reverting v2 succeeds", r.status_code == 200, r.json().get('detail'))
t = text()
check("the reverted rule is back", 'crush_above: 5.0' in t)
check("the later rule is untouched", 'metered_holding_release_density: 3.0' in t)
check("recorded as a new version", len(hist()) == 4)
check("the new version points at what it reverted", vseq(4)['reverts'] == vseq(2)['id'])
check("history is append-only — v2 still readable",
      c.get(f"/api/policy/documents/{K}/versions/{vseq(2)['id']}").json()['text']
      .count('crush_above: 4.0') == 1)

print("\n=== 3. REVERTING A REVERT RE-APPLIES THE CHANGE ===")
r = revert(vseq(4)['id'])
check("a revert can itself be reverted", r.status_code == 200, r.json().get('detail'))
check("the original change is back", 'crush_above: 4.0' in text())
check("and the later change still stands", 'metered_holding_release_density: 3.0' in text())

print("\n=== 4. NO-OP AND REPEAT ===")
r = revert(vseq(2)['id'])
check("reverting v2 again works (it is in force once more)", r.status_code == 200)
r = revert(vseq(2)['id'])
check("reverting it a third time is refused as a no-op", r.status_code == 400,
      r.json().get('detail'))
check("...with a plain message, not a conflict",
      'already been backed out' in str(r.json().get('detail', '')))

print("\n=== 5. CONFLICT ===")
act(text().replace('metered_holding_release_density: 3.0',
                   'metered_holding_release_density: 1.8'), 'metering 1.8')
r = revert(vseq(3)['id'])
check("revert of an overwritten change returns 409", r.status_code == 409, r.status_code)
d = r.json().get('detail', {})
check("the conflict names the block it expected",
      any('3.0' in ''.join(x.get('expected', [])) for x in d.get('conflicts', [])),
      d.get('conflicts'))
check("the conflict explains why", 'already changed by a later version'
      in str(d.get('conflicts')))
before = text()
check("nothing was changed by the failed revert", text() == before)
check("the document is still valid after a failed revert",
      c.post(f'/api/policy/documents/{K}/validate', json={'text': text()}).json()['valid'])

print("\n=== 6. A REVERT THAT WOULD PRODUCE AN INVALID DOCUMENT ===")
# This needs a document with no history yet, so the two versions below are v2 and
# v3 of a clean chain. Give the register a store of its own for this section
# rather than reusing the one the sections above have been amending.
import app.main as M                                            # noqa: E402
from app.config import get_settings                             # noqa: E402
from app.policy.service import PolicyService                    # noqa: E402
from app.policy.store import build_policy_store                 # noqa: E402

_prev_root = os.environ["RAILSETU_POLICY_LOCAL_ROOT"]
_fresh = ROOT / "tests" / ".work" / "revert" / "invalid-case"
shutil.rmtree(_fresh, ignore_errors=True)
_fresh.mkdir(parents=True, exist_ok=True)
os.environ["RAILSETU_POLICY_LOCAL_ROOT"] = str(_fresh)
get_settings.cache_clear()
_saved = M.POLICY
M.POLICY = PolicyService(build_policy_store(get_settings()), get_settings())
M.POLICY.bootstrap()

check("the section starts from a clean chain", len(hist()) == 1, len(hist()))
# v2 raises the crush ceiling; v3 then raises 'dangerous' into the space it opened.
act(text().replace('crush_above: 5.0', 'crush_above: 8.0'), 'v2 crush ceiling 8.0')
act(text().replace('dangerous_above: 3.5', 'dangerous_above: 7.0'), 'v3 dangerous 7.0')
r = revert(vseq(2)['id'])          # would leave dangerous 7.0 > crush 5.0
check("a revert that would break the rules is refused", r.status_code == 400, r.status_code)
check("...and says which rule it would break",
      'increase strictly' in str(r.json().get('detail', '')), r.json().get('detail'))
check("the document in force is unharmed",
      'crush_above: 8.0' in text() and 'dangerous_above: 7.0' in text())
check("...and no version was written for the refused revert", len(hist()) == 3, len(hist()))

os.environ["RAILSETU_POLICY_LOCAL_ROOT"] = _prev_root
get_settings.cache_clear()
M.POLICY = _saved

print("\n=== 7. WRITTEN STANDARDS (prose, not rules) ===")
NK = 'incident-escalation'
base = text(NK)
act(base.replace('10 minutes', '5 minutes'), 'tighten to 5 minutes', k=NK)
act(text(NK).replace('same day', 'within 4 hours'), 'same day -> 4 hours', k=NK)
r = revert(vseq(2, NK)['id'], k=NK)
check("prose documents can be reverted too", r.status_code == 200, r.json().get('detail'))
t = text(NK)
check("the reverted line is restored", '10 minutes' in t)
check("the later prose edit survives", 'within 4 hours' in t)

print("\n=== 8. PATCH SHAPES (unit level) ===")
def rp(parent, version, current):
    return reverse_patch(parent, version, current)
p = "a\nb\nc\nd\n"
check("pure insertion is backed out",
      rp(p, "a\nb\nNEW\nc\nd\n", "a\nb\nNEW\nc\nd\n")[0] == p)
check("pure deletion is restored",
      rp(p, "a\nb\nd\n", "a\nb\nd\n")[0] == p)
check("replacement is undone",
      rp(p, "a\nB!\nc\nd\n", "a\nB!\nc\nd\n")[0] == p)
check("change at the first line",
      rp(p, "A!\nb\nc\nd\n", "A!\nb\nc\nd\n")[0] == p)
check("change at the last line",
      rp(p, "a\nb\nc\nD!\n", "a\nb\nc\nD!\n")[0] == p)
check("multi-line block",
      rp(p, "a\nX\nY\nZ\nd\n", "a\nX\nY\nZ\nd\n")[0] == p)
new, cf = rp(p, "a\nb\nc\nd\n", "a\nb\nc\nd\n")
check("a version that changed nothing reports so", cf and 'changed nothing' in cf[0]['reason'])
# ambiguity: the same line appears twice and context cannot disambiguate
amb_parent, amb_version = "x\nx\n", "x\nx\nx\n"
new, cf = rp(amb_parent, amb_version, amb_version)
check("ambiguous or unlocatable blocks do not silently corrupt",
      new is None or new == amb_parent, f"new={new!r} conflicts={cf}")
# trailing-newline handling
check("trailing newline preserved",
      rp("a\nb\n", "a\nB\n", "a\nB\n")[0].endswith("\n"))
check("no trailing newline preserved",
      not rp("a\nb", "a\nB", "a\nB")[0].endswith("\n"))

print("\n=== 9. RESTORE IS STILL THE OTHER THING ===")
r = restore(vseq(1, NK)['id'], k=NK)
check("restore succeeds", r.status_code == 200, r.json().get('detail'))
check("restore discards ALL later changes",
      '10 minutes' in text(NK) and 'within 4 hours' not in text(NK))
check("restore is tagged separately from revert",
      vseq(len(hist(NK)), NK)['rollback_of'] is not None
      and vseq(len(hist(NK)), NK)['reverts'] is None)
check("restoring the version already in force is refused",
      restore(vseq(len(hist(NK)), NK)['id'], k=NK).status_code == 400)

print("\n=== 10. ATTRIBUTION AND LOCATION ON A REVERT ===")
# Make a fresh, definitely-revertable change on a clean document.
GK = 'demand-assumptions'
act(text(GK).replace('unload_duration_s: 180', 'unload_duration_s: 240'),
    'unload 240s', k=GK)
target = vseq(2, GK)['id']
r = c.post(f'/api/policy/documents/{GK}/revert',
           json={'version_id': target,
                 'location': {'latitude': 28.6428, 'longitude': 77.2191, 'accuracy_m': 12}})
check("revert with a location succeeds", r.status_code == 200, r.json().get('detail'))
v = r.json()['version']
check("attributed to the signed-in account", v['author_email'] == 'edge@ir.gov.in')
check("records the coordinates", v['location']['available']
      and v['location']['latitude'] == 28.6428, v['location'])
check("records the accuracy", v['location']['accuracy_m'] == 12)
check("records the server-observed address", 'client_ip' in v['location'])
check("the reverted value is back", 'unload_duration_s: 180' in text(GK))

r2 = c.post(f'/api/policy/documents/{GK}/revert',
            json={'version_id': target, 'location': {'available': False,
                                                     'reason': 'permission denied'}})
check("a revert with location refused still works or is a clean no-op",
      r2.status_code in (200, 400), r2.status_code)
if r2.status_code == 200:
    check("...and records the refusal honestly, inventing nothing",
          r2.json()['version']['location']['available'] is False
          and 'latitude' not in r2.json()['version']['location'],
          r2.json()['version']['location'])

print(f"\n{'='*60}\nREVERT EDGE CASES: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILURES:")
    for f in FAIL: print("   -", f)
sys.exit(1 if FAIL else 0)
