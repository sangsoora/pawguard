import type { ReactNode } from 'react'
import type { Decision, ReviewStatus, Verdict, VerificationState } from './types'

export function ScoreBadge({ score, decision }: { score: number; decision: Decision }) {
  return (
    <span className={`badge score ${decision}`} title={decision}>
      {score}
    </span>
  )
}

export function StatusBadge({ status }: { status: ReviewStatus | 'active' | 'suspended' }) {
  return <span className={`badge status ${status}`}>{status}</span>
}

export function Pager({
  count,
  page,
  pageSize = 25,
  onPage,
}: {
  count: number
  page: number
  pageSize?: number
  onPage: (p: number) => void
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  return (
    <div className="pager">
      <span>{count} results</span>
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ‹ Prev
      </button>
      <span>
        {page} / {pages}
      </span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next ›
      </button>
    </div>
  )
}

export function ErrorNote({ error }: { error: Error | null }) {
  return error ? <p className="error">{error.message}</p> : null
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <span className={`badge verdict ${verdict}`}>{verdict.replace('_', ' ')}</span>
}

export function VerificationBadge({ state }: { state: VerificationState | null }) {
  const label = state ?? 'none'
  return <span className={`badge vstate ${label}`}>{label.replace('_', ' ')}</span>
}
