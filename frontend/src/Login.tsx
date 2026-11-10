import { useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import { ErrorNote } from './components'
import type { Me } from './types'

export default function Login({
  onLogin,
  path = '/auth/login/',
  subtitle = 'Trust & Safety console',
}: {
  onLogin: (me: Me) => void
  path?: string
  subtitle?: string
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onLogin(await api<Me>(path, { method: 'POST', body: { username, password } }))
    } catch (err) {
      setError(err instanceof ApiError ? err : new Error('Could not reach the server'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} className="card">
        <h1>🐾 PawGuard</h1>
        <p className="muted">{subtitle}</p>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <ErrorNote error={error} />
        <button className="primary" disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
