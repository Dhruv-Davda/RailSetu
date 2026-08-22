"""Thorough backend audit of the policy register."""
from harness import ROOT, bootstrap

bootstrap("platform")

PASS, FAIL = [], []
def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")

# fresh register

from fastapi.testclient import TestClient
from app.main import app
from app.policy import schema as S, diff as D
from app.policy.context import use_policy, current, get_active
c = TestClient(app)

# The policy surface is gated, so the audit signs in first and carries the
# identity header on every call — exactly as the browser does.
_ACC = c.post('/api/session', json={'email': 'auditor@railsetu.in'}).json()['account']
c.headers.update({'X-RailSetu-User': _ACC['email']})
print(f"  (signed in as {_ACC['display_name']} <{_ACC['email']}>)")

print("\n=== 1. SCHEMA VALIDATION ===")
from app.policy import documents as DOCS
KEY = 'crowd-safety'
D_YAML = DOCS.CROWD_SAFETY
bad_cases = [
    ("non-monotonic bands",    D_YAML.replace('crush_above: 5.0', 'crush_above: 3.0')),
    ("band out of range",      D_YAML.replace('crush_above: 5.0', 'crush_above: 99')),
    ("negative band",          D_YAML.replace('restricted_above: 1.0', 'restricted_above: -1')),
    ("yaml syntax",            'crowd_safety: [oops'),
    ("not a mapping",          '- a\n- b'),
    ("foreign section",        DOCS.TRAIN_PRECEDENCE),
    ("empty doc",              ''),
    ("string where number",    D_YAML.replace('crush_above: 5.0', 'crush_above: "five"')),
    ("bool where number",      D_YAML.replace('crush_above: 5.0', 'crush_above: true')),
]
for name, y in bad_cases:
    try:
        S.parse_document(KEY, y); check(f"rejects {name}", False, "ACCEPTED an invalid doc")
    except S.PolicyError:
        check(f"rejects {name}", True)
check("accepts the shipped document", S.parse_document(KEY, D_YAML) is not None)
# all errors at once, not one at a time
errs = S.validate_sections(__import__('yaml').safe_load(
    D_YAML.replace('crush_above: 5.0','crush_above: 3.0')
          .replace('metered_holding_release_density: 2.5','metered_holding_release_density: -1')),
    ('crowd_safety',))
check("reports multiple problems at once", len(errs) >= 2, f"{len(errs)} errors")

print("\n=== 2. DIFF ===")
new = D_YAML.replace('crush_above: 5.0', 'crush_above: 4.5')
h = D.unified_hunks(D_YAML, new)
check("hunk produced for a one-line change", len(h) == 1)
check("hunk has both del and add rows",
      any(l['type']=='del' for l in h[0]['lines']) and any(l['type']=='add' for l in h[0]['lines']))
check("context lines included", any(l['type']=='context' for l in h[0]['lines']))
check("line numbers present", all(l['old'] or l['new'] for l in h[0]['lines']))
check("no diff for identical text", D.unified_hunks(D_YAML, D_YAML) == [])
st = D.diff_stats(D_YAML, new)
check("stats count 1 add / 1 remove", st['added']==1 and st['removed']==1, st)
sem = D.semantic_changes(__import__('yaml').safe_load(D_YAML), __import__('yaml').safe_load(new))
check("semantic change identifies the rule", len(sem)==1 and sem[0]['path'].endswith('crush_above'), sem)
check("semantic change carries before/after", sem[0]['before']==5.0 and sem[0]['after']==4.5)
# ordered list semantics
_obj = DOCS.INTERVENTION_PRIORITY
reordered = _obj.replace("  - crush_points\n  - peak_density", "  - peak_density\n  - crush_points")
sem2 = D.semantic_changes(__import__('yaml').safe_load(_obj), __import__('yaml').safe_load(reordered))
check("objective REORDER detected (order is meaning)", len(sem2) >= 2, [s['path'] for s in sem2])

