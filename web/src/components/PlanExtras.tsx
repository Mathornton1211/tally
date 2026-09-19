import { Briefcase, Calculator, Info } from '@phosphor-icons/react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmtShort, money, money0, pct } from '../lib/format'
import { cx, Money, Panel, PanelHeader, Skeleton } from './ui'

/** "If I land a job at X, when does this end?" Same engine as the payoff
 *  planner, pointed at a decision instead of a report. */
export function WhatIf() {
  const [income, setIncome] = useState(0)
  const [extra, setExtra] = useState(200)
  const [cut, setCut] = useState(0)
  const [debounced, setDebounced] = useState({ income: 0, extra: 200, cut: 0 })
  useEffect(() => {
    const t = setTimeout(() => setDebounced({ income, extra, cut }), 250)
    return () => clearTimeout(t)
  }, [income, extra, cut])

  const q = useQuery({
    queryKey: ['whatif', debounced],
    queryFn: () => api.whatIf(debounced.income, debounced.extra, debounced.cut),
    placeholderData: keepPreviousData,
  })
  const d = q.data

  const slider = (label: string, value: number, set: (n: number) => void, max: number, step: number, fmt: (n: number) => string) => (
    <div>
      <label className="flex items-baseline justify-between text-[13px] text-ink-2">
        <span>{label}</span><span className="text-[15px] font-semibold text-ink tnum">{fmt(value)}</span>
      </label>
      <input type="range" min={0} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))}
             className="mt-1.5 w-full accent-[var(--accent)]" />
    </div>
  )

  return (
    <Panel className="lg:col-span-7">
      <PanelHeader title="What if" sub="Move the sliders. Everything else is your real numbers." />
      <div className="grid gap-5 px-5 pb-5 pt-4 md:grid-cols-2">
        <div className="flex flex-col gap-4">
          {slider('Monthly income', income, setIncome, 12000, 100, money0)}
          {slider('Extra to debt each month', extra, setExtra, 1500, 25, money0)}
          {slider('Cut flexible spending by', cut, setCut, 100, 5, (n) => `${n}%`)}
        </div>
        {!d ? <Skeleton className="h-40 rounded-xl" /> : (
          <div className="flex flex-col gap-3">
            <div className={cx('rounded-xl px-4 py-3', d.covers_the_month ? 'bg-accent-soft' : 'bg-warn-soft')}>
              <div className="text-[13px] text-ink">
                {d.covers_the_month
                  ? <>That covers the month with <b><Money value={Number(d.left_over)} /></b> left over.</>
                  : <>That is <b><Money value={Number(d.shortfall)} /></b> short of the month.</>}
              </div>
              <div className="mt-1 text-[12px] text-ink-3">
                Essentials {money0(Number(d.essentials))} + flexible {money0(Number(d.flexible))}
                {Number(d.cut) > 0 && <> less {money0(Number(d.cut))} cut</>} = {money0(Number(d.spending))} a month
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-surface-2 px-4 py-3">
                <div className="text-[12px] text-ink-3">Debt free</div>
                <div className="mt-0.5 text-[18px] font-semibold text-ink">
                  {d.debt_free?.date ? fmtShort(d.debt_free.date) : '—'}
                </div>
                <div className="text-[12px] text-ink-3">{d.debt_free?.months ? `${d.debt_free.months} months` : 'not at this payment'}</div>
              </div>
              <div className="rounded-xl bg-surface-2 px-4 py-3">
                <div className="text-[12px] text-ink-3">3 month cushion</div>
                <div className="mt-0.5 text-[18px] font-semibold text-ink">
                  {d.cushion.date ? fmtShort(d.cushion.date) : '—'}
                </div>
                <div className="text-[12px] text-ink-3">
                  {d.cushion.months ? `${money0(Number(d.cushion.monthly))} a month toward ${money0(Number(d.cushion.target))}`
                    : 'nothing left over for it'}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

/** Nobody withholds tax on freelance money. This says how much is not yours. */
export function FreelanceTax() {
  const q = useQuery({ queryKey: ['freelance'], queryFn: () => api.freelance() })
  const d = q.data
  if (!d || Number(d.freelance_income) === 0) return null
  const short = Number(d.short_by)

  return (
    <Panel className="lg:col-span-5">
      <PanelHeader title="Freelance and tax" sub={`${d.year} so far`} />
      <div className="grid grid-cols-2 gap-3 px-5 pt-4">
        <div>
          <div className="text-[12px] text-ink-3">Self-employed income</div>
          <div className="mt-0.5 text-[22px] font-semibold tracking-tight text-ink"><Money value={Number(d.freelance_income)} size="lg" /></div>
        </div>
        <div>
          <div className="text-[12px] text-ink-3">Set aside for tax ({Number(d.rate_percent)}%)</div>
          <div className={cx('mt-0.5 text-[22px] font-semibold tracking-tight', short > 0 ? 'text-warn' : 'text-positive')}>
            <Money value={Number(d.should_set_aside)} size="lg" />
          </div>
          {d.tax_account
            ? <div className="text-[12px] text-ink-3">{money(Number(d.set_aside))} in {d.tax_account.name}{short > 0 && `, ${money0(short)} short`}</div>
            : <div className="text-[12px] text-ink-3">No account nominated yet</div>}
        </div>
      </div>
      {d.next_due && (
        <div className="mx-5 mt-4 rounded-xl bg-surface-2 px-4 py-3 text-[13px] text-ink-2">
          Next estimated payment <b className="text-ink">{d.next_due.quarter}</b>, due {fmtShort(d.next_due.due_date)}:
          about <b className="text-ink">{money(Number(d.next_due.estimated_payment))}</b> on {money0(Number(d.next_due.income))} earned.
        </div>
      )}
      {d.clients.length > 0 && (
        <ul className="mt-3 divide-y divide-line pb-1">
          {d.clients.slice(0, 5).map((c) => (
            <li key={c.name} className="flex items-center justify-between gap-3 px-5 py-2">
              <span className="flex min-w-0 items-center gap-2 truncate text-[13px] text-ink">
                <Briefcase size={13} className="shrink-0 text-ink-3" />{c.name}
              </span>
              <span className="shrink-0 text-[13px] text-ink tnum">{money(Number(c.income))} <span className="text-ink-3">{pct(c.share, 0)}</span></span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-start gap-1.5 border-t border-line px-5 py-2.5 text-[12px] text-ink-3">
        <Info size={13} className="mt-0.5 shrink-0" /> {d.note}
      </div>
    </Panel>
  )
}

export function WhatIfIcon() {
  return <Calculator size={16} />
}
