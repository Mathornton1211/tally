import { CaretRight, Copy, ShieldWarning, TrendUp, Warning } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Account, type Dashboard as D, type Txn } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { AskBox, DigestCard } from '../components/AiBits'
import { PlanStrip } from '../components/PlanStrip'
import { CategoryIcon } from '../components/icons'
import { TxnDrawer, TxnRow } from '../components/Transactions'
import { cx, Delta, Empty, ErrorNote, MerchantAvatar, Money, Panel, PanelHeader, Skeleton } from '../components/ui'
import { accountTypeLabel, fmtMonth, money, money0, moneyCompact, parseDate, relativeDays } from '../lib/format'

/**
 * One point per week, each the average of that week's daily values, counting
 * back from today. Balances saw-tooth between paydays and card payments; an
 * average shows the trend instead of the pay cycle.
 */
export function weekly<T extends object>(series: T[]): T[] {
  const out: T[] = []
  for (let end = series.length - 1; end >= 0; end -= 7) {
    const win = series.slice(Math.max(0, end - 6), end + 1)
    const avg = { ...series[end] } as Record<string, unknown>
    for (const k of Object.keys(avg)) {
      if (k === 'date') continue
      avg[k] = win.reduce((s, p) => s + Number((p as Record<string, unknown>)[k]), 0) / win.length
    }
    out.unshift(avg as T)
  }
  return out
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function SpendingPace({ d }: { d: D }) {
  const t = useChartTheme()
  const s = d.spending
  const today = parseDate(d.today)
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
  const diff = s.month_to_date - s.last_month_same_point

  const option = useMemo(() => {
    const days = Array.from({ length: Math.max(daysInMonth, s.last_month.length) }, (_, i) => i + 1)
    const monthName = today.toLocaleDateString('en-US', { month: 'short' })
    const lastName = new Date(today.getFullYear(), today.getMonth() - 1, 1).toLocaleDateString('en-US', { month: 'short' })
    return {
      animationDuration: 600,
      grid: { left: 4, right: 12, top: 16, bottom: 24, containLabel: true },
      xAxis: {
        type: 'category', data: days, boundaryGap: false,
        axisLine: { lineStyle: { color: t.grid } }, axisTick: { show: false },
        axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, interval: (i: number) => [0, 9, 19, daysInMonth - 1].includes(i), formatter: (v: string) => (Number(v) <= daysInMonth ? `${monthName} ${v}` : '') },
      },
      yAxis: {
        type: 'value', splitNumber: 3,
        axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact },
        splitLine: { lineStyle: { color: t.grid } },
      },
      tooltip: {
        ...tooltipBase(t), trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: t.line } },
        formatter: (ps: { dataIndex: number; seriesName: string; value: number | null; color: string }[]) => {
          const day = ps[0].dataIndex + 1
          const rows = ps.filter((p) => p.value != null).map((p) =>
            `<div style="display:flex;gap:16px;justify-content:space-between;align-items:center"><span style="display:flex;gap:6px;align-items:center"><span style="width:8px;height:8px;border-radius:9px;background:${p.color}"></span>${p.seriesName}</span><b style="font-variant-numeric:tabular-nums">${money0(p.value)}</b></div>`).join('')
          return `<div style="color:${t.ink3};margin-bottom:4px">Day ${day}</div>${rows}`
        },
      },
      series: [
        {
          name: lastName, type: 'line', data: s.last_month, showSymbol: false, smooth: 0.25,
          lineStyle: { width: 2, color: t.compare }, itemStyle: { color: t.compare }, z: 1,
        },
        {
          name: monthName, type: 'line', data: s.this_month, smooth: 0.25,
          showSymbol: false, lineStyle: { width: 2.5, color: t.s1 }, itemStyle: { color: t.s1 }, z: 2,
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: t.s1 + '2e' }, { offset: 1, color: t.s1 + '00' }] } },
          markPoint: undefined,
        },
        {
          // Today's endpoint: 8px dot with a surface ring so it sits on the line.
          type: 'line', data: s.this_month.map((v, i) => (i === s.this_month.length - 1 ? v : null)),
          symbol: 'circle', symbolSize: 9, lineStyle: { opacity: 0 }, tooltip: { show: false },
          itemStyle: { color: t.s1, borderColor: t.surface, borderWidth: 2 }, z: 3, silent: true,
        },
      ],
    }
  }, [d, t]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Panel className="md:col-span-8">
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 pt-5">
        <div>
          <div className="text-[13px] font-medium text-ink-3">Spent this month</div>
          <div className="mt-1 text-[40px] font-semibold leading-none tracking-tight text-ink">
            <Money value={s.month_to_date} size="hero" />
          </div>
          <div className="mt-2 text-[13px] text-ink-2">
            {Math.abs(diff) < 1 ? 'Right on pace with last month'
              : <><span className={cx('font-medium', diff > 0 ? 'text-negative' : 'text-positive')}>{money0(Math.abs(diff))} {diff > 0 ? 'more' : 'less'}</span> than this point last month</>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5 text-[12px] text-ink-2">
          <span className="flex items-center gap-1.5"><span className="h-[3px] w-4 rounded-full" style={{ background: 'var(--series-1)' }} />This month</span>
          <span className="flex items-center gap-1.5"><span className="h-[3px] w-4 rounded-full" style={{ background: 'var(--series-compare)' }} />Last month · {money0(s.last_month_total)}</span>
        </div>
      </div>
      <div className="px-3 pb-2">
        <Chart option={option} height={230} ariaLabel={`Cumulative spending this month ${money(s.month_to_date)} versus ${money(s.last_month_same_point)} at the same point last month`} />
      </div>
    </Panel>
  )
}

