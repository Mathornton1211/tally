import {
  CalendarBlank, CheckCircle, Clock, Flag, PiggyBank, Plus, ShieldCheck, TrendDown, TrendUp, Trash, Warning, X,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, type Goal, type GoalsPayload } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtMonth, money, money0, moneyCompact, pct } from '../lib/format'


const field = 'h-10 w-full rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3'

const KINDS = [
  { value: 'net_worth', label: 'Net worth', icon: TrendUp,
    blurb: 'Everything you own, less everything you owe.' },
  { value: 'debt_free', label: 'Debt free', icon: TrendDown,
    blurb: 'Clear every card and loan. The target is zero.' },
  { value: 'emergency_fund', label: 'Emergency fund', icon: ShieldCheck,
    blurb: 'A cushion measured in months of spending.' },
  { value: 'savings', label: 'Savings', icon: PiggyBank,
    blurb: 'A balance to reach and keep.' },
] as const

const KIND = Object.fromEntries(KINDS.map((k) => [k.value, k]))

/**
 * Each state gets its own sentence. The colour is a second signal, never the
 * only one -- "behind" has to read as behind with the colour stripped out.
 */
function stateNote(g: Goal) {
  switch (g.state) {
    case 'done':
      return { icon: CheckCircle, tone: 'text-positive',
               text: g.kind === 'debt_free' ? 'Cleared. Nothing left owing.' : 'Reached.' }
    case 'on_track':
      return { icon: CheckCircle, tone: 'text-positive',
               text: g.eta ? `On track — arriving around ${fmtMonth(g.eta, true)}.` : 'On track for the date set.' }
    case 'behind':
      return { icon: Warning, tone: 'text-warn',
               text: g.shortfall_per_month != null
                 ? `${money(Number(g.shortfall_per_month))} a month short of the pace this needs.`
                 : 'Behind the pace this date needs.' }
    case 'no_deadline':
      return { icon: CalendarBlank, tone: 'text-ink-3',
               text: g.eta
                 ? `No date set. At the current pace, around ${fmtMonth(g.eta, true)}.`
                 : 'No date set, so there is no pace to be behind.' }
    default:
      return { icon: Clock, tone: 'text-ink-3',
               text: 'Not enough history yet to say which way this is going.' }
  }
}

function NetWorthLine({ series }: { series: GoalsPayload['series'] }) {
  const t = useChartTheme()
  const option = useMemo(() => {
    const net = series.map((p) => Number(p.assets) - Number(p.liabilities))
    return {
      animationDuration: 500,
      grid: { left: 4, right: 10, top: 16, bottom: 4, containLabel: true },
      xAxis: {
        type: 'category', data: series.map((p) => p.date), boundaryGap: false,
        axisTick: { show: false }, axisLine: { lineStyle: { color: t.grid } },
        axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11,
                     formatter: (v: string) => fmtMonth(v) },
      },
      yAxis: {
        type: 'value', splitNumber: 4, scale: true,
        axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact },
        splitLine: { lineStyle: { color: t.grid } },
      },
      tooltip: {
        ...tooltipBase(t), trigger: 'axis',
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0].dataIndex
          return `<div style="color:${t.ink3};margin-bottom:4px">${fmtMonth(series[i].date, true)}</div>`
            + `<b style="font-variant-numeric:tabular-nums">${money(net[i])}</b>`
        },
      },
      series: [{
        name: 'Net worth', type: 'line', data: net, smooth: true, symbol: 'none',
        lineStyle: { width: 2, color: t.s1 },
        areaStyle: { color: t.s1, opacity: 0.08 },
      }],
    }
  }, [series, t])
  return <Chart option={option} height={200} ariaLabel="Net worth over time" />
}

