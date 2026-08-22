/*
 * What a draft rule change would actually do.
 *
 * These are not illustrations. Each figure is the output of the same crowd,
 * corridor and protection models the rest of the platform runs on, executed
 * once under the policy in force and once under the draft. That is the whole
 * argument for previewing a rule before activating it: you get the consequence
 * measured, not asserted.
 */

// How to phrase each metric, and which direction is bad. `worse` is used only
// to colour the delta — a change is never described as good or bad on its own,
// because "fewer crush points because we raised the threshold" is not a safety
// improvement and must not be coloured like one.
const FIELDS = {
  crowd: {
    label: 'Station crowding',
    sub: 'peak-hour surge scenario',
    rows: {
      peak_density: { name: 'Peak density', unit: ' p/m²', worseWhen: 'up' },
      peak_los: { name: 'Peak level of service', worseWhen: null },
      crush_count: { name: 'Crush points', worseWhen: 'up' },
      danger_count: { name: 'Danger locations', worseWhen: 'up' },
      cleared: { name: 'People cleared', worseWhen: 'down' },
    },
  },
  corridor: {
    label: 'Corridor punctuality',
    sub: 'disruption scenario, after rescheduling',
    rows: {
      delay_before_min: { name: 'Delay, no action', unit: ' min', worseWhen: 'up' },
      delay_after_min: { name: 'Delay, rescheduled', unit: ' min', worseWhen: 'up' },
      saved_min: { name: 'Delay recovered', unit: ' min', worseWhen: 'down' },
      affected: { name: 'Trains delayed', worseWhen: 'up' },
      moves: { name: 'Hold-and-overtake moves', worseWhen: null },
    },
  },
  protection: {
    label: 'Protection coverage',
    sub: 'national corridor audit',
    rows: {
      weighted_coverage_pct: { name: 'Traffic-weighted coverage', unit: '%', worseWhen: 'down' },
      equipped: { name: 'Corridors equipped', worseWhen: 'down' },
      partial: { name: 'Corridors partial', worseWhen: null },
      none: { name: 'Corridors unprotected', worseWhen: 'up' },
      risk_share_pct: { name: 'Risk on unequipped routes', unit: '%', worseWhen: 'up' },
    },
  },
}

function fmt(v, unit = '') {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return `${Math.round(v * 100) / 100}${unit}`
  return String(v)
}

function Row({ name, unit, worseWhen, d }) {
  if (!d) return null
  const moved = d.changed
  let tone = ''
  if (moved && typeof d.delta === 'number' && worseWhen) {
    const isWorse = worseWhen === 'up' ? d.delta > 0 : d.delta < 0
    tone = isWorse ? 'worse' : 'better'
  } else if (moved) {
    tone = 'moved'
  }
  return (
    <div className={`pi-row ${moved ? 'moved' : ''}`}>
      <div className="pi-name">{name}</div>
      <div className="pi-before">{fmt(d.before, unit)}</div>
      <div className="pi-arrow">{moved ? '→' : ''}</div>
      <div className={`pi-after ${tone}`}>{moved ? fmt(d.after, unit) : ''}</div>
      <div className={`pi-delta ${tone}`}>
        {moved && typeof d.delta === 'number' && d.delta !== 0
          ? `${d.delta > 0 ? '+' : ''}${Math.round(d.delta * 100) / 100}${unit}`
          : ''}
      </div>
    </div>
  )
}

export default function PolicyImpact({ preview }) {
  if (!preview?.valid) return null
  const { deltas = {}, before = {}, after = {}, ran_optimizer: ranOpt } = preview

  const anyMoved = Object.values(deltas).some(
    (grp) => grp && Object.values(grp).some((f) => f?.changed),
  )

  return (
    <div className="pi">
      <div className="pi-head">
        <div>
          <div className="pi-h1">Projected effect</div>
          <div className="pi-h2">
            The crowd, corridor and protection models run twice — once under the policy
            in force, once under this draft. Nothing is activated.
          </div>
        </div>
      </div>

      {!anyMoved && (
        <div className="pi-none">
          These edits change no modelled outcome. That may be correct — comments,
          formatting, or a rule this scenario does not exercise.
        </div>
      )}

      {Object.entries(FIELDS).map(([key, spec]) => {
        const grp = deltas[key]
        if (!grp) return null
        const scenario = (after[key] || before[key] || {}).scenario
        return (
          <div className="pi-group" key={key}>
            <div className="pi-gh">
              <span className="pi-gl">{spec.label}</span>
              <span className="pi-gs">{scenario || spec.sub}</span>
            </div>
            <div className="pi-cols">
              <span />
              <span>in force</span>
              <span />
              <span>draft</span>
              <span>change</span>
            </div>
            {Object.entries(spec.rows).map(([f, meta]) => (
              <Row key={f} name={meta.name} unit={meta.unit || ''}
                worseWhen={meta.worseWhen} d={grp[f]} />
            ))}
          </div>
        )
      })}

      {deltas.recommendation && (
        <div className="pi-group">
          <div className="pi-gh">
            <span className="pi-gl">Recommended intervention</span>
            <span className="pi-gs">what the optimizer would now advise</span>
          </div>
          <div className={`pi-rec ${deltas.recommendation.changed ? 'changed' : ''}`}>
            <div><span className="pi-reclbl">in force</span>
              {(deltas.recommendation.before || ['—']).join(' + ')}</div>
            <div><span className="pi-reclbl">draft</span>
              {(deltas.recommendation.after || ['—']).join(' + ')}</div>
          </div>
          {deltas.recommendation.changed && (
            <div className="pi-warn">
              This change makes the platform advise a different course of action.
            </div>
          )}
        </div>
      )}

      {!ranOpt && (
        <div className="pi-note">
          The mitigation optimizer was not re-run — this draft does not alter
          intervention priority, so its recommendation is unaffected.
        </div>
      )}
    </div>
  )
}
