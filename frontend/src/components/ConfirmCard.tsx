// Confirmation card for 'act' tools. (Phase 4a)
// Ultron wants to send / delete / create / change something: nothing happens until you approve.

import { useEffect, useRef } from 'react'
import type { Confirmation, ConfirmStatus } from '../ws'

interface ConfirmCardProps {
  confirm: Confirmation
  onAnswer: (approved: boolean) => void
}

const STATUS_LABEL: Record<ConfirmStatus, string> = {
  pending: 'Waiting for you',
  approved: 'Approved',
  denied: 'Declined',
  expired: 'Expired — not done',
  stopped: 'Stopped — not done',
}

export default function ConfirmCard({ confirm, onAnswer }: ConfirmCardProps) {
  const pending = confirm.status === 'pending'
  const answer = useRef(onAnswer)
  useEffect(() => {
    answer.current = onAnswer
  })

  // Enter approves and Esc denies, unless you're typing something or a button has focus (Enter clicks that).
  // The oldest waiting card registered first, so it answers and stops the rest.
  useEffect(() => {
    if (!pending) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Enter' && e.key !== 'Escape') return
      if (e.repeat || e.isComposing || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return
      const t = e.target as HTMLElement
      if (t instanceof HTMLButtonElement || t instanceof HTMLSelectElement) return
      if ((t instanceof HTMLTextAreaElement || t instanceof HTMLInputElement) && t.value.trim() !== '') return
      e.preventDefault()
      e.stopImmediatePropagation()
      answer.current(e.key === 'Enter')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending])

  return (
    <div className={`confirm-card confirm-${confirm.status}`} role="group" aria-label="Confirmation">
      <div className="confirm-head">
        <span className="confirm-icon" aria-hidden>
          !
        </span>
        <span className="confirm-title">{confirm.title}</span>
        {!pending && <span className="confirm-status">{STATUS_LABEL[confirm.status]}</span>}
      </div>

      {confirm.details.length > 0 && (
        <dl className="confirm-details">
          {confirm.details.map(([label, value]) => (
            <div key={label} className="confirm-row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {pending && (
        <div className="confirm-actions">
          <button className="btn-approve" onClick={() => onAnswer(true)}>
            Approve <kbd>↵</kbd>
          </button>
          <button className="btn-deny" onClick={() => onAnswer(false)}>
            Deny <kbd>esc</kbd>
          </button>
        </div>
      )}
    </div>
  )
}
