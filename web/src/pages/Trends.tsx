import { CalendarBlank, ChartLineUp, TrendDown, TrendUp } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, type AnnualReview, type TrendsPayload, type YoYCategory } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { CategoryIcon } from '../components/icons'
import {
  cx, Empty, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, PanelHeader, Skeleton,
} from '../components/ui'
import { fmtMonth, fmtShort, money, money0, moneyCompact, pct } from '../lib/format'

const dayMonth = (s: string) =>
  new Date(`${s.slice(0, 10)}T00:00:00`).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })

/** A rise is bad and a fall is good, which is the opposite of most charts. */
function ChangeRow({ c }: { c: YoYCategory }) {
  const change = Number(c.change)
  const up = change > 0
  return (
    <li className="flex items-center gap-3 px-5 py-2.5">
      <CategoryIcon name={c.icon} size={16} className="shrink-0 text-ink-3" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] text-ink">{c.label}</div>
        <div className="text-[12px] text-ink-3 tnum">
          {money0(Number(c.before))} → {money0(Number(c.now))}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className={cx('text-[14px] font-medium tnum', up ? 'text-negative' : 'text-positive')}>
          {up ? '+' : '−'}{money(Math.abs(change))}
        </div>
        {c.percent != null && (
          <div className="text-[11px] text-ink-3 tnum">{up ? '+' : ''}{pct(c.percent)}</div>
        )}
      </div>
    </li>
  )
}

function MonthlyChart({ months }: { months: TrendsPayload['months'] }) {
  const t = useChartTheme()
  const option = useMemo(() => {
    const spent = months.map((m) => Number(m.spent))
    const earned = months.map((m) => Number(m.earned))
    return {
      animationDuration: 500,
      grid: { left: 4, right: 10, top: 28, bottom: 4, containLabel: true },
      legend: {
        top: 0, left: 0, itemWidth: 10, itemHeight: 10, itemGap: 16,
        textStyle: { color: t.ink3, fontFamily: t.font, fontSize: 11 },
        data: ['Out', 'In'],
      },
      xAxis: {
        type: 'category', data: months.map((m) => m.month), boundaryGap: true,
        axisTick: { show: false }, axisLine: { lineStyle: { color: t.grid } },
        axisLabel: {
          color: t.axis, fontFamily: t.font, fontSize: 11,
          formatter: (v: string) => fmtMonth(v),
          interval: months.length > 24 ? 2 : months.length > 12 ? 1 : 0,
        },
      },
      yAxis: {
        type: 'value', splitNumber: 4,
        axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact },
        splitLine: { lineStyle: { color: t.grid } },
      },
      tooltip: {
        ...tooltipBase(t), trigger: 'axis',
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0].dataIndex
          return `<div style="color:${t.ink3};margin-bottom:4px">${fmtMonth(months[i].month, true)}</div>`
            + `<div style="font-variant-numeric:tabular-nums">Out <b>${money(spent[i])}</b></div>`
            + `<div style="font-variant-numeric:tabular-nums">In <b>${money(earned[i])}</b></div>`
        },
      },
      series: [
        { name: 'Out', type: 'bar', data: spent, itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] },
          barMaxWidth: 18 },
        { name: 'In', type: 'line', data: earned, smooth: true, symbol: 'none',
          lineStyle: { width: 2, color: t.s2 } },
      ],
    }
  }, [months, t])
  return <Chart option={option} height={240} ariaLabel="Money out and in, by month" />
}

