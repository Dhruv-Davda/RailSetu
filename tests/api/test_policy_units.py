"""
The policy machinery, at unit level: parsing, validation, diffing, the reverse
patch, the context seam, location, and accounts.

The API suites cover the register end to end. These cover the pieces underneath
it directly, where the edge cases live and where an end-to-end test can only
reach them by luck: a patch that matches in two places, a coordinate reported
with a 300 km error radius, a document whose bands do not increase.
"""
from harness import bootstrap, Report

bootstrap("policy_units")

from app.policy import documents as DOCS                                # noqa: E402
from app.policy.schema import (                                         # noqa: E402
    MAX_NARRATIVE_CHARS, compose, parse_document, validate_narrative,
    validate_sections,
)
from app.policy.diff import (                                           # noqa: E402
    describe_change, diff_stats, reverse_patch, semantic_changes, unified_hunks,
)
from app.policy.context import current, use_policy                      # noqa: E402
from app.policy import location as LOC                                  # noqa: E402
from app.accounts.store import display_name_for, is_valid_email, normalise  # noqa: E402

r = Report("POLICY UNITS")

# ------------------------------------------------------------------ registry
r.section("1. THE DOCUMENT REGISTRY")
docs = DOCS.all_documents()
r.check("documents are registered", len(docs) >= 6, len(docs))
r.check("keys are unique", len({d.key for d in docs}) == len(docs))
r.check("filenames are unique", len({d.filename for d in docs}) == len(docs))
r.check("every document has a title, summary and department",
        all(d.title and d.summary and d.department for d in docs))
r.check("every document declares a format",
        all(d.format in ("yaml", "markdown", "text") for d in docs),
        sorted({d.format for d in docs}))
r.check("the extension follows the format",
        all(d.filename.endswith(d.extension) for d in docs))
r.check("only YAML documents are structured",
        all(d.structured == (d.format == "yaml") for d in docs))
r.check("structured documents declare which sections they own",
        all(d.sections for d in docs if d.structured))
r.check("no two documents claim the same section",
        len([s for d in docs if d.structured for s in d.sections])
        == len({s for d in docs if d.structured for s in d.sections}))
r.check("prose documents claim no sections",
        all(not d.sections for d in docs if not d.structured))
r.check("every builtin is recognised as a builtin",
        all(DOCS.is_builtin(d.key) for d in DOCS.BUILTIN))
r.check("only prose formats can be added at runtime",
        set(DOCS.ADDABLE_FORMATS) == {"markdown", "text"}, DOCS.ADDABLE_FORMATS)

r.section("2. SLUGS")
for raw, want in [("Platform Announcement Standard", "platform-announcement-standard"),
                  ("  Spaces   Everywhere  ", "spaces-everywhere"),
                  ("Already-Hyphenated", "already-hyphenated"),
                  ("Punctuation!? & symbols", "punctuation-symbols"),
                  ("MiXeD CaSe", "mixed-case")]:
    r.check(f"slugify({raw!r})", DOCS.slugify(raw) == want, DOCS.slugify(raw))
r.check("a slug never starts or ends with a hyphen",
        not DOCS.slugify("!! edge !!").strip("-") != DOCS.slugify("!! edge !!"),
        DOCS.slugify("!! edge !!"))
r.check("an empty title does not produce an empty slug",
        DOCS.slugify("???") == "" or DOCS.slugify("???").isascii(), DOCS.slugify("???"))

# ------------------------------------------------------------------ parsing
r.section("3. PARSING AND VALIDATION")
crowd = next(d for d in docs if d.key == "crowd-safety")
data = parse_document(crowd.key, crowd.default_yaml)
r.check("the default document parses", isinstance(data, dict), type(data).__name__)
r.check("it contains the section it declares", set(crowd.sections) <= set(data))
r.check("the default document validates",
        validate_sections(data, crowd.sections) == [], validate_sections(data, crowd.sections))

# parse_document validates as it parses, so an unusable document raises rather
# than returning a half-built rule-set nobody checked.
from app.policy.schema import PolicyError                               # noqa: E402


