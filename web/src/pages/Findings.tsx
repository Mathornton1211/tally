import {
  ArrowCounterClockwise, Binoculars, CaretDown, Check, Copy, MagnifyingGlass, X,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Finding, type FindingsPayload } from '../api'
import {
  Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, Segmented, Skeleton,
} from '../components/ui'
import { fmtMonth, money0 } from '../lib/format'

type Status = 'open' | 'acted' | 'dismissed' | 'all'

const STATUSES: { value: Status; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'acted', label: 'Done' },
  { value: 'dismissed', label: 'Ignored' },
  { value: 'all', label: 'All' },
]

/**
 * How sure the finding is, said in words. The colour is a second signal and
 * never the only one -- "worth checking" has to read as a question with the
 * colour stripped out, because that is exactly what it is.
 */
const CONFIDENCE: Record<Finding['confidence'], { label: string; means: string; tone: string }> = {
  certain: {
    label: 'Certain',
    means: 'Arithmetic on figures the bank reported.',
    tone: 'border-line-strong text-ink',
  },
  likely: {
    label: 'Likely',
    means: 'Arithmetic plus one assumption, stated in the detail.',
    tone: 'border-line-strong text-ink-2',
  },
  worth_checking: {
    label: 'Worth checking',
    means: 'A question Tally cannot answer from the data alone.',
    tone: 'border-line text-ink-3',
  },
}

const KIND_LABEL: Record<string, string> = {
  price_creep: 'Price rise',
  long_running: 'Long-running',
  overlapping: 'Overlapping',
  annual_fee: 'Annual fee',
  expensive_balance: 'Interest',
  recurring_fee: 'Repeat fee',
}

/** Evidence keys are snake_case from the API. Read them out loud. */
function prettyKey(k: string) {
  return k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

function evidenceValue(v: unknown): string {
  if (Array.isArray(v)) return v.join(', ')
  if (v == null) return '—'
  return String(v)
}

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => { setDone(true); setTimeout(() => setDone(false), 1800) },
          () => { /* clipboard is blocked in some contexts; the text is on screen anyway */ },
        )
      }}
      className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] text-ink-2 hover:bg-hover hover:text-ink"
    >
      {done ? <Check size={11} weight="bold" /> : <Copy size={11} />}
      {done ? 'Copied' : label}
    </button>
  )
}

/** A script is many lines and whitespace carries meaning, so it is preserved. */
function Script({ text, title }: { text: string; title: string }) {
  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="text-[12px] font-medium text-ink-3">{title}</span>
        <CopyButton text={text} />
      </div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-ink-2">
        {text}
      </pre>
    </div>
  )
}

function ActedForm({ finding, onDone }: { finding: Finding; onDone: () => void }) {
  const qc = useQueryClient()
  const [saved, setSaved] = useState('')
  const [note, setNote] = useState('')
  const act = useMutation({
    mutationFn: () => api.updateFinding(finding.id, {
      status: 'acted',
      saved: saved ? Number(saved) : null,
      note: note.trim() || null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['findings'] }); onDone() },
  })
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); act.mutate() }}
      className="mt-3 rounded-xl bg-surface-2 p-3"
    >
      <div className="text-[12px] font-medium text-ink">What did it come to?</div>
      <p className="mt-0.5 max-w-[60ch] text-[12px] text-ink-3">
        Optional, and the only way this app can ever show what it actually saved rather than what it
        estimated.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <span className="text-[13px] text-ink-3">$</span>
          <input
            inputMode="decimal"
            value={saved}
            placeholder={finding.annual_saving ? String(Number(finding.annual_saving)) : '0'}
            onChange={(e) => setSaved(e.target.value.replace(/[^\d.]/g, ''))}
            aria-label="Amount saved a year"
            className="h-9 w-24 rounded-lg border border-line-strong bg-surface px-2 text-[13px] tnum text-ink outline-none"
          />
          <span className="text-[13px] text-ink-3">a year</span>
        </div>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="What happened (optional)"
          aria-label="Note"
          className="h-9 min-w-40 flex-1 rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-ink outline-none"
        />
        <Button variant="primary" type="submit" disabled={act.isPending}>
          {act.isPending ? 'Saving…' : 'Done'}
        </Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
      <ErrorNote error={act.error} />
    </form>
  )
}

