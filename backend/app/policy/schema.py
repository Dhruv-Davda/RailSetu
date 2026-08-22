"""
The RailSetu operating-policy document: its default text, its parsed shape, and
its validation rules.

WHAT THIS IS. Every value here is a decision a railway authority makes — a
threshold in a safety standard, a precedence rule, a definition of "equipped".
None of it is physics. Walking speed, the simulation timestep and the node
catchment areas are deliberately NOT in this document: they are empirical or
numerical, nobody "decides" them, and putting them here would turn a policy
register into an arbitrary config editor.

WHY IT IS TEXT. The document is authored and stored as YAML, not as a form.
That is what makes it reviewable the way a rule change should be: it diffs
line by line, it carries comments explaining each rule, and a change to it
reads like an amendment rather than a database write.

Everything downstream (M1 crowd, M2 corridor, M6 protection) reads its rules
from a parsed instance of this document — see app/policy/context.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

# The four objectives the M1 mitigation optimizer can rank plans against.
OBJECTIVES = ("crush_points", "peak_density", "throughput", "measure_count")

OBJECTIVE_LABEL = {
    "crush_points": "Crush points (LOS F locations)",
    "peak_density": "Peak crowd density",
    "throughput": "People cleared in the horizon",
    "measure_count": "Number of measures to execute",
}

# Train classes the corridor model knows about. A precedence table must cover
# these; anything else is an unknown class and is rejected at validation.
TRAIN_CLASSES = (
    "RAJDHANI", "SHATABDI", "DURONTO", "SUPERFAST",
    "MAIL", "EXPRESS", "PASSENGER", "MEMU", "GOODS",
)


DEFAULT_POLICY_YAML = """\
# ═══════════════════════════════════════════════════════════════════════════
#  RailSetu — Operating Policy
#
#  Every value below is a rule someone decides, not a law of physics. Editing
#  this document changes how the crowd model, the corridor scheduler and the
#  protection audit behave.
#
#  Preview before you activate. Nothing here takes effect until it is pushed.
# ═══════════════════════════════════════════════════════════════════════════

meta:
  authority: Station Operations & Safety
  reference: RS-OP-001

# ─── Crowd safety thresholds ───────────────────────────────────────────────
# Fruin Level-of-Service bands, in persons per square metre. These define when
# a location is reported as restricted, dangerous, or a crush point.
#
# crush_above is the consequential one: it is the line between "very crowded"
# and "lethal". Lowering it does not change the crowd — it changes how many
# locations the platform is obliged to report and act on.
crowd_safety:
  density_bands:
    restricted_above: 1.0
    constrained_above: 2.0
    dangerous_above: 3.5
    crush_above: 5.0

  # When metered holding is in force, passengers are held upstream until the
  # space ahead falls below this density before more are released into it.
  metered_holding_release_density: 2.5

  # Assumed egress gain from converting a foot-over-bridge to one-way working
  # and opening reserve lanes. 2.5 = two and a half times normal throughput.
  one_way_fob_egress_multiplier: 2.5

# ─── Intervention priority ─────────────────────────────────────────────────
# The mitigation optimizer simulates all 16 combinations of the four controls
# and ranks them against this list, most important first.
#
# This is the most consequential rule in the document. Put throughput above
# peak_density and the optimizer will start recommending plans that move more
# people at higher risk. That is a legitimate policy position — but it should
# be a deliberate one, recorded, with a name against it.
#
# Valid entries: crush_points, peak_density, throughput, measure_count
intervention_priority:
  - crush_points
  - peak_density
  - throughput
  - measure_count

# ─── Corridor operating rules ──────────────────────────────────────────────
corridor_operations:
  # Minimum separation between two trains on the same section.
  minimum_headway_min: 5.0

  # How long a stopping train occupies a platform.
  station_dwell_min: 2.0
  terminal_dwell_min: 4.0

  # The dispatcher may hold a train at a loop for up to this long to let a
  # faster train overtake. Beyond this the hold costs more than it saves.
  max_overtake_hold_min: 12.0

  # A waiting train is only held for an approaching one if that train is at
  # least this much faster (km/h). Stops marginal overtakes.
  overtake_speed_margin_kmph: 5

