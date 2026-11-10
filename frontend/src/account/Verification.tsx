import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError, useApi } from '../api'
import { ErrorNote } from '../components'

type State = 'none' | 'requested' | 'submitted' | 'manual_review' | 'verified' | 'rejected'

interface Status {
  state: State
  can_submit: boolean
  rejection_reason: string
  requested_by_agent: boolean
}

const WAITING: State[] = ['submitted', 'manual_review']

function SubmitForm({ onSubmitted }: { onSubmitted: () => void }) {
  const [fullName, setFullName] = useState('')
  const [documentNumber, setDocumentNumber] = useState('')
  const [country, setCountry] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/api/verification/me/', {
        method: 'POST',
        body: {
          full_name: fullName,
          document_number: documentNumber,
          document_country: country,
        },
      })
      onSubmitted()
    } catch (err) {
      setError(err instanceof ApiError ? err : new Error('Could not reach the server'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <label>
        Full name (as on your document)
        <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
      </label>
      <label>
        Document number
        <input
          value={documentNumber}
          onChange={(e) => setDocumentNumber(e.target.value)}
          autoComplete="off"
        />
      </label>
      <label>
        Country of issue (2 letters, e.g. ES)
        <input
          value={country}
          maxLength={2}
          onChange={(e) => setCountry(e.target.value.toUpperCase())}
          autoComplete="country"
        />
      </label>
      <ErrorNote error={error} />
      <button
        className="primary"
        disabled={busy || fullName.trim().length < 2 || documentNumber.length < 4 || country.length !== 2}
      >
        {busy ? 'Sending…' : 'Submit for verification'}
      </button>
      <p className="muted small">
        Your details are encrypted, used only to verify your identity, and deleted after a short
        retention period once we have decided.
      </p>
    </form>
  )
}

export default function Verification() {
  const { data, error, reload } = useApi<Status>('/api/verification/me/')

  // While we wait for a decision, check again every few seconds.
  const waiting = data ? WAITING.includes(data.state) : false
  useEffect(() => {
    if (!waiting) return
    const id = window.setInterval(reload, 5000)
    return () => window.clearInterval(id)
  }, [waiting, reload])

  if (error) {
    return (
      <section className="card">
        <ErrorNote error={error} />
      </section>
    )
  }
  if (!data) return <p className="muted">Loading…</p>

  return (
    <section className="card stack">
      <h1>Verify your identity</h1>

      {data.state === 'verified' && (
        <p className="notice ok">✓ You’re verified. Thanks. There’s nothing more to do.</p>
      )}

      {data.state === 'submitted' && (
        <p className="notice wait">
          We’ve received your details and are checking them. This page updates by itself.
        </p>
      )}

      {data.state === 'manual_review' && (
        <p className="notice wait">
          Our team is reviewing your submission. We’ll update this page when it’s decided.
        </p>
      )}

      {data.state === 'rejected' && (
        <p className="notice bad">
          We couldn’t verify you{data.rejection_reason ? `: ${data.rejection_reason}` : ''}
          {/[.!?]$/.test(data.rejection_reason) ? '' : '.'} You can try again below.
        </p>
      )}

      {data.state === 'requested' && data.requested_by_agent && (
        <p className="notice wait">
          Our Trust &amp; Safety team has asked you to verify your identity.
        </p>
      )}

      {data.can_submit && <SubmitForm onSubmitted={reload} />}
    </section>
  )
}
