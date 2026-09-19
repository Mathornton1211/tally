import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, type CashFlow as CF } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { FilterBar } from '../components/Filters'
import { cx, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtMonth, money, moneyCompact, pct } from '../lib/format'
import { useFilters } from '../lib/range'

function Bars({ d }: { d: CF }) {
  const t = useChartTheme()
  const option = useMemo(() => ({
    animationDuration: 500,
    grid: { left: 4, right: 8, top: 16, bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: d.months.map((m) => fmtMonth(m.month)), axisTick: { show: false }, axisLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11 } },
    yAxis: { type: 'value', splitNumber: 4, axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact }, splitLine: { lineStyle: { color: t.grid } } },
    tooltip: {
      ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: t.grid + '80' } },
      formatter: (ps: { dataIndex: number }[]) => {
        const m = d.months[ps[0].dataIndex]
        const net = Number(m.net)
        const row = (c: string, l: string, v: string) => `<div style="display:flex;justify-content:space-between;gap:18px;align-items:center"><span style="display:flex;gap:6px;align-items:center">${c ? `<span style="width:8px;height:8px;border-radius:2px;background:${c}"></span>` : ''}${l}</span><b style="font-variant-numeric:tabular-nums">${v}</b></div>`
        return `<div style="color:${t.ink3};margin-bottom:4px">${fmtMonth(m.month, true)}</div>${row(t.s1, 'Income', money(Number(m.income)))}${row(t.s2, 'Spending', money(Number(m.spending)))}<div style="border-top:1px solid ${t.line};margin:6px 0 4px"></div>${row('', net >= 0 ? 'Saved' : 'Overspent', money(Math.abs(net)))}`
      },
    },
    series: [
      { name: 'Income', type: 'bar', data: d.months.map((m) => Number(m.income)), barMaxWidth: 22, barGap: '12%', itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] } },
      { name: 'Spending', type: 'bar', data: d.months.map((m) => Number(m.spending)), barMaxWidth: 22, itemStyle: { color: t.s2, borderRadius: [4, 4, 0, 0] } },
    ],
  }), [d, t])

  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 pt-5">
        <div className="grid grid-cols-3 gap-6 sm:gap-10">
          <div>
            <div className="text-[13px] text-ink-3">Income</div>
            <div className="mt-1 text-[24px] font-semibold tracking-tight text-ink"><Money value={Number(d.income)} size="lg" /></div>
          </div>
          <div>
            <div className="text-[13px] text-ink-3">Spending</div>
            <div className="mt-1 text-[24px] font-semibold tracking-tight text-ink"><Money value={Number(d.spending)} size="lg" /></div>
          </div>
          <div>
            <div className="text-[13px] text-ink-3">{Number(d.net) >= 0 ? 'Saved' : 'Overspent'}</div>
            <div className={cx('mt-1 text-[24px] font-semibold tracking-tight', Number(d.net) >= 0 ? 'text-positive' : 'text-negative')}><Money value={Math.abs(Number(d.net))} size="lg" /></div>
            <div className="text-[12px] text-ink-3">{pct(d.savings_rate)} of income</div>
          </div>
        </div>
        <div className="flex gap-4 text-[12px] text-ink-2">
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--series-1)' }} />Income</span>
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--series-2)' }} />Spending</span>
        </div>
      </div>
      <div className="px-3 pb-3 pt-3"><Chart option={option} height={280} ariaLabel="Monthly income and spending" /></div>
    </Panel>
  )
}

export default function CashFlow() {
  const f = useFilters('12m')
  const query = f.query()
  const q = useQuery({ queryKey: ['cashflow', query], queryFn: () => api.cashflow(query), placeholderData: keepPreviousData })
  const d = q.data

  return (
    <>
      <PageHeader title="Cash flow" sub="What came in, what went out, and what was left." />
      <FilterBar f={f} categories={false} />
      <ErrorNote error={q.error} />
      {!d ? <Skeleton className="h-[420px] rounded-[18px]" /> : (
        <div className="grid gap-4">
          <Bars d={d} />
          <Panel>
            <PanelHeader title="By month" />
            <div className="mt-3 overflow-x-auto pb-2">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead>
                  <tr className="border-b border-line text-left text-[12px] text-ink-3">
                    <th className="px-5 py-2 font-medium">Month</th>
                    <th className="px-5 py-2 text-right font-medium">Income</th>
                    <th className="px-5 py-2 text-right font-medium">Spending</th>
                    <th className="px-5 py-2 text-right font-medium">Net</th>
                    <th className="px-5 py-2 text-right font-medium">Saved</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {[...d.months].reverse().map((m) => (
                    <tr key={m.month} className="hover:bg-hover">
                      <td className="px-5 py-2.5 font-medium text-ink">{fmtMonth(m.month, true)}</td>
                      <td className="px-5 py-2.5 text-right text-ink tnum">{money(Number(m.income))}</td>
                      <td className="px-5 py-2.5 text-right text-ink tnum">{money(Number(m.spending))}</td>
                      <td className={cx('px-5 py-2.5 text-right font-medium tnum', Number(m.net) >= 0 ? 'text-positive' : 'text-negative')}>{Number(m.net) >= 0 ? '+' : ''}{money(Number(m.net))}</td>
                      <td className="px-5 py-2.5 text-right text-ink-2 tnum">{pct(m.savings_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </>
  )
}
