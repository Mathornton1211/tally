import { ArrowUp, CaretDown, CheckCircle, Code, Sparkle, Warning } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { cx, PageHeader } from '../components/ui'

type Table = { columns: string[]; rows: Record<string, unknown>[]; truncated: boolean }
type Msg = {
  role: 'user' | 'assistant'
  content: string
  status?: string
  sql?: string
  table?: Table
  verified?: boolean
  unverified?: string[]
  error?: string
  pending?: boolean
}

const MONEY_COL = /total|amount|spend|income|balance|average|avg|sum|cost|limit|price/i
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

function cell(col: string, v: unknown) {
  if (v == null) return '—'
  if (typeof v === 'number' && MONEY_COL.test(col)) return usd.format(v)
  if (typeof v === 'number') return v.toLocaleString()
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

function ResultTable({ t }: { t: Table }) {
  if (!t.rows.length) return <div className="px-3 py-2 text-[12px] text-ink-3">No rows.</div>
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-[12px]">
        <thead className="sticky top-0 bg-surface-2">
          <tr>{t.columns.map((c) => <th key={c} className="px-3 py-1.5 text-left font-medium text-ink-3">{c.replace(/_/g, ' ')}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {t.rows.map((r, i) => (
            <tr key={i}>{t.columns.map((c) => (
              <td key={c} className={cx('px-3 py-1.5 text-ink', typeof r[c] === 'number' && 'text-right tnum')}>{cell(c, r[c])}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
      {t.truncated && <div className="px-3 py-1.5 text-[11px] text-ink-3">First 200 rows shown.</div>}
    </div>
  )
}

function Elapsed() {
  const [s, setS] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setS((x) => x + 1), 1000)
    return () => clearInterval(t)
  }, [])
  return s >= 3 ? <span className="ml-1 tnum text-ink-3">{s}s</span> : null
}

const STORE = 'tally.chat'
function loadMsgs(): Msg[] {
  try {
    const raw = sessionStorage.getItem(STORE)
    return raw ? (JSON.parse(raw) as Msg[]).filter((m) => !m.pending) : []
  } catch {
    return []
  }
}

function Answer({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-positive">
        <Sparkle size={16} weight="fill" />
      </div>
      <div className="min-w-0 flex-1">
        {m.error ? (
          <div className="rounded-2xl bg-bad-soft px-4 py-3 text-[14px] text-negative">{m.error}</div>
        ) : (
          <div className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink">
            {m.content}
            {m.pending && !m.content && <span className="text-ink-3">{m.status ?? 'Thinking'}…<Elapsed /></span>}
            {m.pending && m.content && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-ink-3 align-middle" />}
          </div>
        )}
        {m.pending && m.content === '' && (
          <div className="mt-2 flex gap-1">{[0, 1, 2].map((i) => (
            <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-3" style={{ animationDelay: `${i * 120}ms` }} />
          ))}</div>
        )}
        {!m.pending && (m.sql || m.table) && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {m.verified ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-positive">
                <CheckCircle size={12} weight="fill" /> Every number checked against your data
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn"
                    title={`Not found in the query result: ${(m.unverified ?? []).join(', ')}`}>
                <Warning size={12} weight="fill" /> Couldn't verify {(m.unverified ?? []).join(', ')}. Check the table.
              </span>
            )}
            <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-ink-2 hover:bg-hover">
              <Code size={12} /> How I got this <CaretDown size={10} className={cx('transition-transform', open && 'rotate-180')} />
            </button>
          </div>
        )}
        {open && (m.sql || m.table) && (
          <div className="mt-2 overflow-hidden rounded-xl border border-line">
            {/* A what-if has no SQL: the figures are computed from the history
                rather than found in it. The table is still the whole working,
                so it has to be reachable either way. */}
            {m.sql
              ? <pre className="overflow-x-auto whitespace-pre-wrap bg-surface-2 px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-2">{m.sql}</pre>
              : <p className="bg-surface-2 px-3 py-2 text-[11px] leading-relaxed text-ink-2">Worked out from your balances, APRs and minimum payments, with spending measured over your last 90 days. Take-home pay from a salary is an estimate.</p>}
            {m.table && <ResultTable t={m.table} />}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Assistant() {
  const [params, setParams] = useSearchParams()
  const [msgs, setMsgs] = useState<Msg[]>(loadMsgs)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const status = useQuery({ queryKey: ['ai-status'], queryFn: () => fetch('/api/ai/status').then((r) => r.json()), refetchInterval: 30_000 })
  const sugg = useQuery({ queryKey: ['chat-suggestions'], queryFn: () => fetch('/api/chat/suggestions').then((r) => r.json() as Promise<string[]>) })
  const bottom = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const started = useRef(false)

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs])
  // The conversation survives leaving the page and coming back (this tab only).
  useEffect(() => {
    if (msgs.some((m) => m.pending)) return
    try { sessionStorage.setItem(STORE, JSON.stringify(msgs.slice(-30))) } catch { /* storage blocked */ }
  }, [msgs])

  const send = async (q: string) => {
    const question = q.trim()
    if (!question || busy) return
    setInput('')
    setBusy(true)
    const history = msgs.filter((m) => !m.error && m.content).map((m) => ({ role: m.role, content: m.content }))
    setMsgs((m) => [...m, { role: 'user', content: question }, { role: 'assistant', content: '', pending: true }])
    const patch = (fn: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), fn(all[all.length - 1])])
    try {
      const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, history }) })
      if (!r.ok || !r.body) throw new Error(`${r.status}`)
      const reader = r.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let nl
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl)
          buf = buf.slice(nl + 1)
          if (!line) continue
          const ev = JSON.parse(line)
          if (ev.type === 'status') patch((m) => ({ ...m, status: ev.text }))
          else if (ev.type === 'sql') patch((m) => ({ ...m, sql: ev.sql }))
          else if (ev.type === 'table') patch((m) => ({ ...m, table: ev }))
          else if (ev.type === 'token') patch((m) => ({ ...m, content: m.content + ev.text }))
          else if (ev.type === 'done') patch((m) => ({ ...m, pending: false, verified: ev.verified, unverified: ev.unverified }))
          else if (ev.type === 'error') patch((m) => ({ ...m, pending: false, error: ev.text }))
        }
      }
      patch((m) => ({ ...m, pending: false }))
    } catch {
      patch((m) => ({ ...m, pending: false, error: "Couldn't reach Tally. Is the server running?" }))
    } finally {
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  // Deep link from the dashboard: /assistant?q=...
  useEffect(() => {
    const q = params.get('q')
    if (q && !started.current) {
      started.current = true
      setParams({}, { replace: true })
      send(q)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const s = status.data
  return (
    <div className="flex min-h-[calc(100dvh-10rem)] flex-col">
      <PageHeader title="Ask Tally" sub="Questions about your money, answered from your own data by the model running on your server.">
        {s && (
          <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px]', s.reachable ? 'bg-hover text-ink-2' : 'bg-bad-soft text-negative')}>
            <span className={cx('h-1.5 w-1.5 rounded-full', s.reachable ? (s.loaded ? 'bg-positive' : 'bg-ink-3') : 'bg-negative')} />
            {s.reachable ? (s.loaded ? 'Model ready' : 'Model asleep, first answer takes ~30s longer') : 'Model offline'}
          </span>
        )}
      </PageHeader>

      <div className="flex-1">
        {msgs.length > 0 && !busy && (
          <div className="mx-auto mb-2 flex max-w-[760px] justify-end"><button onClick={() => setMsgs([])} className="text-[12px] text-ink-3 hover:text-ink">New conversation</button></div>
        )}
        {msgs.length === 0 ? (
          <div className="mx-auto mt-6 max-w-[640px]">
            <div className="mb-3 text-[13px] font-medium text-ink-3">Try asking</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {(sugg.data ?? []).map((q) => (
                <button key={q} onClick={() => send(q)}
                        className="panel rise px-4 py-3 text-left text-[14px] text-ink transition-colors hover:bg-hover">
                  {q}
                </button>
              ))}
            </div>
            <p className="mt-6 text-[12px] leading-relaxed text-ink-3">
              Tally turns your question into a read-only database query, runs it, and has the model explain the result.
              Nothing leaves your network, the query cannot change anything, and every dollar figure in the answer is checked against the actual result.
            </p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-[760px] flex-col gap-6 pb-6">
            {msgs.map((m, i) => m.role === 'user' ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-[15px] text-page">{m.content}</div>
              </div>
            ) : <Answer key={i} m={m} />)}
            <div ref={bottom} />
          </div>
        )}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(input) }}
            className="sticky bottom-20 mx-auto mt-4 w-full max-w-[760px] lg:bottom-6">
        <div className="panel flex items-end gap-2 p-2 shadow-[0_12px_40px_-16px_rgba(0,0,0,0.35)]">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
            rows={1}
            placeholder="How much did I spend on groceries last month?"
            className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-3 py-2 text-[15px] text-ink outline-none placeholder:text-ink-3"
            aria-label="Ask a question"
          />
          <button type="submit" disabled={busy || !input.trim()} aria-label="Send"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink transition-transform active:scale-95 disabled:opacity-40">
            <ArrowUp size={18} weight="bold" />
          </button>
        </div>
      </form>
    </div>
  )
}
