/*
 * The document editor: a plain monospace text area with a line-number gutter
 * and a validity strip, styled like editing a file on a code host.
 *
 * Deliberately NOT a form of labelled inputs. A form would hide the comments
 * that explain each rule, and those comments are half the document's value —
 * they are what tells the next person why the threshold is 5.0. Editing the
 * text keeps the reasoning next to the rule, and makes the change diffable.
 */
import { useEffect, useRef } from 'react'

export default function PolicyEditor({ value, onChange, readOnly = false, errors = [], valid = true }) {
  const taRef = useRef(null)
  const gutterRef = useRef(null)

  const lines = value ? value.split('\n').length : 1

  // Keep the gutter locked to the textarea's scroll position.
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    const sync = () => { if (gutterRef.current) gutterRef.current.scrollTop = ta.scrollTop }
    ta.addEventListener('scroll', sync)
    return () => ta.removeEventListener('scroll', sync)
  }, [])

  // Tab should indent, not move focus out of the editor — this is a code field.
  function onKeyDown(e) {
    if (e.key !== 'Tab' || readOnly) return
    e.preventDefault()
    const ta = e.target
    const { selectionStart: s, selectionEnd: en } = ta
    const next = `${value.slice(0, s)}  ${value.slice(en)}`
    onChange(next)
    requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 2 })
  }

  return (
    <div className={`pe ${valid ? '' : 'invalid'}`}>
      <div className="pe-body">
        <div className="pe-gutter" ref={gutterRef} aria-hidden="true">
          {Array.from({ length: lines }, (_, i) => <div key={i}>{i + 1}</div>)}
        </div>
        <textarea
          ref={taRef}
          className="pe-ta"
          value={value}
          readOnly={readOnly}
          spellCheck={false}
          wrap="off"
          onKeyDown={onKeyDown}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      <div className={`pe-status ${valid ? 'ok' : 'bad'}`}>
        {valid ? (
          <><span className="pe-tick">✓</span> Valid policy · {lines} lines</>
        ) : (
          <>
            <span className="pe-cross">✕</span>
            {errors.length} problem{errors.length === 1 ? '' : 's'}
            <ul className="pe-errs">
              {errors.slice(0, 6).map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