# ─── Train precedence ──────────────────────────────────────────────────────
# Which class of train is protected when the corridor is congested. Higher
# wins. This is an equity decision as much as an operational one: PASSENGER
# at 2 means commuter services absorb delay so premium services do not.
train_precedence:
  RAJDHANI: 10
  SHATABDI: 9
  DURONTO: 9
  SUPERFAST: 7
  MAIL: 6
  EXPRESS: 5
  PASSENGER: 2
  MEMU: 2
  GOODS: 1

# ─── Protection standards ──────────────────────────────────────────────────
# What percentage of a route must carry Kavach before it counts as equipped.
# Raising the bar reclassifies corridors and lowers reported national
# coverage without a metre of track changing.
protection_standards:
  kavach_equipped_at_pct: 75
  kavach_partial_at_pct: 25

# ─── Demand assumptions ────────────────────────────────────────────────────
# The live arrivals feed returns trains, never passenger counts. These are the
# planning assumptions used to turn an arrival into a crowd. Replace with
# PRS/UTS or gate counts when available.
demand_assumptions:
  default_alighting_per_train: 1200
  special_train_multiplier: 2.2
  unload_duration_s: 180
"""


class PolicyError(ValueError):
    """The document is not a usable policy."""


@dataclass(frozen=True)
class Policy:
    """A parsed, validated operating policy.

    Held immutable so a preview run can never mutate the active policy by
    accident — a preview swaps the whole object, it does not edit one.
    """
    raw: str                                    # the YAML text, verbatim
    data: dict = field(default_factory=dict)    # parsed mapping

    # ---- M1 -------------------------------------------------------------

    @property
    def density_bands(self) -> list[tuple[float, str, str]]:
        """LOS bands in the (threshold, grade, label) shape simulation.py wants."""
        b = self.data["crowd_safety"]["density_bands"]
        return [
            (float(b["restricted_above"]), "A", "free"),
            (float(b["constrained_above"]), "C", "restricted"),
            (float(b["dangerous_above"]), "D", "constrained"),
            (float(b["crush_above"]), "E", "dangerous"),
            (99.0, "F", "crush"),
        ]

    @property
    def crush_threshold(self) -> float:
        return float(self.data["crowd_safety"]["density_bands"]["crush_above"])

    @property
    def meter_density(self) -> float:
        return float(self.data["crowd_safety"]["metered_holding_release_density"])

    @property
    def fob_egress_multiplier(self) -> float:
        return float(self.data["crowd_safety"]["one_way_fob_egress_multiplier"])

    @property
    def intervention_priority(self) -> list[str]:
        return list(self.data["intervention_priority"])

    # ---- M2 -------------------------------------------------------------

    @property
    def headway_min(self) -> float:
        return float(self.data["corridor_operations"]["minimum_headway_min"])

    @property
    def stop_dwell_min(self) -> float:
        return float(self.data["corridor_operations"]["station_dwell_min"])

    @property
    def terminal_dwell_min(self) -> float:
        return float(self.data["corridor_operations"]["terminal_dwell_min"])

    @property
    def max_overtake_hold_min(self) -> float:
        return float(self.data["corridor_operations"]["max_overtake_hold_min"])

    @property
    def overtake_speed_margin(self) -> float:
        return float(self.data["corridor_operations"]["overtake_speed_margin_kmph"])

    @property
    def train_precedence(self) -> dict[str, int]:
        return {k: int(v) for k, v in self.data["train_precedence"].items()}

    # ---- M6 -------------------------------------------------------------

    @property
    def kavach_equipped_pct(self) -> float:
        return float(self.data["protection_standards"]["kavach_equipped_at_pct"])

    @property
    def kavach_partial_pct(self) -> float:
        return float(self.data["protection_standards"]["kavach_partial_at_pct"])

    # ---- demand ---------------------------------------------------------

    @property
    def default_alighting(self) -> float:
        return float(self.data["demand_assumptions"]["default_alighting_per_train"])

    @property
    def special_multiplier(self) -> float:
        return float(self.data["demand_assumptions"]["special_train_multiplier"])

    @property
    def unload_duration_s(self) -> float:
        return float(self.data["demand_assumptions"]["unload_duration_s"])


# --------------------------------------------------------------------------
# parsing + validation
# --------------------------------------------------------------------------

def _num(section: dict, key: str, path: str, errors: list,
         *, lo: float | None = None, hi: float | None = None) -> None:
    if key not in section:
        errors.append(f"{path}.{key} is missing")
        return
    v = section[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.append(f"{path}.{key} must be a number (got {v!r})")
        return
    if lo is not None and v < lo:
        errors.append(f"{path}.{key} must be at least {lo} (got {v})")
    if hi is not None and v > hi:
        errors.append(f"{path}.{key} must be at most {hi} (got {v})")


SECTIONS = ("crowd_safety", "intervention_priority", "corridor_operations",
            "train_precedence", "protection_standards", "demand_assumptions")


def _v_crowd_safety(data, errors):
    cs = data["crowd_safety"]
    if not isinstance(cs, dict) or "density_bands" not in cs:
        errors.append("crowd_safety.density_bands is missing")
    else:
        b = cs["density_bands"]
        if not isinstance(b, dict):
            errors.append("crowd_safety.density_bands must be a mapping")
        else:
            keys = ["restricted_above", "constrained_above", "dangerous_above", "crush_above"]
            for k in keys:
                _num(b, k, "crowd_safety.density_bands", errors, lo=0.05, hi=50)
            if not errors:
                vals = [float(b[k]) for k in keys]
                if vals != sorted(vals) or len(set(vals)) != len(vals):
                    errors.append(
                        "crowd_safety.density_bands must increase strictly: "
                        f"restricted < constrained < dangerous < crush (got {vals})"
                    )
        _num(cs, "metered_holding_release_density", "crowd_safety", errors, lo=0.1, hi=20)
        _num(cs, "one_way_fob_egress_multiplier", "crowd_safety", errors, lo=1.0, hi=10)



def _v_intervention_priority(data, errors):
    ip = data["intervention_priority"]
    if not isinstance(ip, list):
        errors.append("intervention_priority must be a list")
    else:
        unknown = [x for x in ip if x not in OBJECTIVES]
        if unknown:
            errors.append(f"intervention_priority has unknown objective(s): {unknown}. "
                          f"Valid: {', '.join(OBJECTIVES)}")
        if len(set(ip)) != len(ip):
            errors.append("intervention_priority must not repeat an objective")
        missing = [o for o in OBJECTIVES if o not in ip]
        if missing:
            errors.append(f"intervention_priority must rank all four objectives; missing: {missing}")



def _v_corridor_operations(data, errors):
    co = data["corridor_operations"]
    if not isinstance(co, dict):
        errors.append("corridor_operations must be a mapping")
    else:
        _num(co, "minimum_headway_min", "corridor_operations", errors, lo=0.5, hi=60)
        _num(co, "station_dwell_min", "corridor_operations", errors, lo=0, hi=60)
        _num(co, "terminal_dwell_min", "corridor_operations", errors, lo=0, hi=120)
        _num(co, "max_overtake_hold_min", "corridor_operations", errors, lo=0, hi=180)
        _num(co, "overtake_speed_margin_kmph", "corridor_operations", errors, lo=0, hi=100)



def _v_train_precedence(data, errors):
    tp = data["train_precedence"]
    if not isinstance(tp, dict):
        errors.append("train_precedence must be a mapping of class: priority")
    else:
        unknown = [k for k in tp if k not in TRAIN_CLASSES]
        if unknown:
            errors.append(f"train_precedence has unknown class(es): {unknown}. "
                          f"Valid: {', '.join(TRAIN_CLASSES)}")
        missing = [k for k in TRAIN_CLASSES if k not in tp]
        if missing:
            errors.append(f"train_precedence must cover every class; missing: {missing}")
        for k, v in tp.items():
            if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 20):
                errors.append(f"train_precedence.{k} must be a whole number 1-20 (got {v!r})")



def _v_protection_standards(data, errors):
    ps = data["protection_standards"]
    if not isinstance(ps, dict):
        errors.append("protection_standards must be a mapping")
    else:
        _num(ps, "kavach_equipped_at_pct", "protection_standards", errors, lo=0, hi=100)
        _num(ps, "kavach_partial_at_pct", "protection_standards", errors, lo=0, hi=100)
        if ("kavach_equipped_at_pct" in ps and "kavach_partial_at_pct" in ps
                and isinstance(ps["kavach_equipped_at_pct"], (int, float))
                and isinstance(ps["kavach_partial_at_pct"], (int, float))
                and ps["kavach_partial_at_pct"] >= ps["kavach_equipped_at_pct"]):
            errors.append("protection_standards.kavach_partial_at_pct must be BELOW "
                          "kavach_equipped_at_pct (partial is the lower bar)")



def _v_demand_assumptions(data, errors):
    da = data["demand_assumptions"]
    if not isinstance(da, dict):
        errors.append("demand_assumptions must be a mapping")
    else:
        _num(da, "default_alighting_per_train", "demand_assumptions", errors, lo=1, hi=10000)
        _num(da, "special_train_multiplier", "demand_assumptions", errors, lo=0.1, hi=10)
        _num(da, "unload_duration_s", "demand_assumptions", errors, lo=10, hi=3600)


_VALIDATORS = {
    "crowd_safety": _v_crowd_safety,
    "intervention_priority": _v_intervention_priority,
    "corridor_operations": _v_corridor_operations,
    "train_precedence": _v_train_precedence,
    "protection_standards": _v_protection_standards,
    "demand_assumptions": _v_demand_assumptions,
}


def validate_sections(data: Any, sections) -> list[str]:
    """Check only the sections a single document owns.

    Returns ALL problems rather than raising on the first, so the editor can
    show every issue at once instead of one per save attempt.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["the document must be a YAML mapping (key: value at the top level)"]
    for sect in sections:
        if sect not in data:
            errors.append(f"section '{sect}' is missing")
    if errors:
        return errors
    extra = [k for k in data if k not in sections]
    if extra:
        errors.append(f"this document does not own section(s): {extra}. "
                      f"It covers: {', '.join(sections)}")
    for sect in sections:
        _VALIDATORS[sect](data, errors)
    return errors