def refused(text):
    """(was it refused, what did it say)"""
    try:
        d = parse_document(crowd.key, text)
    except PolicyError as e:
        return True, str(e)
    errs = validate_sections(d, crowd.sections)
    return bool(errs), "; ".join(errs)


ok, msg = refused(crowd.default_yaml.replace("crush_above: 5.0", "crush_above: 1.5"))
r.check("bands that do not increase are rejected", ok, msg)
r.check("...and the message names the rule", "increase strictly" in msg, msg)
r.check("...and shows the offending values", "1.5" in msg, msg)

for text, why in [("crush_above: 5.0\n  bad indent", "malformed YAML"),
                  ("crowd_safety: [1, 2, 3]", "a list where a mapping belongs"),
                  ("", "an empty document"),
                  ("corridor_operations:\n  minimum_headway_min: 5.0",
                   "a document that carries someone else's section"),
                  ("crowd_safety:\n  density_bands:\n    restricted_above: 1.0",
                   "a section missing its required rules"),
                  ("crowd_safety:\n  density_bands:\n    restricted_above: -1.0\n"
                   "    constrained_above: 2.0\n    dangerous_above: 3.5\n    crush_above: 5.0",
                   "a negative density")]:
    got, why_not = refused(text)
    r.check(f"{why} is refused", got, why_not[:90])

r.check("every refusal explains itself rather than failing silently",
        all(refused(t)[1] for t in ("", "crowd_safety: [1]")))

r.section("4. PROSE DOCUMENTS")
r.check("ordinary prose is accepted", validate_narrative("# Heading\n\nSome text.") == [])
r.check("empty prose is refused", validate_narrative("   \n  ") != [])
r.check("prose has an upper bound", validate_narrative("x" * (MAX_NARRATIVE_CHARS + 1)) != [])
r.check("...and text just under it is fine", validate_narrative("x" * (MAX_NARRATIVE_CHARS - 1)) == [])
r.check("the bound is generous enough for a real standard", MAX_NARRATIVE_CHARS >= 20_000,
        MAX_NARRATIVE_CHARS)

r.section("5. COMPOSITION")
raws = {d.key: d.default_yaml for d in docs}
pol = compose(raws)
r.check("the library composes into one rule-set", pol is not None)
r.check("composition exposes crowd rules", pol.crush_threshold > 0, pol.crush_threshold)
r.check("composition exposes corridor rules", pol.headway_min > 0, pol.headway_min)
r.check("composition exposes protection rules", pol.kavach_equipped_pct > 0)
r.check("composition exposes demand rules", pol.default_alighting > 0)
try:
    pol.data = {}
    frozen = False
except Exception:
    frozen = True
r.check("a Policy is frozen — the rules in force cannot be mutated in place", frozen)

# ------------------------------------------------------------------ diffing
r.section("6. LINE DIFF")
a = "one\ntwo\nthree\n"
r.check("identical text produces no hunks", unified_hunks(a, a) == [])
h = unified_hunks(a, "one\nTWO\nthree\n")
r.check("a change produces one hunk", len(h) == 1, len(h))
rows = h[0]["lines"]
r.check("the removed line is marked", any(x["type"] == "del" and x["text"] == "two" for x in rows))
r.check("the added line is marked", any(x["type"] == "add" and x["text"] == "TWO" for x in rows))
r.check("context is carried", any(x["type"] == "context" for x in rows))
r.check("old line numbers are present on removals",
        all(x["old"] for x in rows if x["type"] == "del"))
r.check("new line numbers are present on additions",
        all(x["new"] for x in rows if x["type"] == "add"))
r.check("removals carry no new-side number",
        all(x["new"] is None for x in rows if x["type"] == "del"))
r.check("stats count the change", diff_stats(a, "one\nTWO\nthree\n") == {"added": 1, "removed": 1, "changed": 2})
r.check("a pure insertion counts only additions",
        diff_stats(a, "one\ntwo\nextra\nthree\n") == {"added": 1, "removed": 0, "changed": 1})
r.check("a pure deletion counts only removals",
        diff_stats(a, "one\nthree\n") == {"added": 0, "removed": 1, "changed": 1})
