import { useEffect, useState } from 'react'
import { api, primeCsrf } from '../api'
import Login from '../Login'
import type { Me } from '../types'
import Verification from './Verification'

/** The marketplace-user app (owners and sitters). Served at /account. */
export default function Account() {
  const [me, setMe] = useState<Me | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    primeCsrf('/api/account/auth/csrf/')
      .then(() => api<Me>('/api/account/auth/me/'))
      .then(setMe)
      .catch(() => undefined) // not signed in
      .finally(() => setReady(true))
  }, [])

  if (!ready) return <p className="muted center">Loading…</p>
  if (!me) {
    return (
      <Login
        onLogin={setMe}
        path="/api/account/auth/login/"
        subtitle="Sign in to your PawGuard account"
      />
    )
  }

  async function logout() {
    await api('/api/account/auth/logout/', { method: 'POST' })
    setMe(null)
  }

  return (
    <>
      <header className="topbar">
        <strong>🐾 PawGuard</strong>
        <span className="spacer" />
        <span className="muted">{me.username}</span>
        <button onClick={logout}>Sign out</button>
      </header>
      <main className="account">
        <Verification />
      </main>
    </>
  )
}