def validate(data: Any) -> list[str]:
    """Check a fully composed rule-set (every section present)."""
    return validate_sections(data, SECTIONS)


MAX_NARRATIVE_CHARS = 60_000


def validate_narrative(raw: str) -> list[str]:
    """A written standard has no schema, but it still has to be a document."""
    if not (raw or "").strip():
        return ["the document is empty"]
    if len(raw) > MAX_NARRATIVE_CHARS:
        return [f"the document is too long ({len(raw):,} characters; "
                f"the limit is {MAX_NARRATIVE_CHARS:,})"]
    return []


def parse_document(key: str, raw: str) -> dict:
    """Parse + validate ONE policy document.

    Structured documents return their section data. Written standards have no
    machine-readable content, so they return nothing and are checked only for
    being a usable document.
    """
    from . import documents as docs
    doc = docs.get(key)
    if doc is None:
        raise PolicyError(f"unknown policy document '{key}'")
    if not doc.structured:
        errors = validate_narrative(raw)
        if errors:
            raise PolicyError("; ".join(errors))
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        raise PolicyError(f"YAML syntax error{where}: {problem}") from exc
    errors = validate_sections(data, doc.sections)
    if errors:
        raise PolicyError("; ".join(errors))
    return data


def compose(raws: dict) -> Policy:
    """Merge every document's active text into the rule-set the platform runs on.

    `raws` maps document key -> its YAML. Any document not supplied falls back
    to its shipped default, so the platform always has a complete rule-set even
    if one document has never been amended.
    """
    from . import documents as docs
    merged: dict = {}
    for d in docs.all_documents():
        if not d.structured:
            continue          # a written standard governs people, not the models
        raw = raws.get(d.key, d.default_yaml)
        merged.update(parse_document(d.key, raw))
    errors = validate(merged)
    if errors:
        raise PolicyError("; ".join(errors))
    return Policy(raw="", data=merged)


def parse(raw: str) -> Policy:
    """Parse + validate YAML text into a Policy. Raises PolicyError on failure."""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        raise PolicyError(f"YAML syntax error{where}: {problem}") from exc

    errors = validate(data)
    if errors:
        raise PolicyError("; ".join(errors))
    return Policy(raw=raw, data=data)


def default_policy() -> Policy:
    """The composed rule-set with every document at its shipped default."""
    return compose({})
