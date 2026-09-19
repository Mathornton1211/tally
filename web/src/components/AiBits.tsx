import { ArrowRight, BellRinging, CheckCircle, Sparkle, Warning } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Button, cx, Panel, Skeleton } from './ui'

type Digest = {
  month: string
  has_data: boolean
  digest: { headline: string; body: string; verified: boolean; model: string; created_at?: string } | null
}

const monthName = (iso: string) => {
  const [y, m] = iso.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'long' })
}

export function DigestCard() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['digest'], queryFn: () => fetch('/api/digest').then((r) => r.json() as Promise<Digest>) })
  const make = useMutation({
    mutationFn: async () => {
      const r = await fetch('/api/digest', { method: 'POST' })
      if (!r.ok) throw new Error((await r.json()).detail ?? `${r.status}`)
      return r.json()
    },
    onSuccess: (d) => qc.setQueryData(['digest'], d),
  })
  const d = q.data
  if (!d || !d.has_data) return null
  const name = monthName(d.month)

  return (
    <Panel className="md:col-span-12">
      <div className="flex flex-col gap-4 p-5 md:flex-row md:items-start">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-positive">
          <Sparkle size={19} weight="fill" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-ink-3">Your {name} in review</div>
          {make.isPending ? (
            <div className="mt-2 space-y-2">
              <Skeleton className="h-5 w-72" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
              <div className="text-[12px] text-ink-3">Writing on your server. Up to a minute if the model is asleep.</div>
            </div>
          ) : d.digest ? (
            <>
              <h2 className="mt-0.5 text-[18px] font-semibold tracking-tight text-ink">{d.digest.headline}</h2>
              <p className="mt-1.5 max-w-[78ch] text-[14px] leading-relaxed text-ink-2">{d.digest.body}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-ink-3">
                {d.digest.verified
                  ? <span className="inline-flex items-center gap-1 text-positive"><CheckCircle size={12} weight="fill" /> Figures checked against your data</span>
                  : <span className="inline-flex items-center gap-1 text-warn"><Warning size={12} weight="fill" /> Some figures couldn't be verified</span>}
                <button onClick={() => make.mutate()} className="hover:text-ink">Rewrite</button>
              </div>
            </>
          ) : (
            <div className="mt-1 flex flex-wrap items-center gap-3">
              <span className="text-[14px] text-ink-2">A short recap of what changed, written by your local model.</span>
              <Button variant="primary" onClick={() => make.mutate()}>Write my {name} recap</Button>
            </div>
          )}
          {make.isError && <div className="mt-2 text-[12px] text-negative">{(make.error as Error).message}</div>}
        </div>
      </div>
    </Panel>
  )
}

export function AskBox() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) nav(`/assistant?q=${encodeURIComponent(q.trim())}`) }}
          className="panel rise flex items-center gap-2 p-1.5 pl-4 md:col-span-12">
      <Sparkle size={17} weight="fill" className="shrink-0 text-positive" />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything, like “what did I spend at Costco this year?”"
             className="h-10 min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-3" aria-label="Ask Tally" />
      <button type="submit" className={cx('flex h-9 w-9 items-center justify-center rounded-full bg-ink text-page transition-opacity', !q.trim() && 'opacity-40')} aria-label="Ask">
        <ArrowRight size={16} weight="bold" />
      </button>
    </form>
  )
}

type AiStatus = {
  reachable: boolean; loaded?: boolean; model: string; error?: string; enriching: boolean
  pending: { names: number; categories: number }; done: { names: number; categories: number }
  calls_7d: { task: string; calls: number; failed: number; avg_ms: number }[]
}

const TASK_LABEL: Record<string, string> = {
  merchant_names: 'Merchant names', categorize: 'Categories', chat_plan: 'Chat: query', chat_answer: 'Chat: answer', digest: 'Monthly recap',
}

