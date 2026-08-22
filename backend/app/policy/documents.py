"""
The policy library: the separate rule-sets the platform operates under.

One rulebook was the wrong shape. A railway does not amend crowd-safety
thresholds and train precedence in the same act — different people own them,
they change on different cycles, and a reader wants the history of ONE of them
without wading through edits to the others.

So each rule-set is its own document, with its own text, its own version chain
and its own author trail. The platform runs on all of them composed together:
`app/policy/context.py` merges the active version of every document into one
set of rules the simulators read.

Adding a document means adding an entry here — the store, the diff, the
preview and the change history are all generic over the registry.
"""
from __future__ import annotations

from dataclasses import dataclass


# Two kinds of policy live side by side, because a real rulebook contains both.
#
#   "yaml"     a structured rule-set. Parsed, validated field by field, and
#              composed into the rules the simulators actually run on, so a
#              change to one can be previewed as a measured consequence.
#
#   "markdown" / "text"
#              a written standard — a standing order, an escalation chain.
#              Versioned, diffed and attributed exactly like the structured
#              ones, but it governs what PEOPLE do, so there is no modelled
#              effect to preview. Saying so plainly is better than inventing
#              a number for it.
FORMATS = {"yaml": "yaml", "markdown": "md", "text": "txt"}


@dataclass(frozen=True)
class PolicyDocument:
    key: str            # url-safe id, and the storage namespace
    title: str
    summary: str        # one line, for the library listing
    department: str     # the team accountable for this document, ongoing
    sections: tuple     # top-level YAML keys this document owns (structured only)
    default_yaml: str   # the shipped text of the document
    format: str = "yaml"

    @property
    def extension(self) -> str:
        return FORMATS.get(self.format, "txt")

    @property
    def filename(self) -> str:
        return f"{self.key}.{self.extension}"

    @property
    def structured(self) -> bool:
        """Does this document feed the simulators?"""
        return self.format == "yaml"


CROWD_SAFETY = """\
# ═══════════════════════════════════════════════════════════════════════════
#  Crowd safety thresholds
#
#  Fruin Level-of-Service bands, in persons per square metre. These define
#  when a location is reported as restricted, dangerous, or a crush point.
#
#  crush_above is the consequential one: it is the line between "very crowded"
#  and "lethal". Lowering it does not change the crowd — it changes how many
#  locations the platform is obliged to report and act on.
# ═══════════════════════════════════════════════════════════════════════════

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
"""

INTERVENTION_PRIORITY = """\
# ═══════════════════════════════════════════════════════════════════════════
#  Intervention priority
#
#  The mitigation optimizer simulates every combination of the four crowd
#  controls and ranks them against this list, most important first.
#
#  This is the most consequential rule the platform holds. Put throughput above
#  peak_density and the optimizer will start recommending plans that move more
#  people at higher risk. That is a legitimate position to take — but it should
#  be taken deliberately, recorded, with a name against it.
#
#  Valid entries: crush_points, peak_density, throughput, measure_count
# ═══════════════════════════════════════════════════════════════════════════

intervention_priority:
  - crush_points
  - peak_density
  - throughput
  - measure_count
"""

CORRIDOR_OPERATIONS = """\
# ═══════════════════════════════════════════════════════════════════════════
#  Corridor operating rules
#
#  How trains are spaced, how long they hold, and when the dispatcher may
#  stand one aside to let another past.
# ═══════════════════════════════════════════════════════════════════════════

corridor_operations:
  # Minimum separation between two trains on the same section.
  minimum_headway_min: 5.0

  # How long a stopping train occupies a platform.
  station_dwell_min: 2.0
  terminal_dwell_min: 4.0

  # The dispatcher may hold a train at a loop for up to this long to let
  # another overtake. Beyond this the hold costs more than it saves.
  max_overtake_hold_min: 12.0

  # Within a precedence class, a waiting train is only held for an approaching
  # one if that train is at least this much faster (km/h).
  overtake_speed_margin_kmph: 5
"""