function YearOverYear({ y }: { y: TrendsPayload['year_over_year'] }) {
  const change = Number(y.spent_change)
  const up = change > 0

  if (!y.comparable) {
    return (
      <Panel className="mb-4">
        <PanelHeader title="This year against last" />
        <div className="px-5 pb-5 pt-1 text-[13px] text-ink-2">
          {y.history_starts
            ? <>Your history starts in {fmtMonth(y.history_starts, true)}, so{' '}
                {fmtMonth(y.last_year.from, true)} to {fmtShort(y.last_year.to)} is empty. Comparing
                against an empty stretch would report a rise in everything, which is the same dates
                and still nonsense. This fills in once there is a year behind it.</>
            : <>There is nothing to compare against yet. This fills in once Tally has a year of
                history behind it.</>}
        </div>
      </Panel>
    )
  }

  return (
    <Panel className="mb-4">
      <PanelHeader
        title="This year against last"
        sub={`${dayMonth(y.this_year.from)} – ${dayMonth(y.this_year.to)}, against the same dates last year. Comparing a part-year against a whole one would just be a smaller number.`}
      />
      <div className="grid gap-4 px-5 pb-1 pt-4 sm:grid-cols-3">
        <div>
          <div className="text-[12px] text-ink-3">Spent so far</div>
          <div className="mt-0.5 text-[22px] font-semibold tracking-tight text-ink">
            <Money value={Number(y.spent)} size="lg" />
          </div>
        </div>
        <div>
          <div className="text-[12px] text-ink-3">Same point last year</div>
          <div className="mt-0.5 text-[22px] font-semibold tracking-tight text-ink-2">
            <Money value={Number(y.spent_before)} size="lg" />
          </div>
        </div>
        <div>
          <div className="text-[12px] text-ink-3">Difference</div>
          <div className={cx('mt-0.5 flex items-center gap-1.5 text-[22px] font-semibold tracking-tight',
            up ? 'text-negative' : 'text-positive')}>
            {up ? <TrendUp size={18} weight="bold" /> : <TrendDown size={18} weight="bold" />}
            <Money value={Math.abs(change)} size="lg" />
          </div>
          {y.spent_percent != null && (
            <div className="mt-0.5 text-[12px] text-ink-3 tnum">
              {up ? 'more' : 'less'} — {pct(Math.abs(y.spent_percent))}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-px bg-line sm:grid-cols-2 mt-4">
        <div className="bg-surface">
          <div className="px-5 pb-1 pt-4 text-[13px] font-semibold text-ink">Costing more</div>
          {y.risen.length === 0 ? (
            <p className="px-5 pb-4 pt-1 text-[12px] text-ink-3">Nothing has risen by enough to mention.</p>
          ) : (
            <ul className="divide-y divide-line">{y.risen.map((c) => <ChangeRow key={c.category} c={c} />)}</ul>
          )}
        </div>
        <div className="bg-surface">
          <div className="px-5 pb-1 pt-4 text-[13px] font-semibold text-ink">Costing less</div>
          {y.fallen.length === 0 ? (
            <p className="px-5 pb-4 pt-1 text-[12px] text-ink-3">Nothing has fallen by enough to mention.</p>
          ) : (
            <ul className="divide-y divide-line">{y.fallen.map((c) => <ChangeRow key={c.category} c={c} />)}</ul>
          )}
        </div>
      </div>

      <details className="border-t border-line px-5 py-3">
        <summary className="cursor-pointer text-[12px] text-ink-2 hover:text-ink">
          Every category, including the ones too small to be news
        </summary>
        <ul className="mt-2 divide-y divide-line">
          {y.categories.map((c) => (
            <li key={c.category} className="flex items-center gap-3 py-2">
              <CategoryIcon name={c.icon} size={14} className="shrink-0 text-ink-3" />
              <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                {c.label}
                {!c.material && <span className="ml-2 text-[11px] text-ink-3">too small to read into</span>}
              </span>
              <span className="shrink-0 text-[12px] tnum text-ink-3">
                {money0(Number(c.before))} → {money0(Number(c.now))}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </Panel>
  )
}

function Review({ availableYears }: { availableYears: number[] }) {
  const [year, setYear] = useState<number | undefined>(availableYears[0])
  const q = useQuery({ queryKey: ['annual-review', year], queryFn: () => api.annualReview(year) })
  const r: AnnualReview | undefined = q.data

  return (
    <Panel className="mb-4">
      <PanelHeader
        title="The year in one page"
        sub="Including what it cost to carry, which is the part a highlight reel leaves out."
        action={
          availableYears.length > 1 ? (
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              aria-label="Year"
              className="h-9 rounded-lg border border-line-strong bg-surface-2 px-2 text-[13px] text-ink outline-none"
            >
              {availableYears.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          ) : undefined
        }
      />

      {!r ? (
        <div className="p-5"><Skeleton className="h-40 rounded-xl" /></div>
      ) : (
        <div className="px-5 pb-5 pt-4">
          {!r.complete && (
            <p className="mb-3 text-[12px] text-ink-3">
              {r.year} is not over — this covers {dayMonth(r.from)} to {dayMonth(r.to)}, {r.days} days.
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-4">
            {[
              { label: 'Out', value: <Money value={Number(r.spent)} size="lg" /> },
              { label: 'In', value: <Money value={Number(r.earned)} size="lg" /> },
              { label: 'A month', value: <Money value={Number(r.per_month)} size="lg" /> },
              { label: 'A day', value: <Money value={Number(r.per_day)} size="lg" /> },
            ].map((t) => (
              <div key={t.label}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className="mt-0.5 text-[18px] font-semibold tracking-tight text-ink">{t.value}</div>
              </div>
            ))}
          </div>

          <div className="mt-2 text-[12px] text-ink-3">
            {r.transactions.toLocaleString()} transactions across {r.merchants.toLocaleString()} merchants.
          </div>

          <div className="mt-5 grid gap-5 md:grid-cols-2">
            <div>
              <div className="mb-2 text-[13px] font-semibold text-ink">Where it went</div>
              <ul className="divide-y divide-line rounded-xl border border-line">
                {r.categories.slice(0, 8).map((c) => (
                  <li key={c.label} className="flex items-center gap-3 px-3 py-2">
                    <CategoryIcon name={c.icon} size={14} className="shrink-0 text-ink-3" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{c.label}</span>
                    {c.share != null && (
                      <span className="shrink-0 text-[11px] text-ink-3 tnum">{pct(c.share)}</span>
                    )}
                    <Money value={Number(c.total)} className="shrink-0 text-[13px] text-ink" />
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="mb-2 text-[13px] font-semibold text-ink">Who got it</div>
              <ul className="divide-y divide-line rounded-xl border border-line">
                {r.top_merchants.map((m) => (
                  <li key={m.name} className="flex items-center gap-3 px-3 py-2">
                    <MerchantAvatar logo={m.logo_url} icon="DotsThree" name={m.name} size={22} />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{m.name}</span>
                    <span className="shrink-0 text-[11px] text-ink-3 tnum">{m.times}×</span>
                    <Money value={Number(m.total)} className="shrink-0 text-[13px] text-ink" />
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            {r.most_expensive_month && (
              <div className="rounded-xl bg-surface-2 px-3 py-2.5">
                <div className="text-[12px] text-ink-3">Most expensive month</div>
                <div className="mt-0.5 text-[14px] font-medium text-ink">
                  {fmtMonth(r.most_expensive_month.month, true)}
                </div>
                <div className="text-[12px] tnum text-ink-2">
                  {money(Number(r.most_expensive_month.spent))}
                </div>
              </div>
            )}
            {r.cheapest_month && (
              <div className="rounded-xl bg-surface-2 px-3 py-2.5">
                <div className="text-[12px] text-ink-3">Cheapest month</div>
                <div className="mt-0.5 text-[14px] font-medium text-ink">
                  {fmtMonth(r.cheapest_month.month, true)}
                </div>
                <div className="text-[12px] tnum text-ink-2">{money(Number(r.cheapest_month.spent))}</div>
              </div>
            )}
            {r.biggest_single && (
              <div className="rounded-xl bg-surface-2 px-3 py-2.5">
                <div className="text-[12px] text-ink-3">Biggest single purchase</div>
                <div className="mt-0.5 truncate text-[14px] font-medium text-ink">
                  {r.biggest_single.name}
                </div>
                <div className="text-[12px] tnum text-ink-2">
                  {money(Number(r.biggest_single.amount))} · {r.biggest_single.category}
                </div>
              </div>
            )}
          </div>

          <div className="mt-4 rounded-xl border border-line px-3 py-2.5">
            <div className="text-[13px] font-semibold text-ink">What it cost to carry</div>
            <p className="mt-0.5 max-w-[66ch] text-[12px] text-ink-3">
              Fees and interest are money that bought nothing. They are here next to everything else on
              purpose.
            </p>
            <div className="mt-2 flex flex-wrap gap-6">
              <div>
                <div className="text-[12px] text-ink-3">
                  Fees{r.cost_of_carrying.count > 0 && ` (${r.cost_of_carrying.count})`}
                </div>
                <div className="text-[16px] font-semibold tnum text-ink">
                  <Money value={Number(r.cost_of_carrying.fees)} />
                </div>
              </div>
              <div>
                <div className="text-[12px] text-ink-3">Of which interest</div>
                <div className="text-[16px] font-semibold tnum text-ink">
                  <Money value={Number(r.cost_of_carrying.interest)} />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}

export default function Trends() {
  const q = useQuery({ queryKey: ['trends'], queryFn: api.trends })
  const d = q.data

  return (
    <>
      <PageHeader
        title="Trends"
        sub="What has changed over years rather than weeks."
      />
      <ErrorNote error={q.error} />

      {!d ? (
        <div className="grid gap-4">
          <Skeleton className="h-40 rounded-[18px]" />
          <Skeleton className="h-64 rounded-[18px]" />
        </div>
      ) : d.months.length === 0 ? (
        <Panel>
          <Empty title="Nothing to look back on yet" icon={<ChartLineUp size={20} />}>
            Trends need months before they mean anything. Connect a bank and this fills in as history
            arrives.
          </Empty>
        </Panel>
      ) : (
        <>
          <YearOverYear y={d.year_over_year} />

          <Panel className="mb-4">
            <PanelHeader
              title="Month by month"
              sub={`The last ${d.months.length} months. A shape rather than a quarter.`}
            />
            <div className="px-3 pb-3 pt-2"><MonthlyChart months={d.months} /></div>
          </Panel>

          <div className="grid gap-4 md:grid-cols-2">
            <Panel>
              <PanelHeader
                title="Year by year"
                sub="Part-years are marked — half a year drawn next to whole ones reads as a collapse in spending."
              />
              <ul className="mt-2 divide-y divide-line">
                {[...d.years].reverse().map((y) => (
                  <li key={y.year_number} className="flex items-center gap-3 px-5 py-2.5">
                    <CalendarBlank size={14} className="shrink-0 text-ink-3" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] text-ink">
                        {y.year_number}
                        {y.partial && (
                          <span className="ml-2 text-[11px] text-ink-3">
                            part year · {y.days_covered} days
                          </span>
                        )}
                      </div>
                      <div className="text-[12px] text-ink-3 tnum">
                        {y.transactions.toLocaleString()} transactions
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <Money value={Number(y.spent)} className="text-[14px] text-ink" />
                      <div className="text-[11px] text-ink-3">out</div>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader
                title="Where it has gone, all time"
                sub="Lifetime totals per merchant — the number nobody ever sees for themselves."
              />
              <ul className="mt-2 divide-y divide-line">
                {d.merchants.map((m) => (
                  <li key={m.name} className="flex items-center gap-3 px-5 py-2.5">
                    <MerchantAvatar logo={m.logo_url} icon={m.icon} name={m.name} size={28} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[14px] text-ink">{m.name}</div>
                      <div className="text-[12px] text-ink-3 tnum">
                        {m.times}× · {money(Number(m.average))} average
                      </div>
                    </div>
                    <Money value={Number(m.total)} className="shrink-0 text-[14px] text-ink" />
                  </li>
                ))}
              </ul>
            </Panel>
          </div>

          <div className="mt-4">
            <Review availableYears={d.available_years} />
          </div>
        </>
      )}
    </>
  )
}