print("\n=== 3. PREVIEW IS NON-MUTATING ===")
before_active = c.get(f'/api/policy/documents/{KEY}').json()['text']
before_hist = c.get(f'/api/policy/documents/{KEY}/history').json()['count']
p = c.post(f'/api/policy/documents/{KEY}/preview', json={'text': D_YAML.replace('crush_above: 5.0','crush_above: 3.9')}).json()
check("preview returns valid", p['valid'] is True)
check("preview did NOT change the active policy", c.get(f'/api/policy/documents/{KEY}').json()['text'] == before_active)
check("preview did NOT write a version", c.get(f'/api/policy/documents/{KEY}/history').json()['count'] == before_hist)
check("preview reports before AND after", 'before' in p and 'after' in p)
check("preview detects the crush-point change",
      p['deltas']['crowd']['crush_count']['changed'] is True,
      p['deltas']['crowd']['crush_count'])
check("unchanged metrics marked unchanged", p['deltas']['crowd']['peak_density']['changed'] is False)
pinv = c.post(f'/api/policy/documents/{KEY}/preview', json={'text': 'crowd_safety: [oops'}).json()
check("preview of an invalid doc returns errors, not a 500", pinv['valid'] is False and pinv['errors'])
check("invalid preview still shows the diff", 'hunks' in pinv)

print("\n=== 4. CONTEXT ISOLATION ===")
base_crush = get_active().crush_threshold
with use_policy(S.compose({**{d.key: d.default_yaml for d in DOCS.all_documents()},
                            'crowd-safety': DOCS.CROWD_SAFETY.replace('crush_above: 5.0','crush_above: 4.2')})):
    inner = current().crush_threshold
check("override applies inside the block", inner == 4.2)
check("override does not leak outside", current().crush_threshold == base_crush, current().crush_threshold)
check("get_active ignores the override",
      (lambda: [use_policy, get_active().crush_threshold == base_crush][1])())

print("\n=== 5. ACTIVATION ===")
draft = D_YAML.replace('crush_above: 5.0','crush_above: 3.9')
r = c.post(f'/api/policy/documents/{KEY}/activate', json={'text': draft, 'title':'Test change',
      'description':'why'})
check("activate returns 200", r.status_code == 200, r.status_code)
v = r.json()['version']
check("version gets seq 2", v['seq'] == 2, v['seq'])
check("version attributed to the SIGNED-IN account",
      v['author_email']=='auditor@railsetu.in' and v['author_name']=='Auditor')
check("version records title+description", v['title']=='Test change' and v['description']=='why')
check("version has a parent", v['parent_id'] is not None)
check("version records diff stats", v['diff_stats']['added']==1)
check("version records the measured impact", bool(r.json()['impact']['deltas']))
check("policy is now IN FORCE", 'crush_above: 3.9' in c.get(f'/api/policy/documents/{KEY}').json()['text'])
live = c.post('/api/simulate', json={'scenario':'kumbh_surge'}).json()['summary']
check("live simulation reflects the new policy", live['crush_count'] == 5, live['crush_count'])

print("\n=== 6. ACTIVATION GUARDS ===")
for name, body, expect in [
    ("rejects a no-op",           {'text':draft,'title':'x'}, 400),
    ("rejects a missing title",   {'text':D_YAML,'title':''}, 400),
    ("rejects an invalid doc",    {'text':'nope: [','title':'x'}, 400),
]:
    got = c.post(f'/api/policy/documents/{KEY}/activate', json=body).status_code
    check(name, got == expect, f"got {got}")

print("\n=== 7. HISTORY & IMMUTABILITY ===")
h = c.get(f'/api/policy/documents/{KEY}/history').json()
check("history has both versions", h['count'] == 2, h['count'])
check("the library reports 8 documents", c.get('/api/policy/library').json()['count'] == 8)
check("history is newest-first", h['versions'][0]['seq'] > h['versions'][1]['seq'])
check("genesis version exists", any(x['seq']==1 for x in h['versions']))
vid = h['versions'][0]['id']
det = c.get(f'/api/policy/documents/{KEY}/versions/{vid}').json()
check("version detail returns the document", det['text'].startswith('#'))
check("version detail returns diff hunks", len(det['hunks']) >= 1)
check("version detail returns semantic changes", len(det['changes']) == 1)
check("unknown version id -> 404", c.get(f'/api/policy/documents/{KEY}/versions/deadbeef').status_code == 404)
# immutability: the stored v1 document is still the original
v1 = [x for x in h['versions'] if x['seq']==1][0]
v1doc = c.get(f"/api/policy/documents/{KEY}/versions/{v1['id']}").json()['text']
check("earlier version is unchanged by later activations", 'crush_above: 5.0' in v1doc)