function AddGoal({ monthlySpend, onClose }: { monthlySpend: number; onClose: () => void }) {
  const qc = useQueryClient()
  const [kind, setKind] = useState<string>('net_worth')
  const [g, setG] = useState({ name: '', target_amount: '', target_months: '3', target_date: '', note: '' })

  // An emergency fund is the one goal normally said in months rather than
  // dollars, so it opens that way; everything else opens on an amount.
  const byMonths = kind === 'emergency_fund'
  const noTarget = kind === 'debt_free'

  const save = useMutation({
    mutationFn: () => api.createGoal({
      kind,
      name: g.name.trim() || KIND[kind].label,
      target_amount: !noTarget && !byMonths && g.target_amount ? Number(g.target_amount) : null,
      target_months: byMonths && g.target_months ? Number(g.target_months) : null,
      target_date: g.target_date || null,
      note: g.note.trim() || null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['goals'] }); onClose() },
  })

  const ready = noTarget || (byMonths ? !!g.target_months : !!g.target_amount)

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}
            className="relative max-h-[90dvh] w-full max-w-[460px] overflow-y-auto rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
            style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-start justify-between px-6 pt-5">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">Something to aim at</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>

        <div className="grid gap-4 px-6 pt-5">
          <div className="grid grid-cols-2 gap-2">
            {KINDS.map((k) => (
              <button key={k.value} type="button" onClick={() => setKind(k.value)}
                      className={cx('flex flex-col gap-1 rounded-xl border px-3 py-2.5 text-left transition-colors',
                        kind === k.value ? 'border-ink-3 bg-surface-2 text-ink' : 'border-line text-ink-2 hover:bg-hover')}>
                <span className="flex items-center gap-1.5 text-[13px] font-medium">
                  <k.icon size={14} weight={kind === k.value ? 'fill' : 'regular'} />{k.label}
                </span>
                <span className="text-[11px] leading-snug text-ink-3">{k.blurb}</span>
              </button>
            ))}
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">Call it</span>
            <input autoFocus value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })}
                   placeholder={KIND[kind].label} className={field} />
          </label>

          {byMonths ? (
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Months of spending</span>
              <input inputMode="decimal" value={g.target_months}
                     onChange={(e) => setG({ ...g, target_months: e.target.value.replace(/[^\d.]/g, '') })}
                     className={field} />
              <span className="text-[12px] text-ink-3">
                Months rather than a fixed number, so the target moves when your costs do — at{' '}
                {money0(monthlySpend)} a month that is about {money0(monthlySpend * Number(g.target_months || 0))}.
              </span>
            </label>
          ) : noTarget ? (
            <div className="rounded-xl bg-surface-2 px-3 py-2.5 text-[12px] text-ink-2">
              No amount to set — the target is zero, and progress is every card and loan balance coming down.
            </div>
          ) : (
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Target amount</span>
              <input inputMode="decimal" value={g.target_amount} placeholder="25000"
                     onChange={(e) => setG({ ...g, target_amount: e.target.value.replace(/[^\d.]/g, '') })}
                     className={field} />
            </label>
          )}

          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">By when (optional)</span>
            <input type="date" value={g.target_date} onChange={(e) => setG({ ...g, target_date: e.target.value })}
                   className={field} />
            <span className="text-[12px] text-ink-3">Without a date there is nothing to be on track for — just a number.</span>
          </label>
        </div>

        <div className="px-6 pt-3"><ErrorNote error={save.error} /></div>
        <div className="mt-4 flex justify-end gap-2 border-t border-line px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={save.isPending || !ready}>
            {save.isPending ? 'Adding…' : 'Add'}
          </Button>
        </div>
      </form>
    </div>
  )
}

