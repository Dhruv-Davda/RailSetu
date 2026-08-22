/*
 * Unified diff, rendered the way a code host renders one: split line-number
 * gutters for the old and new file, a +/-/space marker column, and the row
 * tinted by what happened to it.
 *
 * Used in two places for the same reason — a rule change should look the same
 * whether you are about to make it (preview) or reading it back a week later
 * (history). Divergence between "what I'm about to do" and "what was done" is
 * exactly the thing a change register exists to prevent.
 */

const MARK = { add: '+', del: '-', context: ' ' }

export default function PolicyDiff({ hunks, stats, empty = 'No changes.' }) {
  if (!hunks?.length) {
    return <div className="pd-empty">{empty}</div>
  }
  return (
    <div className="pd">
      {stats && (
        <div className="pd-stats">
          <span className="pd-add">+{stats.added}</span>
          <span className="pd-del">−{stats.removed}</span>
          <span className="pd-bar">
            {/* proportional add/remove bar, as on a commit page */}
            {Array.from({ length: 5 }).map((_, i) => {
              const total = Math.max(1, stats.added + stats.removed)
              const adds = Math.round((stats.added / total) * 5)
              return <i key={i} className={i < adds ? 'a' : 'd'} />
            })}
          </span>
        </div>
      )}
      <div className="pd-file">
        {hunks.map((h, hi) => (
          <div key={hi}>
            <div className="pd-hunk">
              @@ -{h.old_start},{h.old_lines} +{h.new_start},{h.new_lines} @@
            </div>
            {h.lines.map((l, li) => (
              <div key={li} className={`pd-row ${l.type}`}>
                <span className="pd-ln">{l.old ?? ''}</span>
                <span className="pd-ln">{l.new ?? ''}</span>
                <span className="pd-mark">{MARK[l.type]}</span>
                <span className="pd-text">{l.text || ' '}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * The same change stated in the document's own vocabulary.
 *
 * A line diff tells you a character moved. This tells a duty officer which
 * rule was amended and from what to what — which is the thing they actually
 * need in order to agree or object.
 */
export function ChangeList({ changes, title = 'Rules amended' }) {
  if (!changes?.length) return null
  return (
    <div className="pc">
      <div className="pc-title">{title}</div>
      {changes.map((c, i) => (
        <div className={`pc-row ${c.kind}`} key={i}>
          <span className="pc-kind">{c.kind}</span>
          <span className="pc-path">{c.path}</span>
          {c.kind === 'changed' ? (
            <span className="pc-move">
              <b className="was">{String(c.before)}</b>
              <span className="arr">→</span>
              <b className="now">{String(c.after)}</b>
            </span>
          ) : (
            <span className="pc-move">
              <b className={c.kind === 'added' ? 'now' : 'was'}>
                {String(c.kind === 'added' ? c.after : c.before)}
              </b>
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