function FindingCard({ f }: { f: Finding }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [acting, setActing] = useState(false)
  const invalidate = () => qc.invalidateQueries({ queryKey: ['findings'] })
  const set = useMutation({
    mutationFn: (status: string) => api.updateFinding(f.id, { status }),
    onSuccess: invalidate,
  })

  const conf = CONFIDENCE[f.confidence]
  const evidence = Object.entries(f.evidence ?? {})
  const resolved = f.status !== 'open'

  return (
    <Panel className={cx('flex flex-col', resolved && 'opacity-75')}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">
              {KIND_LABEL[f.kind] ?? f.kind.replace(/_/g, ' ')}
            </span>
            <span className={cx('rounded-full border px-2 py-0.5 text-[11px]', conf.tone)} title={conf.means}>
              {conf.label}
            </span>
            {f.status === 'acted' && (
              <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] text-positive">
                <Check size={10} weight="bold" /> Done
              </span>
            )}
            {f.status === 'dismissed' && (
              <span className="rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-3">Ignored</span>
            )}
          </div>
          <h3 className="mt-2 text-[16px] font-semibold tracking-tight text-ink">{f.title}</h3>
          <p className="mt-1 max-w-[70ch] text-[13px] leading-relaxed text-ink-2">{f.detail}</p>
        </div>

        {f.annual_saving != null && (
          <div className="shrink-0 text-right">
            <div className="text-[20px] font-semibold tracking-tight text-ink">
              <Money value={Number(f.annual_saving)} size="lg" />
            </div>
            <div className="text-[11px] text-ink-3">a year</div>
          </div>
        )}
      </div>

      <div className="px-5 pt-3 text-[11px] text-ink-3">
        {conf.means}
        {' · '}
        {f.times_seen > 1
          ? `Found ${f.times_seen} times since ${fmtMonth(f.first_seen, true)}`
          : `First found ${fmtMonth(f.first_seen, true)}`}
        {f.account_name && ` · ${f.account_name}${f.account_mask ? ` ··${f.account_mask}` : ''}`}
      </div>

      {(evidence.length > 0 || f.action) && (
        <button
          onClick={() => setOpen(!open)}
          className="mx-5 mt-3 inline-flex w-fit items-center gap-1 text-[12px] text-ink-2 hover:text-ink"
        >
          <CaretDown size={12} className={cx('transition-transform', open && 'rotate-180')} />
          {open ? 'Hide the working' : f.action ? 'What this is based on, and what to say' : 'What this is based on'}
        </button>
      )}

      {open && (
        <div className="px-5 pb-1 pt-3">
          {evidence.length > 0 && (
            <dl className="divide-y divide-line rounded-xl border border-line">
              {evidence.map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
                  <dt className="text-[12px] text-ink-3">{prettyKey(k)}</dt>
                  <dd className="text-right text-[12px] tnum text-ink">{evidenceValue(v)}</dd>
                </div>
              ))}
            </dl>
          )}
          {f.action && <Script text={f.action} title="What to say" />}
        </div>
      )}

      {acting ? (
        <div className="px-5 pb-4"><ActedForm finding={f} onDone={() => setActing(false)} /></div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          {f.status === 'open' ? (
            <>
              <Button variant="primary" onClick={() => setActing(true)}>
                <Check size={13} weight="bold" /> I did this
              </Button>
              <Button onClick={() => set.mutate('dismissed')} disabled={set.isPending}>
                <X size={13} /> Not worth it
              </Button>
            </>
          ) : (
            <Button onClick={() => set.mutate('open')} disabled={set.isPending}>
              <ArrowCounterClockwise size={13} /> Put it back
            </Button>
          )}
          <ErrorNote error={set.error} />
        </div>
      )}
    </Panel>
  )
}

export default function Findings() {
  const [status, setStatus] = useState<Status>('open')
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['findings', status], queryFn: () => api.findings(status) })
  const scan = useMutation({
    mutationFn: api.scanFindings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['findings'] }),
  })
  const d: FindingsPayload | undefined = q.data

  return (
    <>
      <PageHeader
        title="Findings"
        sub="What Tally turned up while nobody was looking. The same rules run after every sync, and what they find stays on this list."
      >
        <Segmented value={status} options={STATUSES} onChange={setStatus} />
        <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
          <MagnifyingGlass size={13} /> {scan.isPending ? 'Looking…' : 'Check again'}
        </Button>
      </PageHeader>

      <ErrorNote error={q.error} />

      {!d ? (
        <div className="grid gap-4">
          <Skeleton className="h-20 rounded-[18px]" />
          <Skeleton className="h-48 rounded-[18px]" />
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {[
              { label: 'On the table', node: <Money value={Number(d.on_the_table)} size="lg" />,
                sub: 'a year, if every open one were acted on' },
              { label: 'Still open', node: <span>{d.open}</span>,
                sub: d.open === 1 ? 'thing to look at' : 'things to look at' },
              { label: 'Acted on', node: <span>{d.acted}</span>,
                sub: Number(d.actually_saved) > 0
                  ? `${money0(Number(d.actually_saved))} recorded as saved`
                  : 'nothing recorded yet' },
            ].map((t, i) => (
              <div key={t.label} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">{t.node}</div>
                <div className="mt-0.5 text-[11px] text-ink-3">{t.sub}</div>
              </div>
            ))}
          </div>

          {d.findings.length === 0 ? (
            <Panel>
              <Empty
                title={status === 'open' ? 'Nothing open right now' : 'Nothing here'}
                icon={<Binoculars size={20} />}
              >
                These rules run after every sync and what they find accumulates, so an empty list today is
                not a permanent answer — a price rise needs a few charges before it is visible, and a repeat
                fee needs to have repeated. Check again once there is more history.
              </Empty>
            </Panel>
          ) : (
            <div className="grid gap-4">
              {d.findings.map((f) => <FindingCard key={f.id} f={f} />)}
            </div>
          )}

          <p className="mt-4 max-w-[70ch] px-1 text-[11px] leading-relaxed text-ink-3">
            Every figure above is arithmetic on something your bank reported — no averages from elsewhere and
            no estimate of what a typical household spends. Where a conclusion needs an assumption, the
            assumption is written into the detail rather than hidden in the number.
          </p>
        </>
      )}
    </>
  )
}
