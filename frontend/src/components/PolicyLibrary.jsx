/*
 * The policy library.
 *
 * Cards rather than full-width rows. Each document carries a title, a summary,
 * a filename, a department and a version history — that is a block of related
 * facts, and stretching it across a wide screen pushed the metadata so far
 * from the title that the two stopped reading as one thing, and left a dead
 * band down the right of the page.
 *
 * A card keeps each document's facts together, and the grid reflows to fill
 * whatever width it is given instead of leaving it empty.
 */

const FORMAT_LABEL = { yaml: 'YAML', markdown: 'MD', text: 'TXT' }

function ago(iso) {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 2592000) return `${Math.floor(s / 86400)} d ago`
  return new Date(iso).toLocaleDateString()
}

function initials(name = '') {
  const p = name.trim().split(/\s+/).filter(Boolean)
  if (!p.length) return '?'
  return ((p[0][0] || '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase()
}

export default function PolicyLibrary({ library, openKey, onOpen, onNew }) {
  if (!library) return <div className="pd-empty">loading the policy library…</div>

  const structured = library.documents.filter((d) => d.structured)
  const written = library.documents.filter((d) => !d.structured)
  const amended = library.documents.filter((d) => (d.versions || 1) > 1).length

  return (
    <div className="lib">
      <header className="lib-head">
        <div>
          <h1>Operating policy</h1>
          <p>
            The rules the platform runs on. Each document is amended on its own and
            keeps its own history; the platform operates on all of them together.
          </p>
        </div>
        <div className="lib-tally">
          <div><b>{library.count}</b><span>documents</span></div>
          <div><b>{amended}</b><span>amended</span></div>
          <button className="gh-btn primary lib-new" onClick={onNew}>+ Add policy</button>
        </div>
      </header>

      <Group
        title="Rule-sets"
        note="Read directly by the crowd, corridor and protection models. A change here has a measurable effect, so it can be previewed before it takes force."
        docs={structured} openKey={openKey} onOpen={onOpen}
      />
      <Group
        title="Written standards"
        note="Procedure, in prose. These govern what people do rather than what the models compute, so there is no modelled effect to preview — they are versioned and attributed just the same."
        docs={written} openKey={openKey} onOpen={onOpen}
      />
    </div>
  )
}

function Group({ title, note, docs, openKey, onOpen }) {
  if (!docs.length) return null
  return (
    <section className="lib-group">
      <div className="lib-gh">
        <span className="lib-gt">{title}</span>
        <span className="lib-gc">{docs.length}</span>
        <span className="lib-grule" />
      </div>
      <p className="lib-gn">{note}</p>
      <div className="lib-grid">
        {docs.map((d) => {
          const cur = d.current
          const amended = (d.versions || 1) > 1
          return (
            <button
              key={d.key}
              className={`card ${openKey === d.key ? 'open' : ''}`}
              onClick={() => onOpen(d.key)}
            >
              <div className="card-top">
                <span className={`lib-fmt ${d.format}`}>{FORMAT_LABEL[d.format] || d.format}</span>
                <span className="card-file">{d.filename}</span>
                <span className="card-v">v{cur ? cur.seq : 1}</span>
              </div>

              <h3 className="card-title">{d.title}</h3>
              <p className="card-sum">{d.summary}</p>

              <div className="card-foot">
                <span className="card-dept">{d.department}</span>
                {amended && cur ? (
                  <span className="card-last">
                    <span className="card-av">{initials(cur.author_name)}</span>
                    {cur.author_name} · {ago(cur.created_at)}
                  </span>
                ) : (
                  <span className="card-last quiet">never amended</span>
                )}
              </div>

              {openKey === d.key && <span className="card-open">open</span>}
            </button>
          )
        })}
      </div>
    </section>
  )
}