TRAIN_PRECEDENCE = """\
# ═══════════════════════════════════════════════════════════════════════════
#  Train precedence
#
#  Which class of train is protected when the corridor is congested. Higher
#  wins; speed breaks ties within a class.
#
#  This is an equity decision as much as an operational one. PASSENGER at 2
#  means commuter services absorb delay so premium services do not. Raising it
#  above the expresses reverses that, and the corridor pays for it — preview
#  the change and the cost is measured before anyone commits to it.
# ═══════════════════════════════════════════════════════════════════════════

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
"""

PROTECTION_STANDARDS = """\
# ═══════════════════════════════════════════════════════════════════════════
#  Protection standards
#
#  What share of a route must carry Kavach before it counts as equipped.
#  Raising the bar reclassifies corridors and lowers reported national
#  coverage without a metre of track changing.
# ═══════════════════════════════════════════════════════════════════════════

protection_standards:
  kavach_equipped_at_pct: 75
  kavach_partial_at_pct: 25
"""

DEMAND_ASSUMPTIONS = """\
# ═══════════════════════════════════════════════════════════════════════════
#  Demand assumptions
#
#  The live arrivals feed returns trains, never passenger counts. These are the
#  planning assumptions used to turn an arrival into a crowd. Replace them with
#  PRS/UTS or gate counts once those are available.
# ═══════════════════════════════════════════════════════════════════════════

demand_assumptions:
  default_alighting_per_train: 1200
  special_train_multiplier: 2.2
  unload_duration_s: 180
"""


SURGE_STANDING_ORDERS = """\
# Crowd Control Standing Orders

**Reference** RS-SO-004 · **Owner** Station Operations & Safety

These orders govern what staff do when the platform reports a dangerous or
crush-level density. The thresholds themselves live in the *Crowd safety
thresholds* policy; this document covers the human response to them.

## 1. On a DANGEROUS reading

1. The Station Manager is informed immediately. No exceptions and no delegation.
2. Announcements switch to holding language. Do not announce a platform change
   for any train serving the affected foot-over-bridge.
3. Two staff are posted at the head of the affected stair to meter entry by
   hand until the control measures take effect.

## 2. On a CRUSH reading

1. Entry to the affected span stops. Not slows — stops.
2. RPF and the duty medical officer are called at the same time, not in
   sequence. Waiting to see whether it clears has killed people.
3. The concourse is opened as holding space before the platform is released.
   Passengers are held where there is room, never where there is not.

## 3. Recording

Every activation of these orders is logged with the time the reading was seen,
the time staff were on station, and the time the density returned below the
dangerous band. That record is what tells us whether the thresholds are set in
the right place — which is why it is not optional.

## 4. Review

These orders are reviewed after any activation, and in any case every six
months. A review that changes nothing is still recorded, so silence is never
mistaken for absence of scrutiny.
"""

ESCALATION_PROTOCOL = """\
INCIDENT ESCALATION PROTOCOL
Reference RS-EP-002 | Owner Operations Control

WHO IS CALLED, AND WHEN. Times are from the moment the platform raises the
condition, not from the moment somebody notices it.

  CONDITION                          INFORM                        WITHIN
  ---------------------------------------------------------------------------
  Density at the dangerous band      Station Manager               immediately
  Density at the crush band          Station Manager, RPF,         immediately
                                     duty medical officer
  Corridor delay above 60 min        Divisional Control            10 minutes
  Corridor delay above 180 min       Divisional Control,           immediately
                                     Zonal HQ
  Protection gap on a route          Signalling & Telecom,         same day
  carrying above 200 trains/day      Zonal Safety

ESCALATION IS NOT A REQUEST FOR PERMISSION. Staff act first under the standing
orders and inform in parallel. Nobody waits for an answer before opening a
gate or stopping entry to a span.

IF YOU CANNOT REACH THE NAMED PERSON, escalate one level up rather than
retrying. An unanswered phone is an escalation trigger, not a reason to pause.

STAND-DOWN is declared by the same person who was informed, and is recorded
with a time and a reason. A condition that simply stops being mentioned has
not been stood down.
"""