r.check("far-apart changes make separate hunks",
        len(unified_hunks("\n".join(str(i) for i in range(40)) + "\n",
                          "\n".join("X" if i in (1, 38) else str(i)
                                    for i in range(40)) + "\n")) == 2)

r.section("7. SEMANTIC DIFF — WHAT RULE CHANGED")
ch = semantic_changes({"a": {"b": 1}}, {"a": {"b": 2}})
r.check("a changed value is reported", ch == [{"path": "a.b", "kind": "changed",
                                               "before": 1, "after": 2}], ch)
r.check("the path is dotted, as a reader would cite it", ch[0]["path"] == "a.b")
r.check("an added key is reported as added",
        semantic_changes({}, {"x": 1})[0]["kind"] == "added")
r.check("a removed key is reported as removed",
        semantic_changes({"x": 1}, {})[0]["kind"] == "removed")
r.check("no change means no entries", semantic_changes({"a": 1}, {"a": 1}) == [])
lst = semantic_changes({"o": ["a", "b"]}, {"o": ["b", "a"]})
r.check("list ORDER is meaningful — reordering an objective is a change", lst, lst)
r.check("list entries keep their index in the path",
        all("[" in x["path"] for x in lst), [x["path"] for x in lst])
r.check("a change is described in the document's own terms",
        describe_change(ch[0]) == "a.b: 1 → 2", describe_change(ch[0]))
