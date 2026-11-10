import { useState } from 'react'
import { useApi } from './api'
import { Empty, ErrorNote, Pager } from './components'
import { fmt } from './format'
import type { AuditEntry, Page } from './types'

export default function Audit() {
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ page: String(page) })
  if (action) params.set('action', action)
  const { data, error } = useApi<Page<AuditEntry>>(`/audit/?${params}`)

  return (
    <section>
      <div className="filters">
        <label>
          Action
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setPage(1)
            }}
          >
            <option value="">any</option>
            <option value="assessment.review">assessment.review</option>
            <option value="message.review">message.review</option>
            <option value="verification.verified">verification.verified</option>
            <option value="verification.rejected">verification.rejected</option>
            <option value="user.request_verification">user.request_verification</option>
            <option value="user.suspend">user.suspend</option>
            <option value="user.reinstate">user.reinstate</option>
          </select>
        </label>
      </div>
      <ErrorNote error={error} />
      {data && data.results.length === 0 ? <Empty>No audit entries yet.</Empty> : null}
      {data && data.results.length > 0 ? (
        <>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Agent</th>
                <th>Action</th>
                <th>Target</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((e) => (
                <tr key={e.id}>
                  <td className="muted">{fmt(e.created_at)}</td>
                  <td>{e.actor_label}</td>
                  <td>
                    <code>{e.action}</code>
                  </td>
                  <td>
                    {e.target_type} #{e.target_id}
                  </td>
                  <td className="muted">
                    {Object.entries(e.metadata)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(' · ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager count={data.count} page={page} onPage={setPage} />
        </>
      ) : null}
    </section>
  )
}
