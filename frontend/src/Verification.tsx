import { useState } from 'react'
import { api, ApiError, useApi } from './api'
import { Empty, ErrorNote, Pager, VerificationBadge } from './components'
import { fmt } from './format'
import type { Page, VerificationCase } from './types'

function CaseDetail({ c, onChanged }: { c: VerificationCase; onChanged: () => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)

  async function decide(verb: 'approve' | 'reject') {
    setBusy(true)
    setError(null)
    try {
      await api(`/verifications/${c.id}/${verb}/`, { method: 'POST', body: { reason } })
      setReason('')
      onChanged()
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
          Case #{c.id} <VerificationBadge state={c.state} />
        </h2>
      </header>
      <dl>
        <dt>User</dt>
        <dd>{c.user}</dd>
        <dt>Name</dt>
        <dd>{c.full_name || '—'}</dd>
        <dt>Document</dt>
        <dd>
          {c.document_number_masked || '—'} {c.document_country && `(${c.document_country})`}
        </dd>
        <dt>Provider ref</dt>
        <dd>{c.provider_ref ?? 'not sent yet'}</dd>
      </dl>
      {c.purged_at && (
        <p className="muted">Personal data purged on {fmt(c.purged_at)} (retention policy).</p>
      )}

      {c.state === 'manual_review' && (
        <section className="review">
          <h3>Decide</h3>
          <textarea
            placeholder="Reason (recorded in the audit trail)"
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
          />
          <ErrorNote error={error} />
          <div className="row">
            <button disabled={busy || !reason.trim()} onClick={() => decide('approve')}>
              Approve
            </button>
            <button
              className="danger"
              disabled={busy || !reason.trim()}
              onClick={() => decide('reject')}
            >
              Reject
            </button>
          </div>
        </section>
      )}
      {c.state === 'rejected' && c.rejection_reason && (
        <p className="muted">Rejected: “{c.rejection_reason}”</p>
      )}

      <h3>Audit trail</h3>
      <ul className="timeline">
        {c.events.map((e, i) => (
          <li key={i}>
            <strong>
              {e.from_state ? `${e.from_state} → ` : ''}
              {e.to_state}
            </strong>{' '}
            <span className="muted">
              by {e.actor_label || e.source} · {fmt(e.created_at)}
            </span>
            {e.detail && <div>{e.detail}</div>}
          </li>
        ))}
      </ul>
    </aside>
  )
}

export default function Verification() {
  const [state, setState] = useState('manual_review')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const params = new URLSearchParams({ page: String(page) })
  if (state) params.set('state', state)
  const { data, error, loading, reload } = useApi<Page<VerificationCase>>(
    `/verifications/?${params}`,
  )
  const selected = data?.results.find((c) => c.id === selectedId) ?? null

  return (
    <div className="split">
      <section>
        <div className="filters">
          <label>
            State
            <select
              value={state}
              onChange={(e) => {
                setState(e.target.value)
                setPage(1)
              }}
            >
              <option value="manual_review">manual review</option>
              <option value="">any</option>
              <option value="requested">requested</option>
              <option value="submitted">submitted</option>
              <option value="verified">verified</option>
              <option value="rejected">rejected</option>
            </select>
          </label>
        </div>
        <ErrorNote error={error} />
        {loading && !data ? <p className="muted">Loading…</p> : null}
        {data && data.results.length === 0 ? <Empty>No cases here 🎉</Empty> : null}
        {data && data.results.length > 0 ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>User</th>
                  <th>State</th>
                  <th>Submitted</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((c) => (
                  <tr
                    key={c.id}
                    className={c.id === selectedId ? 'selected' : ''}
                    onClick={() => setSelectedId(c.id)}
                  >
                    <td>#{c.id}</td>
                    <td>{c.user}</td>
                    <td>
                      <VerificationBadge state={c.state} />
                    </td>
                    <td className="muted">{fmt(c.submitted_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager count={data.count} page={page} onPage={setPage} />
          </>
        ) : null}
      </section>
      {selected ? (
        <CaseDetail key={selected.id} c={selected} onChanged={reload} />
      ) : (
        <aside className="detail card muted">Select a case to review it.</aside>
      )}
    </div>
  )
}
