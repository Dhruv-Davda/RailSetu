/*
 * The policy register.
 *
 * You land in the library, because the first question is always "which rule".
 * Opening a document reveals the three things you can do with it — read it,
 * see what a change would do, read what has already been done — and those tabs
 * stay hidden until then, so the surface never offers an action without a
 * subject.
 *
 * Three states, and the boundary between them is the whole point:
 *
 *   Edit      a draft, held in this browser only. Changes nothing.
 *   Preview   the draft run through the real models. Still changes nothing.
 *   Activate  the draft becomes the rules the platform operates under, and is
 *             recorded permanently with who changed it and why.
 *
 * Drafts live in localStorage, one per document, precisely so that "saved" can
 * never be confused with "in force". A saved draft is a private note; only
 * activation is an act.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import PolicyEditor from '../components/PolicyEditor.jsx'
import PolicyDiff, { ChangeList } from '../components/PolicyDiff.jsx'
import PolicyImpact from '../components/PolicyImpact.jsx'
import PolicyLibrary from '../components/PolicyLibrary.jsx'
import { captureLocation, formatLocation, mapLink } from '../geolocation.js'
import {
  getPolicyLibrary, getPolicyDoc, getPolicyDocDefault, validatePolicyDoc,
  previewPolicyDoc, activatePolicyDoc, getPolicyDocHistory, getPolicyDocVersion,
  rollbackPolicyDoc, revertPolicyChange, createPolicyDoc,
} from '../api.js'

const draftKey = (key) => `railsetu.policy.draft.${key}`

const load = (k, fallback = null) => {
  try { const v = localStorage.getItem(k); return v == null ? fallback : v } catch { return fallback }
}
const save = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }
const drop = (k) => { try { localStorage.removeItem(k) } catch { /* ignore */ } }