export function NotifyPanel() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['notify-status'], queryFn: api.notifyStatus })
  const preview = useQuery({ queryKey: ['brief-preview'], queryFn: api.briefPreview })
  const test = useMutation({ mutationFn: api.notifyTest, onSettled: () => qc.invalidateQueries({ queryKey: ['notify-status'] }) })
  const send = useMutation({ mutationFn: api.briefSend, onSettled: () => qc.invalidateQueries({ queryKey: ['notify-status'] }) })
  const s = q.data
  if (!s) return null
  return (
    <Panel className="mt-4">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink">
            <BellRinging size={16} weight="fill" className="text-positive" /> Phone alerts
          </h2>
          <div className="mt-0.5 text-[13px] text-ink-3">
            {s.enabled
              ? <>Through your own ntfy at <span className="font-mono text-[12px]">{s.url}</span> · {s.reachable ? 'reachable' : 'not reachable'}</>
              : <>Not set up. Add NTFY_URL and NTFY_TOPIC to the stack's .env, then subscribe to that topic in the ntfy app.</>}
          </div>
          {s.enabled && s.topic && (
            <div className="mt-2 rounded-lg bg-surface-2 px-3 py-2 text-[12px] text-ink-2">
              On your phone: install ntfy, add server <span className="font-mono">{s.url}</span>, subscribe to topic{' '}
              <span className="font-mono font-semibold text-ink">{s.topic}</span>. Anyone who knows that topic can read
              these messages, so keep it to yourself.
            </div>
          )}
        </div>
        {s.enabled && (
          <div className="flex gap-2">
            <Button onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? 'Sending…' : 'Send a test'}</Button>
            <Button onClick={() => send.mutate()} disabled={send.isPending}>{send.isPending ? 'Sending…' : 'Send this week now'}</Button>
          </div>
        )}
      </div>
      {preview.data && (
        <div className="mx-5 my-4 rounded-xl bg-surface-2 p-4">
          <div className="text-[12px] font-medium text-ink-3">This week's brief would say</div>
          <div className="mt-1 text-[14px] font-semibold text-ink">{preview.data.title}</div>
          <pre className="mt-1 whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-ink-2">{preview.data.body}</pre>
        </div>
      )}
      {!!s.recent?.length && (
        <div className="border-t border-line px-5 py-3 text-[12px] text-ink-3">
          Last sent: {s.recent.slice(0, 3).map((n) => `${n.title}${n.ok ? '' : ' (failed)'}`).join(' · ')}
        </div>
      )}
    </Panel>
  )
}

export function AiStatusPanel() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['ai-status'], queryFn: () => fetch('/api/ai/status').then((r) => r.json() as Promise<AiStatus>), refetchInterval: 10_000 })
  const run = useMutation({ mutationFn: () => fetch('/api/ai/enrich', { method: 'POST' }).then((r) => r.json()), onSuccess: () => qc.invalidateQueries() })
  const s = q.data
  if (!s) return null
  const pending = s.pending.names + s.pending.categories
  return (
    <Panel className="mt-6">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink"><Sparkle size={16} weight="fill" className="text-positive" /> Local AI</h2>
          <div className="mt-0.5 text-[13px] text-ink-3">
            <span className="font-mono text-[12px]">{s.model}</span> on your server · {s.reachable ? (s.loaded ? 'loaded' : 'asleep') : `offline (${s.error ?? 'unreachable'})`}
          </div>
        </div>
        <Button onClick={() => run.mutate()} disabled={!s.reachable || s.enriching || run.isPending || pending === 0}>
          {s.enriching ? 'Working…' : pending ? `Clean up ${pending} now` : 'All caught up'}
        </Button>
      </div>
      <div className="grid gap-3 px-5 py-4 sm:grid-cols-2">
        <div className="rounded-xl bg-surface-2 px-4 py-3">
          <div className="text-[12px] text-ink-3">Merchant names written</div>
          <div className="text-[18px] font-semibold text-ink tnum">{s.done.names}{s.pending.names > 0 && <span className="ml-2 text-[12px] font-normal text-ink-3">{s.pending.names} waiting</span>}</div>
        </div>
        <div className="rounded-xl bg-surface-2 px-4 py-3">
          <div className="text-[12px] text-ink-3">Uncertain categories decided</div>
          <div className="text-[18px] font-semibold text-ink tnum">{s.done.categories}{s.pending.categories > 0 && <span className="ml-2 text-[12px] font-normal text-ink-3">{s.pending.categories} waiting</span>}</div>
        </div>
      </div>
      {s.calls_7d.length > 0 && (
        <table className="mx-5 mb-5 w-[calc(100%-2.5rem)] text-[12px]">
          <thead><tr className="text-left text-ink-3"><th className="py-1 font-medium">Last 7 days</th><th className="py-1 text-right font-medium">Calls</th><th className="py-1 text-right font-medium">Failed</th><th className="py-1 text-right font-medium">Avg time</th></tr></thead>
          <tbody className="divide-y divide-line">
            {s.calls_7d.map((c) => (
              <tr key={c.task}><td className="py-1.5 text-ink">{TASK_LABEL[c.task] ?? c.task}</td><td className="py-1.5 text-right tnum text-ink">{c.calls}</td>
                <td className={cx('py-1.5 text-right tnum', c.failed ? 'text-negative' : 'text-ink-3')}>{c.failed}</td>
                <td className="py-1.5 text-right tnum text-ink-2">{(c.avg_ms / 1000).toFixed(1)}s</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="border-t border-line px-5 py-3 text-[12px] text-ink-3">
        The model only names payees and picks categories where Plaid was unsure. Your own edits always win. <Link to="/assistant" className="text-ink-2 underline underline-offset-2">Ask Tally a question</Link>
      </div>
    </Panel>
  )
}
