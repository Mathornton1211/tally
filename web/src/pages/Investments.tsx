import { ArrowsClockwise, Bank, ChartPieSlice, Info } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, type Portfolio } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtShort, money, money0, pct } from '../lib/format'

const TYPE_LABEL: Record<string, string> = {
  equity: 'Stocks', etf: 'ETFs', 'mutual fund': 'Mutual funds', cash: 'Cash',
  fixed_income: 'Bonds', derivative: 'Options', other: 'Other',
}

function Allocation({ d }: { d: Portfolio }) {
  const t = useChartTheme()
  const option = useMemo(() => ({
    animationDuration: 500,
    grid: { left: 4, right: 12, top: 6, bottom: 4, containLabel: true },
    xAxis: { type: 'value', axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false } },
    yAxis: {
      type: 'category', inverse: true, data: d.allocation.map((a) => TYPE_LABEL[a.type] ?? a.type),
      axisTick: { show: false }, axisLine: { show: false },
      axisLabel: { color: t.ink2, fontFamily: t.font, fontSize: 12 },
    },
    tooltip: {
      ...tooltipBase(t), trigger: 'item',
      formatter: (p: { dataIndex: number }) => {
        const a = d.allocation[p.dataIndex]
        return `<b>${TYPE_LABEL[a.type] ?? a.type}</b><br/>${money(Number(a.value))} · ${pct(a.percent, 1)}`
      },
    },
    series: [{
      type: 'bar', data: d.allocation.map((a) => Number(a.value)), barMaxWidth: 18,
      itemStyle: { color: t.s1, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right', color: t.ink2, fontFamily: t.font, fontSize: 11,
               formatter: (p: { dataIndex: number }) => pct(d.allocation[p.dataIndex].percent, 0) },
    }],
  }), [d, t])
  return <Chart option={option} height={Math.max(120, d.allocation.length * 34)} ariaLabel="Allocation by asset type" />
}