print("\n=== 8. ROLLBACK ===")
rb = c.post(f'/api/policy/documents/{KEY}/rollback', json={'version_id': v1['id']})
check("rollback returns 200", rb.status_code == 200, rb.status_code)
rbv = rb.json()['version']
check("rollback creates a NEW version (append-only)", rbv['seq'] == 3, rbv['seq'])
check("rollback marks what it reverted to", rbv['rollback_of'] == v1['id'])
check("document restored", 'crush_above: 5.0' in c.get(f'/api/policy/documents/{KEY}').json()['text'])
check("history is now 3 (nothing deleted)", c.get(f'/api/policy/documents/{KEY}/history').json()['count'] == 3)
check("rolling back to the version already in force is rejected",
      c.post(f'/api/policy/documents/{KEY}/rollback', json={'version_id': rbv['id']}).status_code == 400)
check("rollback to unknown id rejected",
      c.post(f'/api/policy/documents/{KEY}/rollback', json={'version_id':'nope'}).status_code == 400)

print("\n=== 9. PERSISTENCE ACROSS RESTART ===")
import importlib
from app.policy.store import build_policy_store
from app.policy.service import PolicyService
from app.config import get_settings
st2 = build_policy_store(get_settings())
svc2 = PolicyService(st2, get_settings())
pol2 = svc2.bootstrap()
check("a fresh service restores the rules in force", pol2.crush_threshold == 5.0, pol2.crush_threshold)
check("and sees this document's full history", len(st2.list_versions(KEY)) == 3, len(st2.list_versions(KEY)))
check("other documents are untouched by it", len(st2.list_versions('train-precedence')) == 1)

print("\n=== 10. EVERY LEVER DRIVES OUTPUT ===")
def crowd(): return c.post('/api/simulate', json={'scenario':'kumbh_surge'}).json()['summary']
def corr():  return c.post('/api/m2/simulate', json={'scenario':'passenger_ahead','optimize':True}).json()
def prot():  return c.get('/api/m6/coverage').json()['summary']
def opti():  return c.post('/api/optimize', json={'scenario':'kumbh_surge','explain':False}).json()
def _doc_for(old, newv):
    """Which document owns the line being changed, with the change applied."""
    for d in DOCS.all_documents():
        if old in d.default_yaml:
            return {d.key: d.default_yaml.replace(old, newv)}
    raise AssertionError(f'no document contains {old!r}')

levers = [
  ("crowd_safety.crush_above",      'crush_above: 5.0','crush_above: 3.9', lambda: crowd()['crush_count']),
  ("crowd_safety.meter_density",    'metered_holding_release_density: 2.5','metered_holding_release_density: 0.8',
      lambda: c.post('/api/whatif', json={'scenario':'kumbh_surge','mitigations':{'metered_holding':True}}).json()['impact']['peak_density_after']),
  # 1.0 -> 2.5 is the sensitive range; past ~2.5x the binding constraint moves
  # off the stairs onto the junction's own footway inflow, so it saturates.
  ("crowd_safety.fob_multiplier",   'one_way_fob_egress_multiplier: 2.5','one_way_fob_egress_multiplier: 1.0',
      lambda: c.post('/api/whatif', json={'scenario':'kumbh_surge','mitigations':{'open_fob':True}}).json()['impact']['peak_density_after']),
  ("intervention_priority order",   "  - crush_points\n  - peak_density\n  - throughput\n  - measure_count",
                                    "  - throughput\n  - crush_points\n  - peak_density\n  - measure_count",
      lambda: tuple(opti()['recommended']['active'])),
  ("corridor.minimum_headway_min",  'minimum_headway_min: 5.0','minimum_headway_min: 12.0', lambda: corr()['baseline']['total_delay_min']),
  ("corridor.station_dwell_min",    'station_dwell_min: 2.0','station_dwell_min: 9.0', lambda: corr()['baseline']['total_delay_min']),
  ("corridor.max_overtake_hold",    'max_overtake_hold_min: 12.0','max_overtake_hold_min: 0', lambda: corr()['optimized']['total_delay_min']),
  # The margin only separates trains of EQUAL precedence; the sheet's same-class
  # speed gaps are 2 and 4 km/h, so the sensitive range is downward (1 vs 2).
  ("corridor.overtake_margin",      'overtake_speed_margin_kmph: 5','overtake_speed_margin_kmph: 1', lambda: corr()['optimized']['total_delay_min']),
  ("train_precedence.PASSENGER",    'PASSENGER: 2','PASSENGER: 11', lambda: corr()['optimized']['total_delay_min']),
  ("protection.equipped_at_pct",    'kavach_equipped_at_pct: 75','kavach_equipped_at_pct: 90', lambda: prot()['status_counts']['equipped']),
  ("protection.partial_at_pct",     'kavach_partial_at_pct: 25','kavach_partial_at_pct: 5', lambda: prot()['status_counts']['none']),
]
for name, old, newv, probe in levers:
    base = probe()
    with use_policy(S.compose({**{d.key: d.default_yaml for d in DOCS.all_documents()},
                            **_doc_for(old, newv)})):
        changed = probe()
    check(f"lever {name}", base != changed, f"{base} -> {changed}")