BUILTIN: tuple[PolicyDocument, ...] = (
    PolicyDocument(
        key="crowd-safety",
        title="Crowd safety thresholds",
        summary="The density at which a location is called restricted, dangerous or a crush point.",
        department="Station Operations & Safety",
        sections=("crowd_safety",),
        default_yaml=CROWD_SAFETY,
    ),
    PolicyDocument(
        key="intervention-priority",
        title="Intervention priority",
        summary="What the mitigation optimizer optimises for, in order.",
        department="Station Operations & Safety",
        sections=("intervention_priority",),
        default_yaml=INTERVENTION_PRIORITY,
    ),
    PolicyDocument(
        key="corridor-operations",
        title="Corridor operating rules",
        summary="Headway, dwell, and how long a train may be held for an overtake.",
        department="Operations Control",
        sections=("corridor_operations",),
        default_yaml=CORRIDOR_OPERATIONS,
    ),
    PolicyDocument(
        key="train-precedence",
        title="Train precedence",
        summary="Which class of train is protected when the corridor is congested.",
        department="Operations Control",
        sections=("train_precedence",),
        default_yaml=TRAIN_PRECEDENCE,
    ),
    PolicyDocument(
        key="protection-standards",
        title="Protection standards",
        summary="The coverage a route needs before it counts as Kavach equipped.",
        department="Signalling & Telecom",
        sections=("protection_standards",),
        default_yaml=PROTECTION_STANDARDS,
    ),
    PolicyDocument(
        key="demand-assumptions",
        title="Demand assumptions",
        summary="How an arriving train is turned into a crowd, where no count exists.",
        department="Planning",
        sections=("demand_assumptions",),
        default_yaml=DEMAND_ASSUMPTIONS,
    ),
    PolicyDocument(
        key="crowd-control-standing-orders",
        title="Crowd control standing orders",
        summary="What staff do when a dangerous or crush reading is raised.",
        department="Station Operations & Safety",
        sections=(),
        default_yaml=SURGE_STANDING_ORDERS,
        format="markdown",
    ),
    PolicyDocument(
        key="incident-escalation",
        title="Incident escalation protocol",
        summary="Who is informed, and how quickly, for each condition.",
        department="Operations Control",
        sections=(),
        default_yaml=ESCALATION_PROTOCOL,
        format="text",
    ),
)

# Documents added through the UI. They are written standards, never rule-sets:
# every structured rule is read by a named accessor wired into a specific
# model, so a rule-set invented at runtime would have nothing reading it. It
# would look like policy and change nothing, which is worse than not offering
# it. Prose standards, on the other hand, are exactly what an operations team
# adds week to week.
_ADDED: dict[str, PolicyDocument] = {}

ADDABLE_FORMATS = ("markdown", "text")


def register(doc: PolicyDocument) -> None:
    _ADDED[doc.key] = doc


def all_documents() -> tuple[PolicyDocument, ...]:
    return BUILTIN + tuple(_ADDED.values())


def is_builtin(key: str) -> bool:
    return any(d.key == key for d in BUILTIN)


def get(key: str) -> PolicyDocument | None:
    for d in all_documents():
        if d.key == key:
            return d
    return None


def slugify(title: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return s[:60]


def catalogue() -> list[dict]:
    """Listing shape for the policy library, without any document text."""
    return [
        {"key": d.key, "title": d.title, "summary": d.summary,
         "department": d.department, "sections": list(d.sections),
         "format": d.format, "filename": d.filename,
         "structured": d.structured, "builtin": is_builtin(d.key)}
        for d in all_documents()
    ]
