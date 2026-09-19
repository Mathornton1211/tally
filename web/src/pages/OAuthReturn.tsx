import { useNavigate } from 'react-router-dom'
import { LINK_TOKEN_KEY } from '../api'
import { usePlaid } from '../usePlaid'

function storedToken() {
  try {
    return localStorage.getItem(LINK_TOKEN_KEY)
  } catch {
    return null
  }
}

/** The bank's OAuth page sends the browser here; Link resumes where it left off. */
export default function OAuthReturn() {
  const navigate = useNavigate()
  const token = storedToken()
  const plaid = usePlaid({
    token,
    receivedRedirectUri: window.location.href,
    onDone: () => navigate('/accounts'),
  })

  if (!token) {
    return (
      <section>
        <h1>Bank login</h1>
        <p className="error">The Link session was lost (storage cleared or a different browser). Start the connection again.</p>
        <button onClick={() => navigate('/accounts')}>Back to connections</button>
      </section>
    )
  }
  return (
    <section>
      <h1>Finishing bank login…</h1>
      {plaid.error && <p className="error">{plaid.error}</p>}
    </section>
  )
}
