import { useEffect, useState } from 'react'
import { api, ApiError, primeCsrf } from './api'
import Audit from './Audit'
import Login from './Login'
import Messages from './Messages'
import Queue from './Queue'
import type { Me } from './types'
import Users from './Users'

type Tab = 'queue' | 'messages' | 'users' | 'audit'

const LABELS: Record<Tab, string> = {
  queue: 'Risk queue',
  messages: 'Messages',
  users: 'Users',
  audit: 'Audit log',
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [ready, setReady] = useState(false)
  const [tab, setTab] = useState<Tab>('queue')
  const [userId, setUserId] = useState<number | null>(null)

  useEffect(() => {
    // Set the CSRF cookie, then see whether a session already exists.
    primeCsrf()
      .then(() => api<Me>('/auth/me/'))
      .then(setMe)
      .catch((e) => {
        if (!(e instanceof ApiError) || ![401, 403].includes(e.status)) console.error(e)
      })
      .finally(() => setReady(true))
  }, [])

  if (!ready) return <p className="muted center">Loading…</p>
  if (!me) return <Login onLogin={setMe} />

  async function logout() {
    await api('/auth/logout/', { method: 'POST' })
    setMe(null)
  }

  const openUser = (id: number) => {
    setUserId(id)
    setTab('users')
  }

  return (
    <>
      <header className="topbar">
        <strong>🐾 PawGuard</strong>
        <nav>
          {(['queue', 'messages', 'users', 'audit'] as const).map((t) => (
            <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>
              {LABELS[t]}
            </button>
          ))}
        </nav>
        <span className="spacer" />
        <span className="muted">{me.username}</span>
        <button onClick={logout}>Sign out</button>
      </header>
      <main className="content">
        {tab === 'queue' && <Queue onOpenUser={openUser} />}
        {tab === 'messages' && <Messages />}
        {tab === 'users' && <Users key={userId ?? 'none'} initialId={userId} />}
        {tab === 'audit' && <Audit />}
      </main>
    </>
  )
}