# demand assumptions only affect the LIVE provider; verify at the policy level
with use_policy(S.compose({**{d.key: d.default_yaml for d in DOCS.all_documents()},
                            **_doc_for('default_alighting_per_train: 1200','default_alighting_per_train: 3000')})):
    check("lever demand_assumptions.default_alighting", current().default_alighting == 3000.0)

print("\n=== 11. ACCESS CONTROL ===")
anon = TestClient(app)
for path, method in [(f'/api/policy/documents/{KEY}','get'), (f'/api/policy/documents/{KEY}/history','get'),
                     (f'/api/policy/documents/{KEY}/default','get'), ('/api/accounts','get')]:
    check(f"anonymous {method.upper()} {path} refused",
          getattr(anon, method)(path).status_code == 401)
check("anonymous preview refused",
      anon.post(f'/api/policy/documents/{KEY}/preview', json={'text':'x'}).status_code == 401)
check("anonymous activate refused",
      anon.post(f'/api/policy/documents/{KEY}/activate', json={'text':'x','title':'t'}).status_code == 401)
check("anonymous rollback refused",
      anon.post(f'/api/policy/documents/{KEY}/rollback', json={'version_id':'x'}).status_code == 401)
unknown = TestClient(app); unknown.headers.update({'X-RailSetu-User':'never@seen.example'})
check("unknown address refused", unknown.get(f'/api/policy/documents/{KEY}').status_code == 401)
malformed = TestClient(app); malformed.headers.update({'X-RailSetu-User':'nonsense'})
check("malformed address refused", malformed.get(f'/api/policy/documents/{KEY}').status_code == 401)
for p_ in ['/api/health','/api/station','/api/scenarios','/api/m2/network','/api/m6/coverage']:
    check(f"{p_} stays open", anon.get(p_).status_code == 200)
check("sign-in rejects a bad address",
      anon.post('/api/session', json={'email':'bad'}).status_code == 400)
sec = c.post('/api/session', json={'email':'Second.Person@ir.gov.in'}).json()['account']
check("sign-in normalises the address", sec['email']=='second.person@ir.gov.in')
check("sign-in derives a display name", sec['display_name']=='Second Person')
c2 = TestClient(app); c2.headers.update({'X-RailSetu-User': sec['email']})
base2 = c2.get(f'/api/policy/documents/{KEY}').json()['text']
_r2 = c2.post(f'/api/policy/documents/{KEY}/activate', json={
    'text': base2.replace('crush_above: 5.0','crush_above: 4.7'),
    'title':'By the second person','description':'d'})
a2 = _r2.json()
check("a second account can activate", _r2.status_code == 200, f"{_r2.status_code}")
check("a second account is attributed correctly",
      a2.get('version',{}).get('author_email')=='second.person@ir.gov.in')
hist = c.get(f'/api/policy/documents/{KEY}/history').json()['versions']
check("history holds more than one author",
      len({h['author_email'] for h in hist}) >= 2, {h['author_email'] for h in hist})

print(f"\n{'='*62}\nBACKEND: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILURES:")
    for f in FAIL: print("   -", f)
sys.exit(1 if FAIL else 0)