function NetWorthCard({ d }: { d: D }) {
  const t = useChartTheme()
  const nw = d.net_worth
  const option = useMemo(() => {
    const pts = weekly(nw.series)
    return {
    animationDuration: 600,
    grid: { left: 0, right: 0, top: 6, bottom: 0 },
    xAxis: { type: 'category', show: false, boundaryGap: false, data: pts.map((p) => p.date) },
    yAxis: { type: 'value', show: false, scale: true },
    tooltip: {
      ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: t.line } },
      formatter: (ps: { name: string; value: number }[]) =>
        `<div style="color:${t.ink3}">${parseDate(ps[0].name).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div><b style="font-variant-numeric:tabular-nums">${money(ps[0].value)}</b>`,
    },
    series: [{
      type: 'line', data: pts.map((p) => Number(p.value)), showSymbol: false, smooth: 0.3,
      lineStyle: { width: 2, color: t.s1 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: t.s1 + '30' }, { offset: 1, color: t.s1 + '00' }] } },
    }],
    }
  }, [nw, t])

  return (
    <Panel className="flex flex-col md:col-span-4" style={{ animationDelay: '60ms' }}>
      <PanelHeader title="Net worth" to="/net-worth" />
      <div className="px-5 pt-2">
        <div className="text-[28px] font-semibold tracking-tight text-ink"><Money value={Number(nw.current)} size="lg" /></div>
        <div className="mt-1"><Delta value={Number(nw.current)} previous={nw.thirty_days_ago == null ? null : Number(nw.thirty_days_ago)} label="30 days ago" /></div>
      </div>
      <div className="mt-auto px-1 pb-1 pt-3">
        <Chart option={option} height={110} ariaLabel="Net worth over the last 90 days" />
      </div>
    </Panel>
  )
}