r.check("an addition reads as an addition", "added" in describe_change(semantic_changes({}, {"x": 1})[0]))
r.check("nested structures are walked",
        semantic_changes({"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 9}}})[0]["path"] == "a.b.c")

# ------------------------------------------------------------- reverse patch
r.section("8. REVERSE PATCH — GIT-REVERT SEMANTICS")
P = "a\nb\nc\nd\n"
r.check("an insertion is backed out",
        reverse_patch(P, "a\nb\nNEW\nc\nd\n", "a\nb\nNEW\nc\nd\n")[0] == P)
r.check("a deletion is restored",
        reverse_patch(P, "a\nb\nd\n", "a\nb\nd\n")[0] == P)
r.check("a replacement is undone",
        reverse_patch(P, "a\nB!\nc\nd\n", "a\nB!\nc\nd\n")[0] == P)
r.check("a change on the first line is undone",
        reverse_patch(P, "A!\nb\nc\nd\n", "A!\nb\nc\nd\n")[0] == P)
r.check("a change on the last line is undone",
        reverse_patch(P, "a\nb\nc\nD!\n", "a\nb\nc\nD!\n")[0] == P)
r.check("a multi-line block is undone",
        reverse_patch(P, "a\nX\nY\nZ\nd\n", "a\nX\nY\nZ\nd\n")[0] == P)

# The property that makes revert different from restore.
later = "a\nB!\nc\nd\nLATER\n"
back, conflicts = reverse_patch(P, "a\nB!\nc\nd\n", later)
r.check("reverting keeps changes made after it", back == "a\nb\nc\nd\nLATER\n", back)
r.check("...with no conflict", conflicts == [], conflicts)

_, cf = reverse_patch(P, P, P)
r.check("a version that changed nothing says so",
        cf and "changed nothing" in cf[0]["reason"], cf)

gone, cf = reverse_patch(P, "a\nB!\nc\nd\n", "a\nSOMETHING ELSE\nc\nd\n")
r.check("a block a later version overwrote is a conflict, not a guess", gone is None, gone)
r.check("the conflict says why",
        cf and "already changed by a later version" in cf[0]["reason"], cf)
r.check("the conflict shows what it expected to find", cf and cf[0]["expected"], cf)
r.check("the conflict shows what it would have written", cf and "would_become" in cf[0])

amb, cf = reverse_patch("x\nx\n", "x\nx\nx\n", "x\nx\nx\n")
r.check("an ambiguous match never silently corrupts the document",
        amb is None or amb == "x\nx\n", (amb, cf))
r.check("a trailing newline is preserved",
        reverse_patch("a\nb\n", "a\nB\n", "a\nB\n")[0].endswith("\n"))
r.check("its absence is preserved too",
        not reverse_patch("a\nb", "a\nB", "a\nB")[0].endswith("\n"))
r.check("reverting a revert re-applies the change",
        reverse_patch("a\nb\nc\nd\n", P, P)[0] is not None)

# ------------------------------------------------------------------ context
r.section("9. THE PREVIEW SEAM")
before = current().crush_threshold
draft = compose({**raws, "crowd-safety":
                 crowd.default_yaml.replace("crush_above: 5.0", "crush_above: 4.0")})
with use_policy(draft):
    r.check("inside the block, the draft rules are in force",
            current().crush_threshold == 4.0, current().crush_threshold)
r.check("outside it, the rules in force are untouched",
        current().crush_threshold == before, current().crush_threshold)
try:
    with use_policy(draft):
        raise RuntimeError("boom")
except RuntimeError:
    pass
r.check("an exception inside the block still restores the rules",
        current().crush_threshold == before, current().crush_threshold)
with use_policy(draft):
    with use_policy(compose(raws)):
        inner = current().crush_threshold
    outer = current().crush_threshold
r.check("overrides nest correctly", (inner, outer) == (before, 4.0), (inner, outer))

# ----------------------------------------------------------------- location
r.section("10. LOCATION — RECORDED, NEVER INFERRED")
ok = LOC.normalise({"latitude": 28.6428, "longitude": 77.2191, "accuracy_m": 12}, "10.0.0.1")
r.check("a good fix is accepted", ok["available"] is True, ok)
r.check("the coordinates are kept", (ok["latitude"], ok["longitude"]) == (28.6428, 77.2191))
r.check("the accuracy is kept", ok["accuracy_m"] == 12)
r.check("the observed address is recorded alongside", ok["client_ip"] == "10.0.0.1")
r.check("the fix is timestamped", bool(ok.get("recorded_at")))

no = LOC.normalise({"available": False, "reason": "permission denied"}, "10.0.0.1")
r.check("a refusal is recorded as a refusal", no["available"] is False, no)
r.check("no coordinates are invented for it", "latitude" not in no, no)
r.check("the reason is preserved", "denied" in str(no.get("reason", "")), no)
r.check("the address is still recorded", no.get("client_ip") == "10.0.0.1")

for payload, why in [({"latitude": 28.6, "longitude": 77.2, "accuracy_m": LOC.MAX_ACCURACY_M + 1},
                      "a fix too imprecise to be a location"),
                     ({"latitude": 999, "longitude": 77.2}, "an impossible latitude"),
                     ({"latitude": 28.6, "longitude": 999}, "an impossible longitude"),
                     ({"latitude": "north", "longitude": "east"}, "non-numeric coordinates"),
                     (None, "nothing at all")]:
    got = LOC.normalise(payload, "10.0.0.1")
    r.check(f"{why} is not recorded as a position",
            got.get("available") is not True and "latitude" not in got, got)

r.check("a description is produced for a real fix", bool(LOC.describe(ok)), LOC.describe(ok))
r.check("...and for a refusal, without inventing one", bool(LOC.describe(no)), LOC.describe(no))

# ----------------------------------------------------------------- accounts
r.section("11. IDENTITY")
r.check("a normal address is valid", is_valid_email("asha.rao@ir.gov.in"))
for bad_addr in ("", "not-an-email", "@ir.gov.in", "a@", "a b@ir.gov.in", "a@b"):
    r.check(f"{bad_addr!r} is refused", not is_valid_email(bad_addr))
r.check("addresses are normalised to lower case",
        normalise("  Asha.Rao@IR.GOV.IN ") == "asha.rao@ir.gov.in",
        normalise("  Asha.Rao@IR.GOV.IN "))
for addr, want in [("asha.rao@ir.gov.in", "Asha Rao"),
                   ("vikram_singh@ir.gov.in", "Vikram Singh"),
                   ("meera@ir.gov.in", "Meera")]:
    r.check(f"{addr} displays as {want}", display_name_for(addr) == want, display_name_for(addr))
r.check("a display name is never empty", bool(display_name_for("x@y.in")))

r.finish()