function initials(name = '') {
  const p = name.trim().split(/\s+/).filter(Boolean)
  if (!p.length) return '??'
  return ((p[0][0] || '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase()
}

function ago(iso) {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 2592000) return `${Math.floor(s / 86400)} d ago`
  return new Date(iso).toLocaleDateString()
}

/* Errors from the API carry a transport prefix that means nothing to the
   person reading them. Keep the sentence, drop the plumbing. */
function humanise(message = '') {
  return message.replace(/^API \d+ on \S+\s*—\s*/, '') || message
}

export default function Policy({ account }) {
  const [library, setLibrary] = useState(null)
  const [openKey, setOpenKey] = useState(null)
  const [doc, setDoc] = useState(null)          // { document, text, version }
  const [draft, setDraft] = useState(null)
  const [tab, setTab] = useState('library')
  const [validity, setValidity] = useState({ valid: true, errors: [] })
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])
  const [openVersion, setOpenVersion] = useState(null)
  const [versionDetail, setVersionDetail] = useState(null)
  const [showPush, setShowPush] = useState(false)
  const [revertTo, setRevertTo] = useState(null)   // { version, mode }
  const [conflict, setConflict] = useState(null)
  const [showNew, setShowNew] = useState(false)
  const [savedAt, setSavedAt] = useState(null)
  const validateTimer = useRef(0)

  useEffect(() => {
    getPolicyLibrary().then(setLibrary).catch((e) => setError(humanise(e.message)))
  }, [])

  // Opening a document loads its text and history, and seeds the editor from
  // any draft held for THAT document.
  const openDocument = useCallback(async (key) => {
    setError(null); setPreview(null); setSavedAt(null)
    setOpenVersion(null); setVersionDetail(null)
    setBusy('open')
    try {
      const [d, h] = await Promise.all([getPolicyDoc(key), getPolicyDocHistory(key)])
      setOpenKey(key)
      setDoc(d)
      setDraft(load(draftKey(key)) ?? d.text)
      setHistory(h.versions || [])
      setValidity({ valid: true, errors: [] })
      setTab('document')
    } catch (e) { setError(humanise(e.message)) } finally { setBusy(null) }
  }, [])

  const reloadDocument = useCallback(async (key) => {
    const [d, h, l] = await Promise.all([
      getPolicyDoc(key), getPolicyDocHistory(key), getPolicyLibrary(),
    ])
    setDoc(d); setHistory(h.versions || []); setLibrary(l)
    return d
  }, [])

  // Live validation, debounced — the editor should tell you a rule is bad
  // while you type, not only when you try to activate it.
  useEffect(() => {
    if (draft == null || !openKey) return
    clearTimeout(validateTimer.current)
    validateTimer.current = setTimeout(() => {
      validatePolicyDoc(openKey, draft).then(setValidity).catch(() => {})
    }, 350)
    return () => clearTimeout(validateTimer.current)
  }, [draft, openKey])

  const meta = doc?.document
  const dirty = doc && draft != null && draft !== doc.text
  const hasDraft = openKey ? load(draftKey(openKey)) != null : false

  function onSaveDraft() { save(draftKey(openKey), draft); setSavedAt(new Date()) }

  function onDiscard() {
    drop(draftKey(openKey)); setDraft(doc.text); setPreview(null)
    setSavedAt(null); setTab('document')
  }

  async function onResetToDefault() {
    try { setDraft(await getPolicyDocDefault(openKey)); setPreview(null) }
    catch (e) { setError(humanise(e.message)) }
  }

  async function onPreview() {
    setBusy('preview'); setError(null)
    try { setPreview(await previewPolicyDoc(openKey, draft)); setTab('preview') }
    catch (e) { setError(humanise(e.message)) } finally { setBusy(null) }
  }

  async function onActivate(form) {
    setBusy('push'); setError(null)
    try {
      // No author fields: the server attributes the change to the signed-in
      // account, so a version can never be recorded against someone else.
      await activatePolicyDoc(openKey, { text: draft, ...form })
      drop(draftKey(openKey))
      setShowPush(false); setPreview(null); setSavedAt(null)
      const d = await reloadDocument(openKey)
      setDraft(d.text)
      setTab('history')
    } catch (e) { setError(humanise(e.message)) } finally { setBusy(null) }
  }

  async function onCreate(form) {
    setBusy('create'); setError(null)
    try {
      const r = await createPolicyDoc(form)
      setShowNew(false)
      setLibrary(await getPolicyLibrary())
      await openDocument(r.key)          // land the author in what they just made
    } catch (e) { setError(humanise(e.message)) } finally { setBusy(null) }
  }

  async function onOpenVersion(id) {
    if (openVersion === id) { setOpenVersion(null); setVersionDetail(null); return }
    setOpenVersion(id); setVersionDetail(null)
    try { setVersionDetail(await getPolicyDocVersion(openKey, id)) }
    catch (e) { setError(humanise(e.message)) }
  }

  // Two different acts, deliberately not merged into one button:
  //   revert  — back out only what this version did (git revert)
  //   restore — make the document exactly as it was then (git reset)
  async function onUndo(location) {
    const { version, mode } = revertTo
    setBusy('rollback'); setError(null); setConflict(null)
    try {
      const body = { version_id: version.id, location }
      if (mode === 'revert') await revertPolicyChange(openKey, body)
      else await rollbackPolicyDoc(openKey, body)
      drop(draftKey(openKey))
      const d = await reloadDocument(openKey)
      setDraft(d.text); setRevertTo(null)
      setOpenVersion(null); setVersionDetail(null)
    } catch (e) {
      if (e.status === 409 && e.detail?.conflicts) {
        setConflict({ ...e.detail, version })
        setRevertTo(null)
      } else setError(humanise(e.message))
    } finally { setBusy(null) }
  }

  const store = library?.store || {}
  const TABS = [
    ['library', 'Policies', library ? String(library.count) : null],
    ...(openKey ? [
      ['document', 'Document', dirty ? '●' : null],
      ['preview', 'Preview changes', preview ? '✓' : null],
      ['history', 'Change history', String(history.length)],
    ] : []),
  ]

  return (
    <div className="view pol">
      <div className="pol-top">
        <div className="pol-repo">
          <span className="pol-book">▤</span>
          <button className="pol-crumb" onClick={() => setTab('library')}>RailSetu</button>
          <span className="pol-slash">/</span>
          {openKey && meta ? (
            <>
              <button className="pol-crumb" onClick={() => setTab('library')}>policy</button>
              <span className="pol-slash">/</span>
              <b>{meta.title}</b>
              {doc?.version && <span className="pol-vchip">v{doc.version.seq}</span>}
            </>
          ) : <b>policy library</b>}
        </div>
        <div className="pol-meta">
          <span className={`pol-store ${store.status === 'ok' ? 'ok' : 'bad'}`}>
            {store.store === 'S3PolicyStore'
              ? `S3 · ${store.bucket}/${store.prefix}`
              : 'local register'}
          </span>
          <span className="pol-count">{library?.count ?? '—'} documents</span>
        </div>
      </div>

      <div className="pol-tabs">
        {TABS.map(([k, label, badge]) => (
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
            {label}{badge ? <span className="pol-badge">{badge}</span> : null}
          </button>
        ))}
        <div className="spacer" />
        {busy === 'open' && <span className="loading">opening…</span>}
        {error && <span className="error-chip" title={error}>⚠ {error}</span>}
      </div>

      {tab === 'library' && (
        <div className="pol-body scroll">
          <PolicyLibrary library={library} openKey={openKey} onOpen={openDocument}
            onNew={() => setShowNew(true)} />
        </div>
      )}

      {tab === 'document' && doc && (
        <div className="pol-body">
          <div className="pol-filebar">
            <span className="pol-file">{meta.filename}</span>
            <span className={`lib-fmt ${meta.format}`}>{meta.format}</span>
            <span className="pol-fmeta">
              {dirty ? 'modified' : 'matches the version in force'}
              {hasDraft && <span className="pol-draftdot"> · draft saved{savedAt ? ` ${savedAt.toLocaleTimeString()}` : ''}</span>}
            </span>
            <div className="spacer" />
            <button className="gh-btn sm" onClick={onResetToDefault}>Reset to shipped text</button>
          </div>

          <PolicyEditor value={draft} onChange={setDraft}
            valid={validity.valid} errors={validity.errors} />

          <div className="pol-actions">
            <div className="pol-hint">
              {meta.structured
                ? <>Edits are local until you activate. <b>Preview</b> measures what they
                  would do to the crowd, corridor and protection models; only <b>Activate</b>{' '}
                  changes how the platform operates.</>
                : <>A written standard. It is versioned and attributed like any other
                  policy, but it governs what people do, so there is no modelled effect
                  to measure.</>}
            </div>
            <div className="spacer" />
            {dirty && <button className="gh-btn" onClick={onDiscard}>Discard changes</button>}
            <button className="gh-btn" onClick={onSaveDraft} disabled={!dirty}>Save draft</button>
            <button className="gh-btn" onClick={onPreview} disabled={!dirty || busy === 'preview'}>
              {busy === 'preview' ? 'Running models…' : 'Preview changes'}
            </button>
            <button className="gh-btn primary" disabled={!dirty || !validity.valid}
              onClick={() => setShowPush(true)}>Activate…</button>
          </div>
        </div>
      )}

      {tab === 'preview' && (
        <div className="pol-body scroll">
          {!preview ? (
            <div className="pd-empty">
              Nothing previewed yet. Edit the document, then choose <b>Preview changes</b>.
            </div>
          ) : !preview.valid ? (
            <div className="pol-invalid">
              <b>This draft cannot be activated.</b>
              <ul>{(preview.errors || []).map((e, i) => <li key={i}>{e}</li>)}</ul>
            </div>
          ) : (
            <>
              {preview.narrative ? (
                <div className="pi">
                  <div className="pi-head">
                    <div className="pi-h1">No modelled effect</div>
                    <div className="pi-h2">
                      This is a written standard — it governs what staff do, not what the
                      models compute. The change is recorded and attributed like any
                      other, but there is no simulated consequence to report, and
                      inventing one would be worse than saying so.
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <ChangeList changes={preview.changes} />
                  <PolicyImpact preview={preview} />
                </>
              )}
              <div className="pol-difftitle">Document diff</div>
              <PolicyDiff hunks={preview.hunks} stats={preview.stats} />
              <div className="pol-actions sticky">
                <div className="spacer" />
                <button className="gh-btn" onClick={() => setTab('document')}>Back to document</button>
                <button className="gh-btn primary" disabled={!validity.valid}
                  onClick={() => setShowPush(true)}>Activate…</button>
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'history' && (
        <div className="pol-body scroll">
          <div className="gh-commits">
            {history.map((h) => (
              <div className={`gh-commit ${openVersion === h.id ? 'open' : ''}`} key={h.id}>
                <div className="gh-crow" onClick={() => onOpenVersion(h.id)}>
                  <span className="gh-av">{initials(h.author_name)}</span>
                  <div className="gh-cmain">
                    <div className="gh-ctitle">
                      {h.title}
                      {h.reverts && <span className="gh-tag rb">revert</span>}
                      {h.rollback_of && <span className="gh-tag rs">restore</span>}
                      {h.seq === doc?.version?.seq && <span className="gh-tag now">in force</span>}
                    </div>
                    <div className="gh-cmeta">
                      <b>{h.author_name}</b>
                      <span className="gh-mail">{h.author_email}</span>
                      committed {ago(h.created_at)}
                    </div>
                  </div>
                  <div className="gh-cright">
                    {h.diff_stats?.added != null && (
                      <span className="gh-stat">
                        <span className="pd-add">+{h.diff_stats.added}</span>
                        <span className="pd-del">−{h.diff_stats.removed}</span>
                      </span>
                    )}
                    <span className="gh-sha">{h.id.slice(0, 7)}</span>
                    <span className="gh-seq">v{h.seq}</span>
                  </div>
                </div>

                {openVersion === h.id && (
                  <div className="gh-cbody">
                    {h.description && <p className="gh-desc">{h.description}</p>}
                    {!versionDetail ? <div className="pd-empty">loading diff…</div> : (
                      <>
                        <ChangeList changes={versionDetail.changes} />
                        <LocationRecord location={h.location} />
                        <ImpactRecord impact={h.impact} />
                        <PolicyDiff hunks={versionDetail.hunks} stats={h.diff_stats}
                          empty="This is the initial text — there is nothing before it to compare against." />
                        <div className="gh-cactions">
                          <button className="gh-btn" onClick={() => { setDraft(versionDetail.text); setTab('document') }}>
                            Open in editor
                          </button>
                          {h.parent_id && (
                            <button className="gh-btn danger" disabled={busy === 'rollback'}
                              title="Undo only what this change did, keeping every later change"
                              onClick={() => setRevertTo({ version: h, mode: 'revert' })}>
                              Revert this change
                            </button>
                          )}
                          {h.seq !== doc?.version?.seq && (
                            <button className="gh-btn" disabled={busy === 'rollback'}
                              title="Make the document exactly as it was at this version"
                              onClick={() => setRevertTo({ version: h, mode: 'restore' })}>
                              Restore this version
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {revertTo && (
        <UndoModal version={revertTo.version} mode={revertTo.mode} account={account}
          title={meta?.title} busy={busy === 'rollback'}
          onCancel={() => setRevertTo(null)} onSubmit={onUndo} />
      )}
      {showNew && (
        <NewPolicyModal account={account} busy={busy === 'create'}
          onCancel={() => setShowNew(false)} onSubmit={onCreate} />
      )}
      {conflict && (
        <ConflictModal conflict={conflict} title={meta?.title}
          onCancel={() => setConflict(null)}
          onRestore={() => { setConflict(null); setRevertTo({ version: conflict.version, mode: 'restore' }) }} />
      )}
      {showPush && (
        <PushModal stats={preview?.stats} changes={preview?.changes}
          previewed={!!preview?.valid} account={account} docTitle={meta?.title}
          busy={busy === 'push'} onCancel={() => setShowPush(false)} onSubmit={onActivate} />
      )}
    </div>
  )
}

/* Where the change was made from, as recorded at the time. */
function LocationRecord({ location }) {
  if (!location) return null
  const ip = location.client_ip
  return (
    <div className="gh-impact">
      <div className="gh-impact-h">Where this change was made</div>
      {location.available ? (
        <>
          <div className="gh-impact-row">
            <span className="gh-ig">position</span>
            <span className="gh-ik">coordinates</span>
            <span className="gh-iv">
              {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
              <a className="geo-map" href={mapLink(location)} target="_blank"
                rel="noreferrer noopener">map</a>
            </span>
          </div>
          <div className="gh-impact-row">
            <span className="gh-ig">accuracy</span>
            <span className="gh-ik">reported by the device</span>
            <span className="gh-iv">
              {location.accuracy_m != null ? `±${location.accuracy_m} m` : 'not stated'}
            </span>
          </div>
        </>
      ) : (
        <div className="gh-impact-row">
          <span className="gh-ig">position</span>
          <span className="gh-ik">not recorded</span>
          <span className="gh-iv">{location.reason || 'not provided'}</span>
        </div>
      )}
      {ip && (
        <div className="gh-impact-row">
          <span className="gh-ig">network</span>
          <span className="gh-ik">address seen by the server</span>
          <span className="gh-iv">{ip}</span>
        </div>
      )}
    </div>
  )
}

/* The effect this change had, as measured when it was activated. */
function ImpactRecord({ impact }) {
  const d = impact?.deltas
  if (!d) return null
  const moved = []
  for (const [grp, fields] of Object.entries(d)) {
    if (grp === 'recommendation') continue
    for (const [k, f] of Object.entries(fields || {})) if (f?.changed) moved.push({ grp, k, ...f })
  }
  if (!moved.length && !d.recommendation?.changed) return null
  return (
    <div className="gh-impact">
      <div className="gh-impact-h">Measured effect when activated</div>
      {moved.map((m, i) => (
        <div className="gh-impact-row" key={i}>
          <span className="gh-ig">{m.grp}</span>
          <span className="gh-ik">{m.k.replace(/_/g, ' ')}</span>
          <span className="gh-iv">{String(m.before)} <i>→</i> {String(m.after)}</span>
        </div>
      ))}
      {d.recommendation?.changed && (
        <div className="gh-impact-row">
          <span className="gh-ig">advice</span>
          <span className="gh-ik">recommended plan</span>
          <span className="gh-iv">
            {(d.recommendation.before || ['—']).join(' + ')} <i>→</i> {(d.recommendation.after || ['—']).join(' + ')}
          </span>
        </div>
      )}
    </div>
  )
}

const STARTER = {
  markdown: (title) => `# ${title || 'Untitled standard'}\n\n` +
    `**Reference** RS-XX-000 · **Owner** \n\n` +
    `State what this standard governs, and who it applies to.\n\n` +
    `## 1. \n\n1. \n2. \n\n## 2. Review\n\nWhen this is reviewed, and by whom.\n`,
  text: (title) => `${(title || 'UNTITLED STANDARD').toUpperCase()}\n` +
    `Reference RS-XX-000 | Owner \n\n` +
    `State what this standard governs, and who it applies to.\n\n` +
    `  CONDITION                     ACTION                        WITHIN\n` +
    `  ------------------------------------------------------------------\n` +
    `  \n`,
}

const TYPES = [
  { id: 'markdown', name: 'Markdown', ext: '.md',
    blurb: 'Headings, lists and emphasis. Best for a procedure someone reads top to bottom.' },
  { id: 'text', name: 'Plain text', ext: '.txt',
    blurb: 'No formatting. Best for a table or a reference card meant to be read as laid out.' },
]

/* Add a policy: file type, then name, then body. */
function NewPolicyModal({ account, busy, onCancel, onSubmit }) {
  const [fmt, setFmt] = useState('markdown')
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [department, setDepartment] = useState('')
  const [text, setText] = useState('')
  const [touched, setTouched] = useState(false)
  const loc = useCapturedLocation()

  // Keep the starter in step with the choices until the author edits it.
  const body = touched ? text : STARTER[fmt](title)
  const slug = (title || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  const ok = title.trim() && body.trim() && slug

  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <b>Add a policy</b>
          <span className="modal-sub">
            A written standard: procedure, in prose. It is versioned, attributed and
            revertable exactly like every other document in the library.
          </span>
        </div>

        <div className="modal-body">
          <div className="step"><span className="step-n">1</span> File type</div>
          <div className="types">
            {TYPES.map((t) => (
              <button key={t.id} type="button"
                className={`type ${fmt === t.id ? 'on' : ''}`} onClick={() => setFmt(t.id)}>
                <span className={`lib-fmt ${t.id}`}>{t.ext}</span>
                <span className="type-name">{t.name}</span>
                <span className="type-blurb">{t.blurb}</span>
              </button>
            ))}
          </div>
          <p className="modal-note" style={{ marginTop: 0 }}>
            The structured rule-sets cannot be added here. Each one is read by a
            particular model, so a new one would have nothing reading it — it would
            look like policy and change nothing.
          </p>

          <div className="step"><span className="step-n">2</span> Name</div>
          <label className="fld">
            <span>Title <i>required</i></span>
            <input value={title} maxLength={80} autoFocus
              placeholder="e.g. Platform announcement standards"
              onChange={(e) => setTitle(e.target.value)} />
          </label>
          {slug && <div className="slug">will be saved as <b>{slug}{TYPES.find((t) => t.id === fmt).ext}</b></div>}
          <div className="fld-row">
            <label className="fld">
              <span>One-line summary</span>
              <input value={summary} maxLength={160}
                placeholder="What it governs, in a sentence"
                onChange={(e) => setSummary(e.target.value)} />
            </label>
            <label className="fld">
              <span>Department</span>
              <input value={department} maxLength={80} placeholder="e.g. Operations Control"
                onChange={(e) => setDepartment(e.target.value)} />
            </label>
          </div>

          <div className="step"><span className="step-n">3</span> Body</div>
          <textarea className="newbody" value={body} spellCheck={false} rows={13}
            onChange={(e) => { setTouched(true); setText(e.target.value) }} />

          <Attribution account={account} verb="Adding as" />
          <LocationNotice loc={loc} />
        </div>

        <div className="modal-actions">
          <button className="gh-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="gh-btn primary" disabled={!ok || busy}
            onClick={() => onSubmit({
              format: fmt, title: title.trim(), summary: summary.trim(),
              department: department.trim(), text: body,
              location: loc || { available: false, reason: 'not determined in time' },
            })}>
            {busy ? 'Adding…' : 'Add policy'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* A revert that cannot be applied cleanly. Shown rather than forced through. */
function ConflictModal({ conflict, title, onCancel, onRestore }) {
  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <b>Cannot revert v{conflict.seq} — {title}</b>
          <span className="modal-sub">
            A later change has already edited the same lines, so backing this one
            out on its own would overwrite work nobody asked to undo.
          </span>
        </div>
        <div className="modal-body">
          {conflict.conflicts.map((c, i) => (
            <div className="cf" key={i}>
              <div className="cf-why">{c.reason}</div>
              <div className="cf-block">
                <div className="cf-lbl">expected to find</div>
                {(c.expected || []).map((l, k) => <div className="cf-line del" key={k}>{l}</div>)}
              </div>
              <div className="cf-block">
                <div className="cf-lbl">and put back</div>
                {(c.would_become || []).map((l, k) => <div className="cf-line add" key={k}>{l}</div>)}
              </div>
            </div>
          ))}
          <p className="modal-note">
            Nothing has been changed. You can restore the whole version instead —
            which also discards the later changes — or edit the document by hand.
          </p>
        </div>
        <div className="modal-actions">
          <button className="gh-btn" onClick={onCancel}>Leave it alone</button>
          <button className="gh-btn danger" onClick={onRestore}>Restore v{conflict.seq} instead…</button>
        </div>
      </div>
    </div>
  )
}

/* Ask for a position as soon as the dialog opens, so the permission prompt
   and the fix both resolve before the author is ready to commit. */
function useCapturedLocation() {
  const [loc, setLoc] = useState(null)   // null = still asking
  useEffect(() => {
    let live = true
    captureLocation().then((l) => { if (live) setLoc(l) })
    return () => { live = false }
  }, [])
  return loc
}

function LocationNotice({ loc }) {
  if (loc === null) {
    return (
      <div className="geo pending">
        <span className="geo-ic">◎</span>
        <span>Requesting your location — it is recorded with this change.</span>
      </div>
    )
  }
  if (!loc.available) {
    return (
      <div className="geo none">
        <span className="geo-ic">⊘</span>
        <span>
          No location recorded — <b>{loc.reason}</b>. The change is still made and
          attributed; the register will say the position was unavailable.
        </span>
      </div>
    )
  }
  return (
    <div className="geo ok">
      <span className="geo-ic">◉</span>
      <span>
        Recording this change at <b>{formatLocation(loc)}</b>
        <a href={mapLink(loc)} target="_blank" rel="noreferrer noopener"> view on map</a>
      </span>
    </div>
  )
}

/* Who this change will be recorded against. Shown, not asked for. */
function Attribution({ account, verb }) {
  const ini = (account?.display_name || account?.email || '??')
    .split(/[\s._@-]+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('')
  return (
    <div className="attrib">
      <span className="attrib-av">{ini}</span>
      <span className="attrib-txt">
        <b>{verb} {account?.display_name}</b>
        <span>{account?.email} — this will appear against the change in the history.</span>
      </span>
    </div>
  )
}

function UndoModal({ version, mode, account, title, busy, onCancel, onSubmit }) {
  const loc = useCapturedLocation()
  const revert = mode === 'revert'
  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <b>{revert ? 'Revert a change' : 'Restore a version'} — {title}</b>
          <span className="modal-sub">
            {revert
              ? <>Backs out only what v{version.seq} did. Every change made after it stays in place.</>
              : <>Makes the document exactly as it was at v{version.seq}. Anything done since is undone.</>}
          </span>
        </div>
        <div className="modal-body">
          <div className="modal-warn">
            {revert
              ? <>This takes effect immediately and is recorded as a new version.
                  If a later change has already edited the same lines, nothing is
                  applied and you will be told where the clash is.</>
              : <>This takes effect immediately. It is recorded as a new version —
                  the history is not rewritten, and the version you are leaving is kept.</>}
          </div>
          <div className="revert-target">
            <span className="gh-sha">{version.id.slice(0, 7)}</span>
            <b>v{version.seq}</b> {version.title}
            <span className="muted small"> · {version.author_name}</span>
          </div>
          <Attribution account={account} verb={revert ? 'Reverting as' : 'Restoring as'} />
          <LocationNotice loc={loc} />
          {busy && <div className="modal-progress">
            Re-running the models so the register records what this changes.
            This takes a few seconds.
          </div>}
        </div>
        <div className="modal-actions">
          <button className="gh-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="gh-btn danger" disabled={busy}
            onClick={() => onSubmit(loc || { available: false, reason: 'not determined in time' })}>
            {busy ? 'Working…' : revert ? `Revert v${version.seq}` : `Restore v${version.seq}`}
          </button>
        </div>
      </div>
    </div>
  )
}

function PushModal({ stats, changes, previewed, account, docTitle, busy, onCancel, onSubmit }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const loc = useCapturedLocation()
  const ok = !!title.trim()

  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <b>Activate — {docTitle}</b>
          <span className="modal-sub">
            This records a permanent version of this document and puts it in force.
          </span>
        </div>

        <div className="modal-body">
          {!previewed && (
            <div className="modal-warn">
              You have not previewed this change. Activating without previewing means
              nobody has seen what it does.
            </div>
          )}
          {stats && (
            <div className="modal-stats">
              <span className="pd-add">+{stats.added}</span>
              <span className="pd-del">−{stats.removed}</span>
              <span className="muted small">
                {changes?.length
                  ? `${changes.length} rule${changes.length === 1 ? '' : 's'} amended`
                  : 'text amended'}
              </span>
            </div>
          )}

          <label className="fld">
            <span>Change title <i>required</i></span>
            <input value={title} maxLength={120} autoFocus
              placeholder="e.g. Lower crush threshold to 4.5 p/m²"
              onChange={(e) => setTitle(e.target.value)} />
          </label>

          <label className="fld">
            <span>Reason for the change</span>
            <textarea value={description} rows={4}
              placeholder="Why is this being changed, and on whose authority? This is the record future readers will rely on."
              onChange={(e) => setDescription(e.target.value)} />
          </label>

          <Attribution account={account} verb="Recording as" />
          <LocationNotice loc={loc} />
          {busy && <div className="modal-progress">
            Re-running the crowd, corridor and protection models so the register
            records what this change actually does. This takes a few seconds.
          </div>}
        </div>

        <div className="modal-actions">
          <button className="gh-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="gh-btn primary" disabled={!ok || busy}
            onClick={() => onSubmit({
              title: title.trim(), description: description.trim(),
              location: loc || { available: false, reason: 'not determined in time' },
            })}>
            {busy ? 'Activating…' : 'Activate'}
          </button>
        </div>
      </div>
    </div>
  )
}
