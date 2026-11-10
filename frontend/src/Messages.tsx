import { useState } from 'react'
import { api, ApiError, useApi } from './api'
import { Empty, ErrorNote, Pager, StatusBadge, VerdictBadge } from './components'
import { fmt } from './format'
import type { Moderation, Page } from './types'

function MessageDetail({ m, onReviewed }: { m: Moderation; onReviewed: () => void }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const reviewable = m.verdict !== 'clean' && m.review_status === 'pending'

  async function review(outcome: 'cleared' | 'confirmed') {
    setBusy(true)
    setError(null)
    try {
      await api(`/messages/${m.id}/review/`, { method: 'POST', body: { outcome, note } })
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
          Message #{m.message.id} <VerdictBadge verdict={m.verdict} />
        </h2>
        <StatusBadge status={m.review_status} />
      </header>
      <dl>
        <dt>From</dt>
        <dd>
          {m.message.sender} · booking #{m.message.booking_id}
        </dd>
        <dt>Sent</dt>
        <dd>{fmt(m.message.created_at)}</dd>
        <dt>Decided by</dt>
        <dd>
          {m.stage === 'rules' && 'rules'}
          {m.stage === 'llm' &&
            `LLM (${m.llm_model}${m.confidence !== null ? `, ${Math.round(m.confidence * 100)}% confident` : ''})`}
          {m.stage === 'llm_unavailable' && 'rules only: LLM unavailable, needs a human'}
        </dd>
      </dl>
      <blockquote>{m.message.body}</blockquote>

      <h3>Why</h3>
      {m.categories.length > 0 && (
        <p>
          {m.categories.map((c) => (
            <code key={c}>{c}</code>
          ))}
        </p>
      )}
      <ul className="hits">
        {m.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {m.llm_input_tokens !== null && (
        <p className="muted">
          LLM cost: {m.llm_input_tokens} in / {m.llm_output_tokens} out tokens ·{' '}
          {m.llm_latency_ms} ms
        </p>
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
            <button
              className="danger"
              disabled={busy || !note.trim()}
              onClick={() => review('confirmed')}
            >
              Confirm violation
            </button>
          </div>
        </section>
      ) : (
        <p className="muted">
          {m.verdict === 'clean'
            ? 'Clean; nothing to review.'
            : `${m.review_status} by ${m.reviewed_by ?? '—'} on ${fmt(m.reviewed_at)}${
                m.review_note ? `: “${m.review_note}”` : ''
              }`}
        </p>
      )}
    </aside>
  )
}

export default function Messages() {
  const [verdict, setVerdict] = useState('')
  const [reviewStatus, setReviewStatus] = useState('pending')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const params = new URLSearchParams({ page: String(page) })
  if (verdict) params.set('verdict', verdict)
  else params.set('verdict', 'flagged,needs_review') // default queue: anything not clean
  if (reviewStatus) params.set('review_status', reviewStatus)
  const { data, error, loading, reload } = useApi<Page<Moderation>>(`/messages/?${params}`)
  const selected = data?.results.find((m) => m.id === selectedId) ?? null

  return (
    <div className="split">
      <section>
        <div className="filters">
          <label>
            Verdict
            <select
              value={verdict}
              onChange={(e) => {
                setVerdict(e.target.value)
                setPage(1)
              }}
            >
              <option value="">flagged + needs review</option>
              <option value="flagged">flagged</option>
              <option value="needs_review">needs review</option>
              <option value="clean">clean</option>
            </select>
          </label>
          <label>
            Status
            <select
              value={reviewStatus}
              onChange={(e) => {
                setReviewStatus(e.target.value)
                setPage(1)
              }}
            >
              <option value="">any</option>
              <option value="pending">pending</option>
              <option value="cleared">cleared</option>
              <option value="confirmed">confirmed</option>
            </select>
          </label>
        </div>
        <ErrorNote error={error} />
        {loading && !data ? <p className="muted">Loading…</p> : null}
        {data && data.results.length === 0 ? <Empty>No messages to review 🎉</Empty> : null}
        {data && data.results.length > 0 ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>Verdict</th>
                  <th>From</th>
                  <th>Message</th>
                  <th>Categories</th>
                  <th>By</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((m) => (
                  <tr
                    key={m.id}
                    className={m.id === selectedId ? 'selected' : ''}
                    onClick={() => setSelectedId(m.id)}
                  >
                    <td>
                      <VerdictBadge verdict={m.verdict} />
                    </td>
                    <td>{m.message.sender}</td>
                    <td className="snippet" title={m.message.body}>
                      {m.message.body}
                    </td>
                    <td>
                      {m.categories.map((c) => (
                        <code key={c}>{c}</code>
                      ))}
                    </td>
                    <td className="muted">{m.stage}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager count={data.count} page={page} onPage={setPage} />
          </>
        ) : null}
      </section>
      {selected ? (
        <MessageDetail key={selected.id} m={selected} onReviewed={reload} />
      ) : (
        <aside className="detail card muted">Select a message to see why it was flagged.</aside>
      )}
    </div>
  )
}