function GoalCard({ g }: { g: Goal }) {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ['goals'] })
  const del = useMutation({ mutationFn: () => api.deleteGoal(g.id), onSuccess: invalidate })

  const meta = KIND[g.kind] ?? KIND.net_worth
  const note = stateNote(g)
  const Icon = meta.icon
  const NoteIcon = note.icon

  // Debt counts DOWN. There is no "starting debt" stored, so a fill-to-target
  // bar would be inventing a denominator; the number owed is the honest one.
  const down = g.kind === 'debt_free'
  const percent = g.percent == null ? null : Math.max(0, Math.min(g.percent, 1))
  const fill = g.state === 'done' ? 'bg-positive' : g.state === 'behind' ? 'bg-warn' : 'bg-series-1'

  return (
    <Panel className={cx('flex flex-col', g.done && 'opacity-80')}>
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="flex min-w-0 items-center gap-3">
          <div className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
            g.done ? 'bg-accent-soft text-positive' : 'bg-hover text-ink-2')}>
            <Icon size={19} />
          </div>
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold text-ink">{g.name}</div>
            <div className="truncate text-[12px] text-ink-3">
              {meta.label}
              {g.target_date && ` · by ${fmtMonth(g.target_date, true)}`}
              {g.target_months != null && ` · ${Number(g.target_months)} months of spending`}
            </div>
          </div>
        </div>
        <button onClick={() => del.mutate()} className="shrink-0 p-1 text-ink-3 hover:text-negative" aria-label="Delete goal">
          <Trash size={13} />
        </button>
      </div>

      <div className="px-5 pt-4">
        {down ? (
          <>
            <div className="flex items-baseline gap-2">
              <span className="text-[26px] font-semibold tracking-tight text-ink">
                <Money value={Number(g.remaining)} size="lg" />
              </span>
              <span className="text-[13px] text-ink-3">left to clear</span>
            </div>
            <div className="mt-1 text-[12px] text-ink-3">
              {g.pace_per_month != null && Number(g.pace_per_month) > 0
                ? `Coming down about ${money0(Number(g.pace_per_month))} a month.`
                : 'Not coming down yet at a measurable rate.'}
            </div>
          </>
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[22px] font-semibold tracking-tight text-ink">
                <Money value={Number(g.current)} size="lg" />
              </span>
              <span className="shrink-0 text-[13px] text-ink-3 tnum">
                of {money0(Number(g.target))}{percent != null && ` · ${pct(percent)}`}
              </span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-hover">
              <div className={cx('h-full', fill)} style={{ width: `${(percent ?? 0) * 100}%` }} />
            </div>
            {!g.done && (
              <div className="mt-1.5 text-[12px] text-ink-3 tnum">{money(Number(g.remaining))} to go</div>
            )}
          </>
        )}
      </div>

      <div className={cx('mx-5 mt-3 flex items-start gap-1.5 rounded-xl px-3 py-2 text-[12px]',
        g.state === 'behind' ? 'bg-warn-soft' : g.state === 'done' ? 'bg-accent-soft' : 'bg-surface-2')}>
        <NoteIcon size={13} weight="fill" className={cx('mt-0.5 shrink-0', note.tone)} />
        <span className="text-ink-2">{note.text}</span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line px-5 py-3 text-[12px]">
        <div>
          <div className="text-ink-3">Needs a month</div>
          <div className="font-medium tnum text-ink">
            {g.required_per_month == null ? '—' : money0(Number(g.required_per_month))}
          </div>
        </div>
        <div>
          <div className="text-ink-3">Doing a month</div>
          <div className="font-medium tnum text-ink">
            {g.pace_per_month == null ? '—' : money0(Number(g.pace_per_month))}
          </div>
        </div>
        <div>
          <div className="text-ink-3">At that pace</div>
          <div className="font-medium tnum text-ink">
            {g.months_at_pace == null ? '—' : `${g.months_at_pace} mo`}
          </div>
        </div>
      </div>
      {g.note && <div className="px-5 pb-4 text-[12px] text-ink-3">{g.note}</div>}
    </Panel>
  )
}

