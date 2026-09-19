import { ChartDonut, DownloadSimple } from '@phosphor-icons/react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api, qs, type Spending as S } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { FilterBar } from '../components/Filters'
import { CategoryIcon } from '../components/icons'
import { cx, Delta, Empty, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtMonth, fmtShort, iso, money, money0, moneyCompact, parseDate } from '../lib/format'
import { useFilters, type Filters } from '../lib/range'

function Trend({ d, f }: { d: S; f: Filters }) {
  const t = useChartTheme()
  const option = useMemo(() => {
    const labels = d.series.map((p) => (d.bucket === 'month' ? fmtMonth(p.bucket) : fmtShort(p.bucket)))
    return {
      animationDuration: 500,
      grid: { left: 4, right: 8, top: 12, bottom: 4, containLabel: true },
      xAxis: {
        type: 'category', data: labels, axisTick: { show: false },
        axisLine: { lineStyle: { color: t.grid } },
        axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, hideOverlap: true },
      },
      yAxis: { type: 'value', splitNumber: 4, axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact }, splitLine: { lineStyle: { color: t.grid } } },
      tooltip: {
        ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: t.grid + '80' } },
        formatter: (ps: { dataIndex: number; value: number }[]) => {
          const p = d.series[ps[0].dataIndex]
          const title = d.bucket === 'month' ? fmtMonth(p.bucket, true) : parseDate(p.bucket).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
          return `<div style="color:${t.ink3}">${title}</div><b style="font-variant-numeric:tabular-nums">${money(Number(p.amount))}</b>${d.bucket === 'month' ? `<div style="color:${t.ink3};margin-top:2px;font-size:11px">Click to see this month</div>` : ''}`
        },
      },
      series: [{
        type: 'bar', data: d.series.map((p) => Number(p.amount)), barMaxWidth: 36, barCategoryGap: '28%',
        itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] },
        emphasis: { itemStyle: { color: t.s1, opacity: 0.85 } },
        cursor: d.bucket === 'month' ? 'pointer' : 'default',
      }],
    }
  }, [d, t])

  const drill = (i: number) => {
    if (d.bucket !== 'month') return
    const m = parseDate(d.series[i].bucket)
    f.setCustom(iso(m), iso(new Date(m.getFullYear(), m.getMonth() + 1, 0)))
  }

  return (
    <Panel className="lg:col-span-12">
      <div className="flex flex-wrap items-end justify-between gap-4 px-5 pt-5">
        <div>
          <div className="text-[13px] font-medium text-ink-3">Total spent · {fmtShort(d.start)} – {fmtShort(d.end)}</div>
          <div className="mt-1 text-[40px] font-semibold leading-none tracking-tight text-ink"><Money value={Number(d.total)} size="hero" /></div>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-3">
            <Delta value={Number(d.total)} previous={Number(d.previous)} invert label={`${fmtShort(d.previous_start)} – ${fmtShort(d.previous_end)}`} />
            <span>{d.count.toLocaleString()} transactions</span>
          </div>
          {/* What could actually be cut, which is the only useful split when money is tight. */}
          {Number(d.total) > 0 && (
            <div className="mt-3 max-w-md">
              <div className="flex h-2 overflow-hidden rounded-full bg-hover">
                <div className="h-full bg-series-1" style={{ width: `${(Number(d.essential) / Number(d.total)) * 100}%` }} />
                <div className="h-full bg-series-2" style={{ width: `${(Number(d.flexible) / Number(d.total)) * 100}%` }} />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 text-[12px] text-ink-3">
                <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-series-1" />
                  {money0(Number(d.essential))} essentials</span>
                <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-series-2" />
                  {money0(Number(d.flexible))} flexible, the part you can actually cut</span>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="px-3 pb-3 pt-2">
        <Chart option={option} height={240} onClick={(p) => drill(p.dataIndex)} ariaLabel={`Spending by ${d.bucket}`} />
      </div>
    </Panel>
  )
}

function Categories({ d, f }: { d: S; f: Filters }) {
  const total = Number(d.total) || 1
  const max = Math.max(...d.categories.map((c) => Number(c.amount)), 1)
  const selected = f.categories
  return (
    <Panel className="lg:col-span-7">
      <PanelHeader title="By category" sub="Click one to focus the page on it" />
      <ul className="mt-3 px-3 pb-4">
        {d.categories.map((c) => {
          const amt = Number(c.amount)
          const on = selected.includes(c.key)
          return (
            <li key={c.key}>
              <button onClick={() => f.setList('category', on ? selected.filter((k) => k !== c.key) : [c.key])}
                      className={cx('grid w-full grid-cols-[34px_1fr_auto] items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-hover', on && 'bg-accent-soft hover:bg-accent-soft')}>
                <div className="flex h-[34px] w-[34px] items-center justify-center rounded-full bg-hover text-ink-2"><CategoryIcon name={c.icon} size={17} /></div>
                <div className="min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="truncate text-[14px] font-medium text-ink">{c.label}</span>
                    <span className="shrink-0 text-[12px] text-ink-3 tnum">{Math.round((amt / total) * 100)}%</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-hover">
                    <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${(amt / max) * 100}%`, background: 'var(--series-1)' }} />
                  </div>
                </div>
                <div className="w-28 text-right">
                  <Money value={amt} className="text-[14px] font-medium text-ink" />
                  <div className="text-[11px]"><Delta value={amt} previous={Number(c.previous) || null} invert /></div>
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

function Merchants({ d, f }: { d: S; f: Filters }) {
  return (
    <Panel className="lg:col-span-5">
      <PanelHeader title="Top merchants" />
      <ol className="mt-3 divide-y divide-line pb-2">
        {d.merchants.map((m, i) => (
          <li key={m.name}>
            <Link to={`/transactions${qs({ ...f.query(), q: m.name, range: 'custom' })}`}
                  className="flex items-center gap-3 px-5 py-2.5 hover:bg-hover">
              <span className="w-4 text-[12px] text-ink-3 tnum">{i + 1}</span>
              <MerchantAvatar logo={m.logo_url} icon={m.icon} name={m.name} size={32} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-medium text-ink">{m.name}</div>
                <div className="text-[12px] text-ink-3">{m.count} {m.count === 1 ? 'visit' : 'visits'} · avg {money0(Number(m.amount) / m.count)}</div>
              </div>
              <Money value={Number(m.amount)} className="text-[14px] font-medium text-ink" />
            </Link>
          </li>
        ))}
      </ol>
    </Panel>
  )
}

export default function Spending() {
  const f = useFilters('6m')
  const query = f.query()
  const q = useQuery({ queryKey: ['spending', query], queryFn: () => api.spending(query), placeholderData: keepPreviousData })
  const d = q.data

  return (
    <>
      <PageHeader title="Spending" sub="Transfers and card payments are left out so nothing is counted twice.">
        <a href={`/api/export/transactions.csv?start=${f.start}&end=${f.end}`}
           className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-[13px] font-medium text-ink hover:bg-hover">
          <DownloadSimple size={14} /> CSV
        </a>
        <a href={`/api/export/tax-pack.zip?year=${new Date(f.end).getFullYear()}`}
           className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-[13px] font-medium text-ink hover:bg-hover">
          <DownloadSimple size={14} /> Tax pack
        </a>
      </PageHeader>
      <FilterBar f={f} />
      <ErrorNote error={q.error} />
      {!d ? (
        <div className="grid gap-4 lg:grid-cols-12">
          <Skeleton className="h-[360px] rounded-[18px] lg:col-span-12" />
          <Skeleton className="h-[420px] rounded-[18px] lg:col-span-7" />
          <Skeleton className="h-[420px] rounded-[18px] lg:col-span-5" />
        </div>
      ) : d.count === 0 ? (
        <Panel><Empty title="No spending in this range" icon={<ChartDonut size={18} />}>Pick a wider range or clear filters.</Empty></Panel>
      ) : (
        <div className={cx('grid gap-4 lg:grid-cols-12 transition-opacity', q.isFetching && 'opacity-70')}>
          <Trend d={d} f={f} />
          <Categories d={d} f={f} />
          <Merchants d={d} f={f} />
        </div>
      )}
    </>
  )
}
