import { Info, Lifebuoy, Plus, Target, Trash, TrendUp, Warning } from '@phosphor-icons/react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, type Debt, type Plan as P, type PayoffPlan } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { FreelanceTax, WhatIf } from '../components/PlanExtras'
import { Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, PanelHeader, Segmented, Skeleton } from '../components/ui'
import { fmtShort, money, money0, moneyCompact, relativeDays } from '../lib/format'

const MODE = {
  survival: { label: 'Tight right now', tone: 'bg-warn-soft text-warn', icon: Lifebuoy },
  payoff: { label: 'Paying down', tone: 'bg-accent-soft text-positive', icon: TrendUp },
  growth: { label: 'Building', tone: 'bg-accent-soft text-positive', icon: Target },
}

const EVENT_TONE: Record<string, string> = {
  overdue: 'text-negative', minimum: 'text-ink', bill: 'text-ink', subscription: 'text-ink-2', income: 'text-positive',
}

function RunwayCard({ d }: { d: P }) {
  const t = useChartTheme()
  const rw = d.runway
  const days = rw.days_until_zero
  const series = useMemo(() => rw.series.slice(0, 60), [rw.series])

  const option = useMemo(() => ({
    animationDuration: 500,
    grid: { left: 4, right: 10, top: 14, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category', boundaryGap: false, data: series.map((p) => p.date), axisTick: { show: false },
      axisLine: { lineStyle: { color: t.grid } },
      axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, hideOverlap: true, formatter: (v: string) => fmtShort(v) },
    },
    yAxis: { type: 'value', axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact }, splitLine: { lineStyle: { color: t.grid } } },
    tooltip: {
      ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: t.line } },
      formatter: (ps: { dataIndex: number }[]) => {
        const p = series[ps[0].dataIndex]
        const due = rw.events.filter((e) => e.date === p.date)
        return `<div style="color:${t.ink3}">${fmtShort(p.date)}</div><b style="font-variant-numeric:tabular-nums">${money(Number(p.balance))}</b>`
          + due.map((e) => `<div style="color:${t.ink3};font-size:11px">${e.name} ${money(Math.abs(Number(e.amount)))}</div>`).join('')
      },
    },
    series: [{
      type: 'line', data: series.map((p) => Number(p.balance)), showSymbol: false, smooth: 0.15,
      lineStyle: { width: 2.5, color: t.s1 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: t.s1 + '2e' }, { offset: 1, color: t.s1 + '00' }] } },
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { color: t.s2, type: 'dashed', width: 1.5 },
        label: { show: false },
        data: [{ yAxis: 0 }],
      },
    }],
  }), [series, rw.events, t])

  return (
    <Panel className="lg:col-span-7">
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 pt-5">
        <div>
          <div className="text-[13px] font-medium text-ink-3">Cash on hand</div>
          <div className="mt-1 text-[40px] font-semibold leading-none tracking-tight text-ink">
            <Money value={Number(rw.cash)} size="hero" />
          </div>
          <div className="mt-2 text-[13px] text-ink-2">
            {days == null ? (
              <>Covers everything Tally can see for the next 90 days.</>
            ) : (
              <>Runs out <span className="font-medium text-negative">in {days} {days === 1 ? 'day' : 'days'}</span>{' '}
                ({fmtShort(rw.zero_date!)}) at about {money0(Number(rw.daily_spending))} a day plus the bills below.</>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[13px] text-ink-3">{rw.income_expected ? 'Before the next money' : 'Through ' + fmtShort(rw.committed_through)}</div>
          <div className={cx('mt-1 text-[22px] font-semibold tracking-tight', Number(rw.safe_to_spend) < 0 ? 'text-negative' : 'text-positive')}>
            {Number(rw.safe_to_spend) < 0
              ? <>Short <Money value={Math.abs(Number(rw.safe_to_spend))} size="lg" /></>
              : <><Money value={Number(rw.safe_to_spend)} size="lg" /> spare</>}
          </div>
          <div className="text-[12px] text-ink-3">
            {money0(Number(rw.committed_before_income))} committed
            {rw.next_income && <> · next money {relativeDays(rw.next_income.date)}</>}
          </div>
        </div>
      </div>
      <div className="px-3 pb-2 pt-2"><Chart option={option} height={200} ariaLabel="Projected cash balance" /></div>
      {/* Louder than the income note below it on purpose: a missing rent does
          not make this projection cautious, it makes it wrong. */}
      {(rw.gaps ?? []).map((g) => (
        <div key={g.key} className="flex items-start gap-2 border-t border-line bg-warn-soft px-5 py-2.5 text-[12px] text-warn">
          <Warning size={14} weight="fill" className="mt-0.5 shrink-0" />
          <span><span className="font-medium">{g.label}.</span> {g.detail}</span>
        </div>
      ))}
      {!rw.income_expected && (
        <div className="flex items-start gap-2 border-t border-line px-5 py-2.5 text-[12px] text-ink-3">
          <Info size={14} className="mt-0.5 shrink-0" />
          No repeating income found, so this projection assumes nothing comes in. Freelance or one-off deposits won't show up here until they repeat.
        </div>
      )}
    </Panel>
  )
}

function Upcoming({ d }: { d: P }) {
  const rw = d.runway
  let balance = Number(rw.cash)
  const rows = rw.events.slice(0, 12).map((e) => {
    balance -= Number(e.amount)
    return { ...e, after: balance }
  })
  return (
    <Panel className="lg:col-span-5">
      <PanelHeader title="What's coming" sub="Bills, minimums and income, in order" />
      {rows.length === 0 ? <Empty title="Nothing scheduled" /> : (
        <ul className="mt-2 divide-y divide-line pb-1">
          {rows.map((e, i) => (
            <li key={i} className="flex items-center gap-3 px-5 py-2.5">
              <div className="w-16 shrink-0 text-[12px] text-ink-3">{relativeDays(e.date)}</div>
              <div className="min-w-0 flex-1">
                <div className={cx('truncate text-[14px]', EVENT_TONE[e.kind] ?? 'text-ink')}>
                  {e.name}
                  {e.kind === 'overdue' && <span className="ml-2 rounded-full bg-bad-soft px-1.5 py-0.5 text-[11px] font-medium text-negative">past due</span>}
                </div>
              </div>
              <div className="text-right">
                <Money value={-Number(e.amount)} className={cx('text-[14px] font-medium', Number(e.amount) < 0 ? 'text-positive' : 'text-ink')} showPlus />
                <div className={cx('text-[11px] tnum', e.after < 0 ? 'text-negative' : 'text-ink-3')}>
                  {e.after < 0 ? 'short ' : 'leaves '}{money0(Math.abs(e.after))}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function Cards({ d }: { d: P }) {
  const u = d.utilization
  return (
    <Panel className="lg:col-span-5">
      <PanelHeader title="Cards and loans"
                   sub={u ? `${money0(Number(u.used))} of ${money0(Number(u.limit))} used · ${Math.round((u.percent ?? 0) * 100)}%` : undefined}
                   action={<span className="text-right text-[12px] text-ink-3">{money0(Number(d.monthly_interest_total))}/mo<br />in interest</span>} />
      <ul className="mt-3 divide-y divide-line pb-1">
        {d.debts.map((x: Debt) => (
          <li key={x.account_id} className="px-5 py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-[14px] font-medium text-ink">{x.name}{x.mask && <span className="text-ink-3"> ··{x.mask}</span>}</span>
              <Money value={Number(x.balance)} className="text-[14px] font-semibold text-ink" />
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              {x.credit_limit && (
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-hover">
                  <div className={cx('h-full rounded-full', (x.utilization ?? 0) >= 0.9 ? 'bg-negative' : (x.utilization ?? 0) >= 0.3 ? 'bg-warn' : 'bg-positive')}
                       style={{ width: `${Math.min((x.utilization ?? 0) * 100, 100)}%` }} />
                </div>
              )}
              <span className="text-[11px] text-ink-3 tnum">{x.utilization != null && `${Math.round(x.utilization * 100)}% of ${money0(Number(x.credit_limit))}`}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-3">
              <span>{x.apr != null ? `${Number(x.apr).toFixed(2)}% APR` : 'rate unknown'}
                {x.apr_source !== 'issuer' && x.apr != null && <span className="text-ink-3"> ({x.apr_source})</span>}</span>
              <span aria-hidden>·</span>
              <span>min {money(Number(x.minimum))}{x.minimum_source === 'assumed' && ' (estimated)'}</span>
              {x.due_date && <><span aria-hidden>·</span>
                <span className={x.is_overdue ? 'font-medium text-negative' : ''}>
                  {x.is_overdue ? 'past due' : `due ${relativeDays(x.due_date).toLowerCase()}`}
                </span></>}
              <span aria-hidden>·</span>
              <span>{money(Number(x.monthly_interest))}/mo interest</span>
            </div>
          </li>
        ))}
      </ul>
      {d.debts.some((x) => x.apr_source !== 'issuer') && (
        <div className="border-t border-line px-5 py-2.5 text-[12px] text-ink-3">
          Rates marked estimated or entered aren't from the issuer. Adding the real APR in Accounts makes the plan below exact.
        </div>
      )}
    </Panel>
  )
}

function PayoffPlanner({ d }: { d: P }) {
  const qc = useQueryClient()
  const t = useChartTheme()
  const [extra, setExtra] = useState(Number(d.settings.monthly_extra || 0))
  const [strategy, setStrategy] = useState(d.settings.strategy || 'avalanche')
  const [debounced, setDebounced] = useState(extra)
  useEffect(() => { const id = setTimeout(() => setDebounced(extra), 250); return () => clearTimeout(id) }, [extra])

  const q = useQuery({
    queryKey: ['payoff', debounced, strategy],
    queryFn: () => api.payoff(debounced, strategy),
    placeholderData: keepPreviousData,
  })
  const save = useMutation({
    mutationFn: () => api.savePlanSettings({ monthly_extra: extra, strategy }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan'] }),
  })

  const res = q.data?.result as PayoffPlan | undefined
  const base = q.data?.minimums as PayoffPlan | undefined
  const option = useMemo(() => {
    if (!res || !base) return null
    const n = Math.max(res.balances.length, Math.min(base.balances.length, 120))
    const pad = (arr: { month: number; balance: number }[]) =>
      Array.from({ length: n }, (_, i) => (i < arr.length ? Number(arr[i].balance) : 0))
    return {
      animationDuration: 400,
      grid: { left: 4, right: 10, top: 14, bottom: 4, containLabel: true },
      xAxis: { type: 'category', boundaryGap: false, data: Array.from({ length: n }, (_, i) => i + 1),
               axisTick: { show: false }, axisLine: { lineStyle: { color: t.grid } },
               axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, hideOverlap: true,
                            formatter: (v: string) => (Number(v) % 12 === 0 ? `${Number(v) / 12}y` : '') } },
      yAxis: { type: 'value', axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact }, splitLine: { lineStyle: { color: t.grid } } },
      tooltip: {
        ...tooltipBase(t), trigger: 'axis',
        formatter: (ps: { dataIndex: number; seriesName: string; value: number; color: string }[]) =>
          `<div style="color:${t.ink3}">Month ${ps[0].dataIndex + 1}</div>` + ps.map((p) =>
            `<div style="display:flex;gap:14px;justify-content:space-between"><span style="display:flex;gap:6px;align-items:center"><span style="width:8px;height:8px;border-radius:9px;background:${p.color}"></span>${p.seriesName}</span><b style="font-variant-numeric:tabular-nums">${money0(p.value)}</b></div>`).join(''),
      },
      series: [
        { name: 'Minimums only', type: 'line', data: pad(base.balances), showSymbol: false, smooth: 0.2, lineStyle: { width: 2, color: t.compare }, itemStyle: { color: t.compare } },
        { name: 'Your plan', type: 'line', data: pad(res.balances), showSymbol: false, smooth: 0.2, lineStyle: { width: 2.5, color: t.s1 }, itemStyle: { color: t.s1 },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: t.s1 + '2e' }, { offset: 1, color: t.s1 + '00' }] } } },
      ],
    }
  }, [res, base, t])

  if (!d.payoff) return null
  const changed = extra !== Number(d.settings.monthly_extra || 0) || strategy !== d.settings.strategy

  return (
    <Panel className="lg:col-span-12">
      <PanelHeader title="Payoff plan" sub="Minimums on everything, and every spare dollar at one card until it's gone."
                   action={<Segmented value={strategy} onChange={setStrategy}
                                      options={[{ value: 'avalanche', label: 'Cheapest' }, { value: 'snowball', label: 'Fastest win' }]} />} />
      <div className="grid gap-5 px-5 pt-4 lg:grid-cols-2">
        <div>
          <label htmlFor="extra" className="flex items-baseline justify-between text-[13px] text-ink-2">
            <span>Extra per month, on top of {money0(Number(d.minimums_total))} of minimums</span>
            <span className="text-[16px] font-semibold text-ink tnum">{money0(extra)}</span>
          </label>
          <input id="extra" type="range" min={0} max={600} step={10} value={extra}
                 onChange={(e) => setExtra(Number(e.target.value))}
                 className="mt-2 w-full accent-[var(--accent)]" />
          <div className="flex justify-between text-[11px] text-ink-3"><span>$0</span><span>$600</span></div>
          {changed && (
            <Button className="mt-3" onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save this as my plan'}
            </Button>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-surface-2 px-4 py-3">
            <div className="text-[12px] text-ink-3">Debt free</div>
            <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">
              {res?.payoff_date ? new Date(res.payoff_date).toLocaleDateString('en-US', { month: 'short', year: 'numeric' }) : '—'}
            </div>
            <div className="text-[12px] text-ink-3">{res?.months ? `${res.months} months` : 'not at this payment'}</div>
          </div>
          <div className="rounded-xl bg-surface-2 px-4 py-3">
            <div className="text-[12px] text-ink-3">Interest you'd pay</div>
            <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink"><Money value={Number(res?.total_interest ?? 0)} size="lg" /></div>
            <div className="text-[12px] text-positive">{q.data?.interest_saved ? `${money0(Number(q.data.interest_saved))} less than minimums` : ''}</div>
          </div>
          <div className="col-span-2 rounded-xl bg-accent-soft px-4 py-3 text-[13px] text-ink">
            {res?.months && q.data?.months_saved
              ? <>Paying {money0(Number(res.monthly_payment))} a month clears everything in {res.months} months, {q.data.months_saved} months sooner than minimums, and saves {money0(Number(q.data.interest_saved))} in interest.</>
              : <>At minimums only this takes {base?.months ? `${Math.round(base.months / 12)} years` : 'longer than 50 years'}. Even {money0(50)} extra changes that; try the slider.</>}
          </div>
        </div>
      </div>
      {option && <div className="px-3 pb-1 pt-4"><Chart option={option} height={180} ariaLabel="Balance over time, your plan versus minimums" /></div>}
      <ol className="divide-y divide-line border-t border-line">
        {res?.order.map((o) => (
          <li key={o.account_id} className="flex items-center gap-3 px-5 py-2.5">
            <span className={cx('flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold',
              o.rank === 1 ? 'bg-accent text-accent-ink' : 'bg-hover text-ink-2')}>{o.rank}</span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] text-ink">{o.name}{o.mask && <span className="text-ink-3"> ··{o.mask}</span>}</div>
              <div className="text-[12px] text-ink-3">
                {money(Number(o.balance))}{o.apr != null && ` at ${Number(o.apr).toFixed(2)}%`}
                {o.rank === 1 && <span className="ml-2 font-medium text-positive">← everything spare goes here</span>}
              </div>
            </div>
            <div className="text-right text-[12px] text-ink-3">
              {o.paid_off_month ? <>gone in {o.paid_off_month} mo<br /><span className="text-[11px]">{money0(Number(o.interest_paid))} interest</span></> : 'not cleared'}
            </div>
          </li>
        ))}
      </ol>
      {res?.stalled.length ? (
        <div className="border-t border-line bg-warn-soft px-5 py-3 text-[13px] text-warn">
          At this payment the interest on {res.stalled.join(', ')} grows faster than the payments. More per month, or a lower rate, is the only way out. Card issuers have hardship programs that can cut the rate; it costs a phone call to ask.
        </div>
      ) : null}
    </Panel>
  )
}

function Goals({ d }: { d: P }) {
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: (g: { name: string; kind: string; target_amount: number; account_id?: string | null }) => api.createGoal(g),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan'] }),
  })
  const del = useMutation({ mutationFn: api.deleteGoal, onSuccess: () => qc.invalidateQueries({ queryKey: ['plan'] }) })

  return (
    <Panel className="lg:col-span-7">
      <PanelHeader title="Goals" sub="Progress reads straight from the account, so nothing needs updating by hand." />
      <ul className="mt-2 divide-y divide-line">
        {d.goals.map((g) => (
          <li key={g.id} className="px-5 py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-[14px] font-medium text-ink">{g.name}</span>
              <span className="text-[13px] text-ink tnum"><Money value={Number(g.current)} /> <span className="text-ink-3">of {money0(Number(g.target_amount))}</span></span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-hover">
              <div className="h-full rounded-full bg-positive transition-[width] duration-500" style={{ width: `${Math.min((g.percent ?? 0) * 100, 100)}%` }} />
            </div>
            <div className="mt-1 flex items-center justify-between text-[12px] text-ink-3">
              <span>{g.months_to_go ? `about ${g.months_to_go} months at ${money0(Number(g.monthly_contribution))}/mo` : `${money0(Number(g.remaining))} to go`}</span>
              <button onClick={() => del.mutate(g.id)} className="inline-flex items-center gap-1 hover:text-ink"><Trash size={12} /> Remove</button>
            </div>
          </li>
        ))}
      </ul>
      {d.suggested_goals.length > 0 && (
        <div className="border-t border-line px-5 py-4">
          <div className="mb-2 text-[12px] font-medium text-ink-3">Worth setting</div>
          <div className="flex flex-col gap-2">
            {d.suggested_goals.map((s) => (
              <div key={s.name} className="flex items-start gap-3 rounded-xl bg-surface-2 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium text-ink">{s.name} · {money0(Number(s.target_amount))}</div>
                  <div className="text-[12px] text-ink-3">{s.why}</div>
                </div>
                <Button onClick={() => add.mutate({ name: s.name, kind: s.kind, target_amount: Number(s.target_amount), account_id: s.account_id ?? null })}
                        disabled={add.isPending}><Plus size={13} weight="bold" /> Add</Button>
              </div>
            ))}
          </div>
        </div>
      )}
      {d.goals.length === 0 && d.suggested_goals.length === 0 && <Empty title="No goals yet" icon={<Target size={18} />} />}
    </Panel>
  )
}

function Options({ d }: { d: P }) {
  const stuck = d.payoff?.minimums.months == null || (d.payoff?.minimums.months ?? 0) > 120
  return (
    <Panel className="lg:col-span-5">
      <PanelHeader title="Options worth knowing" sub="Things that exist, not advice" />
      <ul className="space-y-3 px-5 py-4 text-[13px] leading-relaxed text-ink-2">
        <li><b className="text-ink">Hardship programs.</b> Most card issuers have one. A call can lower the rate, waive fees, or pause payments for a few months. Asking costs nothing and does not show on a credit report by itself.</li>
        <li><b className="text-ink">Nonprofit credit counseling.</b> Agencies in the NFCC network offer free or low-cost sessions and debt management plans, which is different from debt settlement companies that charge a percentage.</li>
        {stuck && <li><b className="text-ink">Rate matters more than order here.</b> At the current payment the balances barely move, so a lower rate, through a hardship program or a balance transfer offer, changes more than any reordering of payments.</li>}
        <li><b className="text-ink">Pay before the statement closes.</b> Utilization is reported from the statement balance, so paying a few days early lowers the number the credit bureaus see.</li>
        <li><b className="text-ink">Autopay the minimum on everything.</b> It turns a missed due date into a non-event. You can always pay more by hand.</li>
      </ul>
      <div className="border-t border-line px-5 py-3 text-[12px] text-ink-3">
        Tally is not a financial adviser. These are general options; the numbers above are your own.
      </div>
    </Panel>
  )
}

export default function PlanPage() {
  const q = useQuery({ queryKey: ['plan'], queryFn: api.plan })
  const d = q.data
  const m = d && MODE[d.mode.mode]
  const Icon = m?.icon ?? Lifebuoy

  return (
    <>
      <PageHeader title="Plan" sub="What is due, what is left, and when the cards are gone." />
      <ErrorNote error={q.error} />
      {!d ? (
        <div className="grid gap-4 lg:grid-cols-12">
          <Skeleton className="h-[330px] rounded-[18px] lg:col-span-7" />
          <Skeleton className="h-[330px] rounded-[18px] lg:col-span-5" />
          <Skeleton className="h-[420px] rounded-[18px] lg:col-span-12" />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <div className={cx('flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3 lg:col-span-12', m!.tone)}>
            <Icon size={18} weight="fill" />
            <span className="text-[14px] font-semibold">{m!.label}</span>
            <span className="text-[13px] opacity-90">{d.mode.reasons.join(' · ')}</span>
            {Number(d.debt_total) > 0 && (
              <span className="ml-auto text-[13px]">
                <Money value={Number(d.debt_total)} /> owed · {money0(Number(d.monthly_interest_total))}/mo in interest
              </span>
            )}
          </div>
          <RunwayCard d={d} />
          <Upcoming d={d} />
          <PayoffPlanner d={d} />
          <WhatIf />
          <FreelanceTax />
          <Cards d={d} />
          {/* When money is tight the options matter more than the goals; once it
              is not, the goals come first. */}
          {d.mode.mode === 'survival'
            ? <><Options d={d} /><Goals d={d} /></>
            : <><Goals d={d} /><Options d={d} /></>}
        </div>
      )}
    </>
  )
}
