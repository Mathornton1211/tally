import { CurrencyDollar, MagnifyingGlass, Sparkle, Tag as TagIcon, TextT, X } from '@phosphor-icons/react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type SearchResult, type Txn } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { CategoryIcon } from '../components/icons'
import { TxnDrawer, TxnRow } from '../components/Transactions'
import { Button, Empty, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtMonth, fmtShort, money, money0, moneyCompact } from '../lib/format'

const EXAMPLES = [
  'costco last year',
  'groceries over $50',
  'netflix',
  'how much did I spend on dining in March',
  'income last month',
]

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const tidy = (s: string) => s.replace(/\s{2,}/g, ' ').replace(/\s+([,.!?])/g, '$1').trim()

/** Remove whole words from the question, so a chip can undo what it matched. */
function stripWords(q: string, words: string[]) {
  let out = q
  for (const w of words) {
    const t = w.trim()
    if (!t) continue
    out = out.replace(new RegExp(`"?\\b${esc(t)}\\b"?`, 'ig'), ' ')
  }
  return tidy(out)
}

const AMOUNT_RE =
  /\b(over|above|more than|at least|under|below|less than|at most|between)\s*\$?\d[\d,.]*(\s*(and|-|to)\s*\$?\d[\d,.]*)?/ig

type Chip = { key: string; icon: typeof TextT; label: string; value: string; next: string }

/**
 * What the question was understood to mean. This is the point of the page: a
 * wrong reading has to be visible and undoable, not silently folded into a
 * total that looks authoritative.
 */
function chipsFor(r: SearchResult, labels: Record<string, string>): Chip[] {
  const q = r.question
  const f = r.filters
  const out: Chip[] = []

  if (f.merchant) {
    out.push({ key: 'merchant', icon: MagnifyingGlass, label: 'at', value: f.merchant,
               next: stripWords(q, f.merchant.split(/\s+/)) })
  }
  if (f.category) {
    const label = labels[f.category] ?? f.category
    out.push({ key: 'category', icon: TextT, label: 'in', value: label,
               next: stripWords(q, [label, ...label.split(/[\s&]+/), f.category.replace(/_/g, ' ')]) })
  }
  if (f.tag) {
    out.push({ key: 'tag', icon: TagIcon, label: 'tagged', value: f.tag, next: stripWords(q, [f.tag]) })
  }
  if (f.start || f.end) {
    const value = f.when
      ?? [f.start && fmtShort(f.start), f.end && fmtShort(f.end)].filter(Boolean).join(' – ')
    out.push({ key: 'date', icon: TextT, label: 'during', value,
               next: f.when ? stripWords(q, [f.when, ...f.when.split(/\s+/)]) : tidy(q.replace(/\b20\d{2}\b/g, ' ')) })
  }
  if (f.min_amount != null || f.max_amount != null) {
    const value = f.min_amount != null && f.max_amount != null
      ? `${money0(Number(f.min_amount))} – ${money0(Number(f.max_amount))}`
      : f.min_amount != null ? `over ${money0(Number(f.min_amount))}` : `under ${money0(Number(f.max_amount))}`
    out.push({ key: 'amount', icon: CurrencyDollar, label: 'amount', value,
               next: tidy(q.replace(AMOUNT_RE, ' ')) })
  }
  if (f.kind) {
    out.push({ key: 'kind', icon: TextT, label: 'only', value: f.kind,
               next: stripWords(q, ['income', 'earned', 'earn', 'deposit', 'paid me']) })
  }
  return out
}

function Months({ months }: { months: SearchResult['months'] }) {
  const t = useChartTheme()
  const option = useMemo(() => ({
    animationDuration: 400,
    grid: { left: 4, right: 8, top: 12, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category', data: months.map((m) => fmtMonth(m.month)), axisTick: { show: false },
      axisLine: { lineStyle: { color: t.grid } },
      axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11 },
    },
    yAxis: {
      type: 'value', splitNumber: 3,
      axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact },
      splitLine: { lineStyle: { color: t.grid } },
    },
    tooltip: {
      ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: t.grid + '80' } },
      formatter: (ps: { dataIndex: number }[]) => {
        const m = months[ps[0].dataIndex]
        return `<div style="color:${t.ink3};margin-bottom:4px">${fmtMonth(m.month, true)}</div>`
          + `<b style="font-variant-numeric:tabular-nums">${money(Number(m.spent))}</b>`
      },
    },
    series: [{
      name: 'Spent', type: 'bar', data: months.map((m) => Number(m.spent)),
      barMaxWidth: 22, itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] },
    }],
  }), [months, t])
  return <Chart option={option} height={170} ariaLabel="Matching spending by month" />
}