function Upcoming({ d }: { d: D }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const iconFor = (key: string) => meta.data?.categories.find((c) => c.key === key)?.icon ?? 'Repeat'
  const items = d.upcoming.slice(0, 6)
  const total = d.upcoming.reduce((s, x) => s + Number(x.last_amount), 0)
  return (
    <Panel className="md:col-span-4" style={{ animationDelay: '120ms' }}>
      <PanelHeader title="Upcoming bills" sub={items.length ? `${money0(total)} in the next 30 days` : undefined} to="/recurring" />
      {items.length === 0 ? <Empty title="Nothing due soon">Recurring charges show up here once Tally has seen them a few times.</Empty> : (
        <ul className="mt-3 divide-y divide-line pb-2">
          {items.map((s) => (
            <li key={s.key + s.account_id} className="flex items-center gap-3 px-5 py-2.5">
              <MerchantAvatar logo={s.logo_url} icon={iconFor(s.category)} name={s.name} size={32} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-medium text-ink">{s.name}</div>
                <div className="text-[12px] text-ink-3">{relativeDays(s.next_date)}</div>
              </div>
              <Money value={Number(s.last_amount)} className="text-[14px] font-medium text-ink" />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function TopCategories({ d }: { d: D }) {
  const cats = d.categories.slice(0, 6)
  const max = Math.max(...cats.map((c) => Number(c.amount)), 1)
  return (
    <Panel className="md:col-span-8" style={{ animationDelay: '160ms' }}>
      <PanelHeader title="Where it went" sub={`${fmtMonth(d.today, true)} so far`} to="/spending" />
      {cats.length === 0 ? <Empty title="No spending yet this month" /> : (
        <ul className="mt-3 px-5 pb-5">
          {cats.map((c) => {
            const amount = Number(c.amount)
            const prev = c.last_month_same_point == null ? null : Number(c.last_month_same_point)
            return (
              <li key={c.key}>
                <Link to={`/transactions?range=mtd&category=${c.key}`} className="group -mx-2 grid grid-cols-[32px_1fr_auto] items-center gap-3 rounded-xl px-2 py-2 hover:bg-hover">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-hover text-ink-2 group-hover:bg-surface">
                    <CategoryIcon name={c.icon} size={16} />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[14px] font-medium text-ink">{c.label}</span>
                      <span className="hidden text-[12px] sm:inline">
                        {prev ? <Delta value={amount} previous={prev} invert /> : <span className="text-ink-3">New this month</span>}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-hover">
                      <div className="h-full rounded-full" style={{ width: `${(amount / max) * 100}%`, background: 'var(--series-1)' }} />
                    </div>
                  </div>
                  <Money value={amount} className="w-24 text-right text-[14px] font-medium text-ink" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}

function HeadsUp({ d, rec }: { d: D; rec?: { price_changes: number; duplicates: number } }) {
  const items: { icon: React.ReactNode; title: string; body: string; to: string; tone: 'warn' | 'neutral' | 'bad' }[] = []
  if (d.alerts?.urgent) {
    items.push({ icon: <ShieldWarning size={18} weight="fill" />, tone: 'bad', to: '/alerts',
      title: `${d.alerts.urgent} alert${d.alerts.urgent > 1 ? 's' : ''} to review`,
      body: d.alerts.top ?? 'Unusual activity found' })
  }
  if (Number(d.fees.last_30) > 0) {
    items.push({ icon: <Warning size={18} weight="fill" />, tone: 'warn', to: '/fees',
      title: `${money(Number(d.fees.last_30))} in fees and interest`,
      body: `${d.fees.count_30} charge${d.fees.count_30 === 1 ? '' : 's'} in the last 30 days · ${money0(Number(d.fees.ytd))} this year` })
  }
  if (rec?.duplicates) {
    items.push({ icon: <Copy size={18} weight="bold" />, tone: 'neutral', to: '/recurring',
      title: `${rec.duplicates} subscription${rec.duplicates > 1 ? 's' : ''} billed twice`, body: 'Same service charged on two different cards' })
  }
  if (rec?.price_changes) {
    items.push({ icon: <TrendUp size={18} weight="bold" />, tone: 'neutral', to: '/recurring',
      title: `${rec.price_changes} price increase${rec.price_changes > 1 ? 's' : ''}`, body: 'A subscription now costs more than it used to' })
  }
  if (!items.length) return null
  return (
    <div className="grid gap-3 md:col-span-12 md:grid-cols-3">
      {items.slice(0, 3).map((it, i) => (
        <Link key={i} to={it.to} className="panel rise group flex items-center gap-3 p-4 transition-colors hover:bg-hover" style={{ animationDelay: `${200 + i * 50}ms` }}>
          <div className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-full', it.tone === 'warn' ? 'bg-warn-soft text-warn' : it.tone === 'bad' ? 'bg-bad-soft text-negative' : 'bg-hover text-ink-2')}>
            {it.icon}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-semibold text-ink">{it.title}</div>
            <div className="truncate text-[12px] text-ink-3">{it.body}</div>
          </div>
          <CaretRight size={14} className="text-ink-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
      ))}
    </div>
  )
}

const GROUP_ORDER = ['depository', 'credit', 'loan', 'investment', 'other']

function Accounts({ d }: { d: D }) {
  const groups = GROUP_ORDER.map((type) => {
    const accts = d.accounts.filter((a) => a.type === type)
    return { type, accts, total: accts.reduce((s, a) => s + Number(a.current_balance || 0), 0) }
  }).filter((g) => g.accts.length)
  const [open, setOpen] = useState<string | null>('depository')

  return (
    <Panel className="md:col-span-5" style={{ animationDelay: '240ms' }}>
      <PanelHeader title="Accounts" to="/accounts" />
      <div className="mt-3 pb-2">
        {groups.map((g) => (
          <div key={g.type} className="border-t border-line first:border-t-0">
            <button onClick={() => setOpen(open === g.type ? null : g.type)} className="flex w-full items-center justify-between px-5 py-3 hover:bg-hover">
              <span className="flex items-center gap-2 text-[14px] font-medium text-ink">
                <CaretRight size={12} weight="bold" className={cx('text-ink-3 transition-transform', open === g.type && 'rotate-90')} />
                {accountTypeLabel[g.type]}
                <span className="text-[12px] font-normal text-ink-3">{g.accts.length}</span>
              </span>
              <Money value={(g.type === 'credit' || g.type === 'loan' ? -1 : 1) * g.total} className="text-[14px] font-semibold text-ink" />
            </button>
            {open === g.type && (
              <ul className="pb-2">
                {g.accts.map((a: Account) => (
                  <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-1.5 pl-10">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] text-ink">{a.name}{a.mask && <span className="text-ink-3"> ··{a.mask}</span>}</div>
                      <div className="truncate text-[12px] text-ink-3">{a.institution}</div>
                    </div>
                    <div className="text-right">
                      <Money value={Number(a.current_balance || 0)} className="text-[13px] text-ink" />
                      {a.credit_limit && <div className="text-[11px] text-ink-3">{Math.round((Number(a.current_balance || 0) / Number(a.credit_limit)) * 100)}% of {money0(Number(a.credit_limit))}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </Panel>
  )
}

function Recent({ d, onOpen }: { d: D; onOpen: (t: Txn) => void }) {
  return (
    <Panel className="md:col-span-7" style={{ animationDelay: '280ms' }}>
      <PanelHeader title="Recent transactions" to="/transactions" />
      <div className="mt-2 divide-y divide-line pb-2">
        {d.recent.map((t) => <TxnRow key={t.id} t={t} onOpen={onOpen} compact />)}
      </div>
    </Panel>
  )
}

function Loading() {
  return (
    <div className="grid gap-4 md:grid-cols-12">
      <Skeleton className="h-[340px] rounded-[18px] md:col-span-8" />
      <Skeleton className="h-[340px] rounded-[18px] md:col-span-4" />
      <Skeleton className="h-[72px] rounded-[18px] md:col-span-12" />
      <Skeleton className="h-[320px] rounded-[18px] md:col-span-4" />
      <Skeleton className="h-[320px] rounded-[18px] md:col-span-8" />
    </div>
  )
}

const SETUP_DISMISSED = 'tally.setup-dismissed'

/**
 * One line, only while the basics are missing, and dismissible for good.
 * A dashboard full of correct numbers that mean nothing is the problem this
 * points at; nagging about it forever would be a second problem.
 */
function SetupStrip() {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(SETUP_DISMISSED) === '1'
    } catch {
      return false
    }
  })
  const q = useQuery({ queryKey: ['setup'], queryFn: api.setupState, staleTime: 60_000 })
  if (hidden || !q.data?.show_welcome) return null

  const dismiss = () => {
    try {
      localStorage.setItem(SETUP_DISMISSED, '1')
    } catch { /* a preference that cannot be saved still applies for this visit */ }
    setHidden(true)
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-line bg-accent-soft px-4 py-3">
      <span className="text-[13px] text-ink">
        Tally is {q.data.done} of {q.data.total} set up.
      </span>
      <Link to="/welcome" className="text-[13px] font-medium text-ink underline decoration-line-strong">
        Finish setting it up
      </Link>
      <button onClick={dismiss} className="ml-auto text-[12px] text-ink-3 hover:text-ink">
        Not now
      </button>
    </div>
  )
}

/** One line, and only when there is something waiting. The queue itself lives
 *  at /review; this is just the nudge that makes somebody open it. */
function ReviewStrip() {
  const q = useQuery({ queryKey: ['review', '45'], queryFn: () => api.reviewQueue(45), staleTime: 60_000 })
  const n = q.data?.total ?? 0
  if (!n) return null
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-line bg-surface px-4 py-3">
      <span className="text-[13px] text-ink">
        {n} {n === 1 ? 'charge needs' : 'charges need'} a quick look.
      </span>
      <Link to="/review" className="text-[13px] font-medium text-ink underline decoration-line-strong">
        Review them
      </Link>
    </div>
  )
}

export default function Dashboard() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })
  const rec = useQuery({ queryKey: ['recurring'], queryFn: api.recurring })
  const [open, setOpen] = useState<Txn | null>(null)
  // Whoever is actually looking. The greeting was hardcoded to the first
  // owner's name, which is wrong the moment a second person signs in.
  const who = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 60_000 })
  const me = who.data?.people.find((p) => p.id === who.data?.me)?.name
  const d = q.data

  return (
    <>
      <SetupStrip />
      <ReviewStrip />
      <div className="mb-6">
        <h1 className="text-[26px] font-semibold tracking-tight text-ink">{greeting()}{me ? `, ${me}` : ''}</h1>
        <p className="mt-1 text-[14px] text-ink-3">
          {parseDate(d?.today ?? new Date().toISOString()).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
      </div>
      <ErrorNote error={q.error} />
      {!d ? <Loading /> : d.accounts.length === 0 ? (
        <Panel><Empty title="Connect your first bank" icon={<CaretRight size={18} />}>
          Tally reads your transactions through Plaid. <Link className="text-accent underline" to="/accounts">Add an account</Link> to fill this in.
        </Empty></Panel>
      ) : (
        <div className="grid gap-4 md:grid-cols-12">
          <PlanStrip />
          <AskBox />
          <SpendingPace d={d} />
          <NetWorthCard d={d} />
          <HeadsUp d={d} rec={rec.data} />
          <DigestCard />
          <Upcoming d={d} />
          <TopCategories d={d} />
          <Recent d={d} onOpen={setOpen} />
          <Accounts d={d} />
        </div>
      )}
      <TxnDrawer txn={open} onClose={() => setOpen(null)} />
    </>
  )
}