function Suggestions({ list, monthlySpend }: { list: GoalsPayload['suggestions']; monthlySpend: number }) {
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: (s: GoalsPayload['suggestions'][number]) => api.createGoal({
      kind: s.kind, name: s.name,
      target_amount: s.target_amount ?? null,
      target_months: s.target_months ?? null,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  })
  if (!list.length) return null
  return (
    <Panel className="mb-4">
      <PanelHeader title="Worth aiming at"
                   sub="The standard advice, with your own numbers in it. Add one and change it later." />
      <ul className="mt-3 divide-y divide-line border-t border-line">
        {list.map((s) => {
          const Icon = (KIND[s.kind] ?? KIND.net_worth).icon
          return (
            <li key={s.kind} className="flex items-start gap-3 px-5 py-3">
              <Icon size={16} className="mt-0.5 shrink-0 text-ink-3" />
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium text-ink">{s.name}</div>
                <div className="mt-0.5 text-[12px] leading-snug text-ink-3">{s.why}</div>
              </div>
              <Button onClick={() => add.mutate(s)} disabled={add.isPending}>
                <Plus size={12} weight="bold" /> Add
              </Button>
            </li>
          )
        })}
      </ul>
      <div className="px-5 pb-3 pt-1 text-[11px] text-ink-3">
        Based on about {money0(monthlySpend)} a month of spending.
      </div>
    </Panel>
  )
}

export default function Goals() {
  const [adding, setAdding] = useState(false)
  const q = useQuery({ queryKey: ['goals'], queryFn: api.goals2 })
  const d = q.data

  // The one cast, for the duplicate `Goal` declaration noted at the top.
  const goals = d?.goals ?? []
  const behind = goals.filter((g) => g.state === 'behind').length

  return (
    <>
      <PageHeader title="Goals" sub="Where the money is heading, and whether that is where you wanted it to go.">
        <Button variant="primary" onClick={() => setAdding(true)}><Plus size={14} weight="bold" /> Add</Button>
      </PageHeader>

      <ErrorNote error={q.error} />
      {adding && <AddGoal monthlySpend={Number(d?.monthly_spend ?? 0)} onClose={() => setAdding(false)} />}

      {!d ? (
        <div className="grid gap-4">
          <Skeleton className="h-24 rounded-[18px]" />
          <Skeleton className="h-64 rounded-[18px]" />
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-3">
            {[
              { label: 'Net worth now', node: <Money value={Number(d.net_worth)} size="lg" /> },
              { label: `Moving a month`,
                node: d.pace_per_month == null
                  ? <span className="text-[15px] text-ink-3">not enough history</span>
                  : <Money value={Number(d.pace_per_month)} size="lg" showPlus /> },
              { label: 'Spending a month', node: <Money value={Number(d.monthly_spend)} size="lg" /> },
            ].map((t, i) => (
              <div key={t.label} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">{t.node}</div>
              </div>
            ))}
          </div>

          {d.series.length > 1 && (
            <Panel className="mb-4">
              <PanelHeader title="Net worth"
                           sub={`Measured over the last ${Math.round(d.measured_over_days / 30)} months — the pace above comes from this line.`} />
              <div className="px-3 pb-3 pt-2"><NetWorthLine series={d.series} /></div>
            </Panel>
          )}

          {behind > 0 && (
            <div className="mb-4 flex items-start gap-2 rounded-2xl border border-line bg-warn-soft px-4 py-3 text-[13px] text-ink">
              <Warning size={15} weight="fill" className="mt-0.5 shrink-0 text-warn" />
              <span>
                {behind === 1 ? 'One goal is' : `${behind} goals are`} behind the pace their date needs. Either the
                date moves or the monthly number does.
              </span>
            </div>
          )}

          <Suggestions list={d.suggestions} monthlySpend={Number(d.monthly_spend)} />

          {goals.length === 0 ? (
            <Panel><Empty title="Nothing to aim at yet" icon={<Flag size={20} />}>
              A goal turns the net worth chart from a line into a question with an answer: at this rate, do you
              get there, and if not, by how much a month are you short?
            </Empty></Panel>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {goals.map((g) => <GoalCard key={g.id} g={g} />)}
            </div>
          )}
        </>
      )}
    </>
  )
}