export default function Search() {
  const [params, setParams] = useSearchParams()
  const question = params.get('q') ?? ''
  const [text, setText] = useState(question)
  const [open, setOpen] = useState<Txn | null>(null)

  // The sidebar box navigates here, so the input follows the URL rather than
  // the other way round.
  useEffect(() => { setText(question) }, [question])

  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 5 * 60_000 })
  const labels = useMemo(
    () => Object.fromEntries((meta.data?.categories ?? []).map((c) => [c.key, c.label])),
    [meta.data],
  )

  const q = useQuery({
    queryKey: ['search', question],
    queryFn: () => api.search(question),
    enabled: question.trim().length > 0,
    placeholderData: keepPreviousData,
  })
  const d = q.data

  const ask = (next: string) => {
    const v = next.trim()
    if (v) setParams({ q: v })
    else setParams({})
  }

  return (
    <>
      <PageHeader title="Search" sub="Ask it the way you would say it. Tally shows what it understood." />

      <form onSubmit={(e) => { e.preventDefault(); ask(text) }} className="relative mb-4">
        <MagnifyingGlass size={16} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-3" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus={!question}
          placeholder="how much did I spend at Costco last year"
          aria-label="Ask about your money"
          className="h-12 w-full rounded-full border border-line bg-surface pl-11 pr-24 text-[15px] text-ink outline-none placeholder:text-ink-3 focus:border-line-strong"
        />
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
          <Button variant="primary" type="submit" disabled={!text.trim()}>Ask</Button>
        </div>
      </form>

      <ErrorNote error={q.error} />

      {!question ? (
        <Panel>
          <Empty title="Ask about your money" icon={<MagnifyingGlass size={20} />}>
            Dates, amounts, merchants, categories and tags are all read straight out of the sentence — no model
            needed, and no filters to build.
          </Empty>
          <div className="flex flex-wrap justify-center gap-2 px-6 pb-8">
            {EXAMPLES.map((e) => (
              <button key={e} onClick={() => ask(e)}
                      className="rounded-full border border-line-strong px-3 py-1.5 text-[13px] text-ink-2 hover:bg-hover hover:text-ink">
                {e}
              </button>
            ))}
          </div>
        </Panel>
      ) : !d ? (
        <div className="grid gap-4"><Skeleton className="h-20 rounded-[18px]" /><Skeleton className="h-64 rounded-[18px]" /></div>
      ) : (
        <>
          <Panel className="mb-4">
            <div className="flex flex-wrap items-center gap-2 px-5 py-4">
              <span className="text-[12px] text-ink-3">Understood as</span>
              {chipsFor(d, labels).map((c) => {
                const canDrop = c.next && c.next !== d.question
                return (
                  <span key={c.key}
                        className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface-2 py-1 pl-2.5 pr-1.5 text-[13px] text-ink">
                    <span className="text-ink-3">{c.label}</span>
                    <b className="font-medium">{c.value}</b>
                    {canDrop && (
                      <button onClick={() => ask(c.next)} aria-label={`Drop ${c.label} ${c.value}`}
                              className="rounded-full p-0.5 text-ink-3 hover:bg-hover hover:text-ink">
                        <X size={11} weight="bold" />
                      </button>
                    )}
                  </span>
                )
              })}
              {chipsFor(d, labels).length === 0 && (
                <span className="text-[13px] text-ink-2">nothing in particular — showing everything</span>
              )}
              <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-ink-3">
                {d.filters.by === 'model'
                  ? <><Sparkle size={11} /> read by the local model</>
                  : <><TextT size={11} /> read from the words</>}
              </span>
            </div>
          </Panel>

          {d.count === 0 ? (
            <Panel>
              <Empty title="Nothing matched that" icon={<MagnifyingGlass size={20} />}>
                Try dropping part of the question with the × above, or one of these.
              </Empty>
              <div className="flex flex-wrap justify-center gap-2 px-6 pb-8">
                {EXAMPLES.slice(0, 3).map((e) => (
                  <button key={e} onClick={() => ask(e)}
                          className="rounded-full border border-line-strong px-3 py-1.5 text-[13px] text-ink-2 hover:bg-hover hover:text-ink">
                    {e}
                  </button>
                ))}
              </div>
            </Panel>
          ) : (
            <>
              <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: 'Transactions', node: <span className="tnum">{d.count}</span> },
                  { label: 'Spent', node: <Money value={Number(d.spent)} size="lg" /> },
                  { label: 'Average', node: <Money value={Number(d.average)} size="lg" /> },
                  { label: 'Came in', node: <Money value={Number(d.earned)} size="lg" /> },
                ].map((t, i) => (
                  <div key={t.label} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                    <div className="text-[12px] text-ink-3">{t.label}</div>
                    <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">{t.node}</div>
                  </div>
                ))}
              </div>

              <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
                <Panel>
                  <PanelHeader
                    title="Matches"
                    sub={d.first && d.last ? `${fmtShort(d.first)} – ${fmtShort(d.last)}` : undefined}
                    action={d.rows.length < d.count
                      ? <span className="text-[12px] text-ink-3">showing {d.rows.length} of {d.count}</span>
                      : undefined}
                  />
                  <ul className="mt-2 divide-y divide-line">
                    {d.rows.map((t) => (
                      <li key={t.id}><TxnRow t={t} onOpen={setOpen} compact /></li>
                    ))}
                  </ul>
                </Panel>

                <div className="grid content-start gap-4">
                  {d.months.length > 1 && (
                    <Panel>
                      <PanelHeader title="By month" />
                      <div className="px-3 pb-3 pt-2"><Months months={d.months} /></div>
                    </Panel>
                  )}
                  {d.merchants.length > 1 && (
                    <Panel>
                      <PanelHeader title="Where it went" />
                      <ul className="mt-2 divide-y divide-line">
                        {d.merchants.map((m) => (
                          <li key={m.name} className="flex items-center gap-3 px-5 py-2.5">
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-[13px] text-ink">{m.name}</div>
                              <div className="text-[11px] text-ink-3">{m.count} {m.count === 1 ? 'time' : 'times'}</div>
                            </div>
                            <Money value={Number(m.total)} className="text-[13px] text-ink" />
                          </li>
                        ))}
                      </ul>
                    </Panel>
                  )}
                  {d.filters.category && (
                    <div className="flex items-center gap-2 px-1 text-[12px] text-ink-3">
                      <CategoryIcon name={meta.data?.categories.find((c) => c.key === d.filters.category)?.icon ?? 'DotsThree'} size={12} />
                      Only {labels[d.filters.category] ?? d.filters.category} is counted here.
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </>
      )}

      <TxnDrawer txn={open} onClose={() => setOpen(null)} />
    </>
  )
}
