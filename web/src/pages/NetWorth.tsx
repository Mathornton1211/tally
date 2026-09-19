import { Info } from '@phosphor-icons/react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, type NetWorth as NW } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { DateRangePicker } from '../components/Filters'
import { cx, Delta, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { accountTypeLabel, fmtShort, money, moneyCompact, parseDate } from '../lib/format'
import { useFilters } from '../lib/range'
import { weekly } from './Dashboard'

function Trend({ d: raw }: { d: NW }) {
  const t = useChartTheme()
  // Daily points zigzag between paydays and card payments; past ~3 months plot weekly.
  const d = useMemo(() => (raw.series.length > 92 ? { ...raw, series: weekly(raw.series) } : raw), [raw])
  const option = useMemo(() => ({
    animationDuration: 600,
    grid: { left: 4, right: 12, top: 16, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category', boundaryGap: false, data: d.series.map((p) => p.date), axisTick: { show: false },
      axisLine: { lineStyle: { color: t.grid } },
      axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, hideOverlap: true, formatter: (v: string) => fmtShort(v) },
    },
    yAxis: { type: 'value', scale: true, splitNumber: 4, axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact }, splitLine: { lineStyle: { color: t.grid } } },
    tooltip: {
      ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: t.line } },
      formatter: (ps: { dataIndex: number }[]) => {
        const p = d.series[ps[0].dataIndex]
        return `<div style="color:${t.ink3};margin-bottom:4px">${parseDate(p.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</div>
          <div style="font-size:15px;font-weight:600;font-variant-numeric:tabular-nums">${money(Number(p.net_worth))}</div>
          <div style="color:${t.ink3};font-variant-numeric:tabular-nums">Assets ${money(Number(p.assets))} · Debts ${money(Number(p.liabilities))}</div>`
      },
    },
    series: [{
      type: 'line', data: d.series.map((p) => Number(p.net_worth)), showSymbol: false, smooth: 0.2,
      lineStyle: { width: 2.5, color: t.s1 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: t.s1 + '30' }, { offset: 1, color: t.s1 + '00' }] } },
    }],
  }), [d, t])

  const last = d.series[d.series.length - 1]
  const first = d.series[0]
  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-6 px-5 pt-5">
        <div>
          <div className="text-[13px] font-medium text-ink-3">Net worth</div>
          <div className="mt-1 text-[40px] font-semibold leading-none tracking-tight text-ink"><Money value={Number(last.net_worth)} size="hero" /></div>
          <div className="mt-2"><Delta value={Number(last.net_worth)} previous={Number(first.net_worth)} label={fmtShort(first.date)} /></div>
        </div>
        <div className="grid grid-cols-2 gap-8">
          <div><div className="text-[13px] text-ink-3">Assets</div><div className="mt-1 text-[20px] font-semibold text-ink"><Money value={Number(last.assets)} size="lg" /></div></div>
          <div><div className="text-[13px] text-ink-3">Debts</div><div className="mt-1 text-[20px] font-semibold text-ink"><Money value={Number(last.liabilities)} size="lg" /></div></div>
        </div>
      </div>
      <div className="px-3 pb-2 pt-3"><Chart option={option} height={300} ariaLabel="Net worth over time" /></div>
      <div className="flex items-center gap-1.5 border-t border-line px-5 py-2.5 text-[12px] text-ink-3">
        <Info size={13} /> History before your first sync is estimated by replaying transactions backward from today's balances.
      </div>
    </Panel>
  )
}

const ORDER = ['depository', 'investment', 'other', 'credit', 'loan']

export default function NetWorth() {
  const f = useFilters('6m')
  const q = useQuery({ queryKey: ['networth', f.start, f.end], queryFn: () => api.networth({ start: f.start, end: f.end }), placeholderData: keepPreviousData })
  const d = q.data

  return (
    <>
      <PageHeader title="Net worth"><DateRangePicker f={f} /></PageHeader>
      <ErrorNote error={q.error} />
      {!d ? <Skeleton className="h-[440px] rounded-[18px]" /> : (
        <div className="grid gap-4">
          <Trend d={d} />
          <div className="grid gap-4 md:grid-cols-2">
            {ORDER.map((type) => {
              const accts = d.accounts.filter((a) => a.type === type)
              if (!accts.length) return null
              const liability = type === 'credit' || type === 'loan'
              const total = accts.reduce((s, a) => s + Number(a.current_balance || 0), 0)
              return (
                <Panel key={type}>
                  <PanelHeader title={accountTypeLabel[type]} action={<Money value={liability ? -total : total} className="text-[15px] font-semibold text-ink" />} />
                  <ul className="mt-2 divide-y divide-line pb-1">
                    {accts.map((a) => (
                      <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                        <div className="min-w-0">
                          <div className="truncate text-[14px] text-ink">{a.name}{a.mask && <span className="text-ink-3"> ··{a.mask}</span>}</div>
                          <div className="text-[12px] text-ink-3">{a.institution}</div>
                        </div>
                        <div className="text-right">
                          <Money value={Number(a.current_balance || 0)} className="text-[14px] font-medium text-ink" />
                          {a.change != null && Math.abs(Number(a.change)) >= 1 && (
                            <div className={cx('text-[12px] tnum', Number(a.change) >= 0 ? 'text-positive' : 'text-negative')}>
                              {Number(a.change) >= 0 ? '+' : '-'}{money(Math.abs(Number(a.change)))}
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}
