import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Account from './account/Account.tsx'
import App from './App.tsx'

// The same bundle serves two apps: /account is for owners and sitters, everything else is the
// agent console.
const isAccount = window.location.pathname.startsWith('/account')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isAccount ? <Account /> : <App />}
  </StrictMode>,
)