export default function Investments() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['investments'], queryFn: api.investments })
  const sync = useMutation({ mutationFn: api.syncInvestments, onSettled: () => qc.invalidateQueries() })
  const d = q.data

  return (
    <>
      <PageHeader title="Investments" sub="Brokerage and retirement accounts, and what is inside them.">
        <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
          <ArrowsClockwise size={14} className={sync.isPending ? 'animate-spin' : ''} /> Refresh holdings
        </Button>
      </PageHeader>
      <ErrorNote error={q.error} />
      {!d ? <Skeleton className="h-96 rounded-[18px]" /> : !d.has_data ? (
        <Panel><Empty title="No holdings yet" icon={<ChartPieSlice size={20} />}>
          Connect a brokerage or 401(k) on the Accounts page. Many providers share holdings through Plaid;
          some only share the balance, which still counts toward net worth.
        </Empty></Panel>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <Panel className="lg:col-span-7">
            <div className="grid gap-4 px-5 py-5 sm:grid-cols-3">
              <div>
                <div className="text-[13px] text-ink-3">Total value</div>
                <div className="mt-1 text-[34px] font-semibold leading-none tracking-tight text-ink">
                  <Money value={Number(d.total_value)} size="hero" />
                </div>
              </div>
              <div>
                <div className="text-[13px] text-ink-3">Gain on what you paid</div>
                <div className={cx('mt-1 text-[24px] font-semibold tracking-tight', Number(d.gain) >= 0 ? 'text-positive' : 'text-negative')}>
                  <Money value={Number(d.gain)} size="lg" showPlus />
                </div>
                <div className="text-[12px] text-ink-3">
                  {pct(d.gain_percent, 1)} on {money0(Number(d.cost_basis))} invested
                  {d.basis_coverage != null && d.basis_coverage < 0.99 && ` · covers ${pct(d.basis_coverage, 0)} of holdings`}
                </div>
              </div>
              <div>
                <div className="text-[13px] text-ink-3">Added this year</div>
                <div className="mt-1 text-[24px] font-semibold tracking-tight text-ink"><Money value={Number(d.contributions_ytd)} size="lg" /></div>
                <div className="text-[12px] text-ink-3">
                  retirement {money0(Number(d.retirement_value))} · taxable {money0(Number(d.taxable_value))}
                </div>
              </div>
            </div>
          </Panel>

          <Panel className="lg:col-span-5">
            <PanelHeader title="Mix" sub="By asset type" />
            <div className="px-3 pb-3 pt-2"><Allocation d={d} /></div>
          </Panel>

          <Panel className="lg:col-span-7">
            <PanelHeader title="Holdings" sub={`${d.holdings.length} positions`} />
            <div className="mt-2 overflow-x-auto pb-2">
              <table className="w-full min-w-[520px] text-[13px]">
                <thead>
                  <tr className="border-b border-line text-left text-[12px] text-ink-3">
                    <th className="px-5 py-2 font-medium">Position</th>
                    <th className="px-5 py-2 text-right font-medium">Shares</th>
                    <th className="px-5 py-2 text-right font-medium">Value</th>
                    <th className="px-5 py-2 text-right font-medium">Gain</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {d.holdings.map((h) => (
                    <tr key={h.account_id + h.security_id} className="hover:bg-hover">
                      <td className="px-5 py-2.5">
                        <div className="font-medium text-ink">{h.ticker ?? h.security_name}</div>
                        <div className="truncate text-[12px] text-ink-3">
                          {h.ticker ? h.security_name : TYPE_LABEL[h.security_type ?? ''] ?? h.security_type} · {h.account_name}
                          {h.weight != null && ` · ${pct(h.weight, 0)}`}
                        </div>
                      </td>
                      <td className="px-5 py-2.5 text-right tnum text-ink-2">{Number(h.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
                      <td className="px-5 py-2.5 text-right tnum text-ink">{money(Number(h.value))}</td>
                      <td className={cx('px-5 py-2.5 text-right tnum', h.gain == null ? 'text-ink-3' : Number(h.gain) >= 0 ? 'text-positive' : 'text-negative')}>
                        {h.gain == null ? '—' : `${Number(h.gain) >= 0 ? '+' : ''}${money(Number(h.gain))}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="flex flex-col gap-4 lg:col-span-5">
            <Panel>
              <PanelHeader title="Accounts" />
              <ul className="mt-2 divide-y divide-line pb-1">
                {d.accounts.map((a) => (
                  <li key={a.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-hover text-ink-2"><Bank size={17} /></div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[14px] font-medium text-ink">
                        {a.name}{a.mask && <span className="text-ink-3"> ··{a.mask}</span>}
                        {a.retirement && <span className="ml-2 rounded-full bg-hover px-1.5 py-0.5 text-[11px] text-ink-2">retirement</span>}
                      </div>
                      <div className="text-[12px] text-ink-3">
                        {a.holdings} position{a.holdings === 1 ? '' : 's'}
                        {Number(a.contributions_ytd) > 0 && ` · ${money0(Number(a.contributions_ytd))} added this year`}
                      </div>
                    </div>
                    <Money value={Number(a.value)} className="text-[14px] font-semibold text-ink" />
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel>
              <PanelHeader title="Recent activity" />
              <ul className="mt-2 divide-y divide-line pb-1">
                {d.recent.slice(0, 8).map((r, i) => (
                  <li key={i} className="flex items-center gap-3 px-5 py-2.5">
                    <div className="w-14 shrink-0 text-[12px] text-ink-3">{fmtShort(r.date)}</div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] text-ink">{r.ticker ?? r.security_name ?? r.name}</div>
                      <div className="truncate text-[12px] text-ink-3">{r.subtype ?? r.type} · {r.account_name}</div>
                    </div>
                    <Money value={Number(r.amount)} className="text-[13px] text-ink" />
                  </li>
                ))}
              </ul>
              {d.recent.length === 0 && <Empty title="No activity in the last year" />}
            </Panel>
          </div>

          <div className="flex items-start gap-2 rounded-2xl border border-line bg-surface px-4 py-3 text-[12px] text-ink-3 lg:col-span-12">
            <Info size={14} className="mt-0.5 shrink-0" />
            Values and cost basis come from your provider through Plaid, refreshed on each sync. Tally reports what
            you hold; it does not recommend trades or allocations, and it cannot place one.
          </div>
        </div>
      )}
    </>
  )
}
