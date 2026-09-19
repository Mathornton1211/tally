import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { usePlaidLink } from 'react-plaid-link'
import { api, LINK_ITEM_KEY, LINK_TOKEN_KEY } from './api'

function store(key: string, value: string | null) {
  try {
    if (value == null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch { /* storage blocked; OAuth return will ask to retry */ }
}

/**
 * Opens Plaid Link. With `receivedRedirectUri` it resumes a Link session that an
 * OAuth bank (Chase, BofA, Capital One, Amex) redirected back from.
 */
export function usePlaid(opts: { token?: string | null; receivedRedirectUri?: string; onDone?: () => void } = {}) {
  const qc = useQueryClient()
  const [token, setToken] = useState<string | null>(opts.token ?? null)
  const [updateItem, setUpdateItem] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const finish = useCallback(() => {
    store(LINK_TOKEN_KEY, null)
    store(LINK_ITEM_KEY, null)
    setToken(null)
    setBusy(false)
    qc.invalidateQueries()
    opts.onDone?.()
  }, [qc, opts])

  const { open, ready } = usePlaidLink({
    // Empty token makes the hook wait. The redirect URI is only passed with a token,
    // or react-plaid-link tries to resume a session it has nothing to resume with.
    token: token ?? '',
    receivedRedirectUri: token ? opts.receivedRedirectUri : undefined,
    onSuccess: async (publicToken) => {
      try {
        const itemFromStorage = localStorage.getItem(LINK_ITEM_KEY)
        const existing = updateItem ?? (itemFromStorage ? Number(itemFromStorage) : null)
        if (existing != null) {
          // Update mode: same Item, credentials refreshed. No exchange.
          await api.syncItem(existing)
        } else {
          if (!publicToken) throw new Error('Plaid returned no public token')
          await api.exchange(publicToken)
        }
      } catch (e) {
        setError((e as Error).message)
      } finally {
        finish()
      }
    },
    onExit: (err) => {
      if (err) setError(`${err.error_code}: ${err.display_message || err.error_message}`)
      finish()
    },
  })

  useEffect(() => {
    if (token && ready) open()
  }, [token, ready, open])

  const start = async (itemId?: number) => {
    setError(null)
    setBusy(true)
    try {
      const { link_token } = await api.linkToken(itemId)
      store(LINK_TOKEN_KEY, link_token)
      store(LINK_ITEM_KEY, itemId != null ? String(itemId) : null)
      setUpdateItem(itemId ?? null)
      setToken(link_token)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return { start, error, busy }
}
