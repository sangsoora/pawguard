import { useState } from 'react'
import { api, ApiError, useApi } from './api'
import { Empty, ErrorNote, Pager, ScoreBadge, StatusBadge } from './components'
import { fmt } from './format'
import type { Assessment, Page } from './types'

function AssessmentDetail({
  a,
  onReviewed,
  onOpenUser,
}: {
  a: Assessment
  onReviewed: () => void
  onOpenUser: (id: number) => void
}) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const reviewable = a.decision !== 'allow' && a.review_status === 'pending'

  async function review(outcome: 'cleared' | 'confirmed') {
    setBusy(true)
    setError(null)
    try {
      await api(`/assessments/${a.id}/review/`, { method: 'POST', body: { outcome, note } })
      setNote('')
      onReviewed()
    } catch (e) {
      setError(e instanceof ApiError ? e : new Error('Request failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="detail card">
      <header>
        <h2>
          Assessment #{a.id} <ScoreBadge score={a.score} decision={a.decision} />
        </h2>
        <StatusBadge status={a.review_status} />
      </header>

      <dl>
        <dt>Owner</dt>
        <dd>
          <button className="link" onClick={() => onOpenUser(a.user_id)}>
            {a.user}
          </button>
        </dd>
        <dt>Booking</dt>
        <dd>
          #{a.booking.id} → {a.booking.sitter}, {a.booking.amount} {a.booking.currency}
          <br />
          {a.booking.start_date} to {a.booking.end_date} ({a.booking.status})
        </dd>
        <dt>Scored</dt>
        <dd>{fmt(a.created_at)}</dd>
      </dl>

      <h3>Why it was flagged</h3>
      {a.hits.length === 0 ? (
        <Empty>No rules fired.</Empty>
      ) : (
        <ul className="hits">
          {a.hits.map((h) => (
            <li key={h.reason_code} className={h.shadow ? 'shadow' : ''}>
              <strong>{h.reason_code}</strong>
              <span className="muted">
                {h.shadow ? ' · shadow (not scored)' : ` · +${h.points}`}
              </span>
              <div>{h.detail}</div>
            </li>
          ))}
        </ul>
      )}

      {reviewable ? (
        <section className="review">
          <h3>Resolve</h3>
          <textarea
            placeholder="Note (required to confirm)"
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
          />
          <ErrorNote error={error} />
          <div className="row">
            <button disabled={busy} onClick={() => review('cleared')}>
              Clear (false positive)
            </button>
            <button className="danger" disabled={busy || !note.trim()} onClick={() => review('confirmed')}>
              Confirm risk
            </button>
          </div>
        </section>
      ) : (
        <p className="muted">
          {a.decision === 'allow'
            ? 'Allowed automatically; nothing to review.'
            : `${a.review_status} by ${a.reviewed_by ?? '—'} on ${fmt(a.reviewed_at)}${
                a.review_note ? `: “${a.review_note}”` : ''
              }`}
        </p>
      )}
    </aside>
  )
}

export default function Queue({ onOpenUser }: { onOpenUser: (id: number) => void }) {
  const [reviewStatus, setReviewStatus] = useState('pending')
  const [decision, setDecision] = useState('')
  const [minScore, setMinScore] = useState('40')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const params = new URLSearchParams({ page: String(page) })
  if (reviewStatus) params.set('review_status', reviewStatus)
  if (decision) params.set('decision', decision)
  if (minScore) params.set('min_score', minScore)
  const { data, error, loading, reload } = useApi<Page<Assessment>>(`/assessments/?${params}`)

  const selected = data?.results.find((a) => a.id === selectedId) ?? null
  const setFilter = (fn: () => void) => {
    fn()
    setPage(1)
  }

  return (
    <div className="split">
      <section>
        <div className="filters">
          <label>
            Status
            <select value={reviewStatus} onChange={(e) => setFilter(() => setReviewStatus(e.target.value))}>
              <option value="">any</option>
              <option value="pending">pending</option>
              <option value="cleared">cleared</option>
              <option value="confirmed">confirmed</option>
            </select>
          </label>
          <label>
            Decision
            <select value={decision} onChange={(e) => setFilter(() => setDecision(e.target.value))}>
              <option value="">any</option>
              <option value="review">review</option>
              <option value="block">block</option>
              <option value="allow">allow</option>
            </select>
          </label>
          <label>
            Min score
            <input
              type="number"
              min={0}
              max={100}
              value={minScore}
              onChange={(e) => setFilter(() => setMinScore(e.target.value))}
            />
          </label>
        </div>

        <ErrorNote error={error} />
        {loading && !data ? <p className="muted">Loading…</p> : null}
        {data && data.results.length === 0 ? <Empty>Queue is empty 🎉</Empty> : null}
        {data && data.results.length > 0 ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>Score</th>
                  <th>Owner</th>
                  <th>Sitter</th>
                  <th>Amount</th>
                  <th>Reasons</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((a) => (
                  <tr
                    key={a.id}
                    className={a.id === selectedId ? 'selected' : ''}
                    onClick={() => setSelectedId(a.id)}
                  >
                    <td>
                      <ScoreBadge score={a.score} decision={a.decision} />
                    </td>
                    <td>{a.user}</td>
                    <td>{a.booking.sitter}</td>
                    <td>
                      {a.booking.amount} {a.booking.currency}
                    </td>
                    <td>
                      {a.hits.map((h) => (
                        <code key={h.reason_code} className={h.shadow ? 'shadow' : ''}>
                          {h.reason_code}
                        </code>
                      ))}
                    </td>
                    <td className="muted">{fmt(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager count={data.count} page={page} onPage={setPage} />
          </>
        ) : null}
      </section>

      {selected ? (
        <AssessmentDetail key={selected.id} a={selected} onReviewed={reload} onOpenUser={onOpenUser} />
      ) : (
        <aside className="detail card muted">Select an assessment to see why it was flagged.</aside>
      )}
    </div>
  )
}
