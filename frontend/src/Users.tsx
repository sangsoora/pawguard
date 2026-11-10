import { useState } from 'react'
import { api, ApiError, useApi } from './api'
import {
  Empty,
  ErrorNote,
  Pager,
  ScoreBadge,
  StatusBadge,
  VerificationBadge,
} from './components'
import { fmt } from './format'
import type { Assessment, ConsoleUser, Page } from './types'

function AssessmentList({
  items,
  empty,
  showOwner = false,
}: {
  items?: Assessment[]
  empty: string
  showOwner?: boolean
}) {
  if (!items?.length) return <Empty>{empty}</Empty>
  return (
    <ul className="hits">
      {items.map((a) => (
        <li key={a.id}>
          <ScoreBadge score={a.score} decision={a.decision} /> booking #{a.booking.id}{' '}
          {showOwner ? `from ${a.user}` : `→ ${a.booking.sitter}`} ·{' '}
          <StatusBadge status={a.review_status} />
          <div className="muted">
            {a.hits.map((h) => h.reason_code).join(', ') || 'no rules fired'}
          </div>
        </li>
      ))}
    </ul>
  )
}

function UserDetail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { data: u, error, reload } = useApi<ConsoleUser>(`/users/${id}/`)
  const [reason, setReason] = useState('')
  const [actionError, setActionError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)

  if (error) return <aside className="detail card"><ErrorNote error={error} /></aside>
  if (!u) return <aside className="detail card muted">Loading…</aside>

  const isAgent = u.role === 'agent'
  const verb = u.status === 'active' ? 'suspend' : 'reinstate'

  async function requestVerification() {
    setBusy(true)
    setActionError(null)
    try {
      await api(`/users/${id}/request-verification/`, { method: 'POST' })
      reload()
      onChanged()
    } catch (e) {
      setActionError(e instanceof ApiError ? e : new Error('Request failed'))
    } finally {
      setBusy(false)
    }
  }

  async function act() {
    setBusy(true)
    setActionError(null)
    try {
      await api(`/users/${id}/${verb}/`, { method: 'POST', body: { reason } })
      setReason('')
      reload()
      onChanged()
    } catch (e) {
      setActionError(e instanceof ApiError ? e : new Error('Request failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="detail card">
      <header>
        <h2>{u.username}</h2>
        <StatusBadge status={u.status} />
      </header>
      <dl>
        <dt>Role</dt>
        <dd>{u.role}</dd>
        <dt>Email</dt>
        <dd>{u.email}</dd>
        <dt>Phone</dt>
        <dd>{u.phone_number || '—'}</dd>
        <dt>Country / IP</dt>
        <dd>
          {u.country || '—'} / {u.signup_ip ?? '—'}
        </dd>
        <dt>Identity</dt>
        <dd>
          <VerificationBadge state={u.verification_state} />
          {!isAgent && (!u.verification_state || u.verification_state === 'rejected') && (
            <>
              {' '}
              <button className="link" disabled={busy} onClick={requestVerification}>
                Request verification
              </button>
            </>
          )}
        </dd>
        <dt>Joined</dt>
        <dd>{fmt(u.date_joined)}</dd>
      </dl>

      {isAgent ? (
        <p className="muted">Agent accounts can’t be changed from the console.</p>
      ) : (
        <section className="review">
          <h3>{verb === 'suspend' ? 'Suspend account' : 'Reinstate account'}</h3>
          <textarea
            placeholder="Reason (recorded in the audit log)"
            value={reason}
            maxLength={500}
            onChange={(e) => setReason(e.target.value)}
          />
          <ErrorNote error={actionError} />
          <button
            className={verb === 'suspend' ? 'danger' : ''}
            disabled={busy || !reason.trim()}
            onClick={act}
          >
            {verb === 'suspend' ? 'Suspend' : 'Reinstate'}
          </button>
        </section>
      )}

      <h3>As booking owner</h3>
      <AssessmentList items={u.recent_assessments} empty="No bookings made by this user were scored." />
      <h3>As sitter (bookings received)</h3>
      <AssessmentList
        items={u.received_assessments}
        empty="No bookings received by this user were scored."
        showOwner
      />
    </aside>
  )
}

export default function Users({ initialId }: { initialId: number | null }) {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(initialId)

  const params = new URLSearchParams({ page: String(page) })
  if (search) params.set('search', search)
  if (status) params.set('status', status)
  const { data, error, reload } = useApi<Page<ConsoleUser>>(`/users/?${params}`)

  return (
    <div className="split">
      <section>
        <div className="filters">
          <label>
            Search
            <input
              placeholder="username, email, phone"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
            />
          </label>
          <label>
            Status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value)
                setPage(1)
              }}
            >
              <option value="">any</option>
              <option value="active">active</option>
              <option value="suspended">suspended</option>
            </select>
          </label>
        </div>
        <ErrorNote error={error} />
        {data && data.results.length === 0 ? <Empty>No users match.</Empty> : null}
        {data && data.results.length > 0 ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Identity</th>
                  <th>Risk</th>
                  <th>As owner</th>
                  <th>As sitter</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((u) => (
                  <tr
                    key={u.id}
                    className={u.id === selectedId ? 'selected' : ''}
                    onClick={() => setSelectedId(u.id)}
                  >
                    <td>{u.username}</td>
                    <td>{u.role}</td>
                    <td>
                      <StatusBadge status={u.status} />
                    </td>
                    <td>
                      <VerificationBadge state={u.verification_state} />
                    </td>
                    <td>{u.risk_score || '—'}</td>
                    <td>{u.assessment_count}</td>
                    <td>
                      {u.sitter_max_score === null
                        ? '—'
                        : `max ${u.sitter_max_score} · ${u.sitter_flagged_count} flagged`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager count={data.count} page={page} onPage={setPage} />
          </>
        ) : null}
      </section>
      {selectedId ? (
        <UserDetail key={selectedId} id={selectedId} onChanged={reload} />
      ) : (
        <aside className="detail card muted">Select a user.</aside>
      )}
    </div>
  )
}
