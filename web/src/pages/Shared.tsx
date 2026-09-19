import { CalendarBlank, LockKey } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { api, type SharedView } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { CategoryIcon } from '../components/icons'
import { cx, Money, Skeleton } from '../components/ui'
import { fmtMonth, fmtShort, money, money0 } from '../lib/format'

/**
 * The page somebody outside the household opens. No sidebar, no navigation and
 * no way into the rest of the app -- the reader is not a user here, they are
 * holding one narrow window onto one date range.
 *
 * Printed as often as it is read, so it carries its own print rules.
 */

const PRINT_CSS = `
@media print {
  @page { margin: 16mm; }
  html, body { background: #fff !important; }
  .sheet { background: #fff !important; border: 0 !important; box-shadow: none !important; }
  .no-print { display: none !important; }
  .print-break { break-inside: avoid; }
}
`

function Wordmark() {
  return (
    <div className="flex items-center gap-2">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="9" fill="var(--accent)" />
        <path d="M9 11.5h14M16 11.5V23" stroke="var(--accent-ink)" strokeWidth="3.2" strokeLinecap="round" />
      </svg>
      <span className="text-[14px] font-semibold tracking-tight text-ink">Tally</span>
    </div>
  )
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-[100dvh] bg-page">
      <style>{PRINT_CSS}</style>
      <header className="border-b border-line px-4 py-3 md:px-8">
        <div className="mx-auto flex max-w-[1000px] items-center justify-between">
          <Wordmark />
          <span className="text-[12px] text-ink-3">Shared report</span>
        </div>
      </header>
      <main className="px-4 py-6 md:px-8 md:py-10">
        <div className="mx-auto max-w-[1000px]">{children}</div>
      </main>
    </div>
  )
}

function Months({ months }: { months: SharedView['months'] }) {
  const t = useChartTheme()
  const option = useMemo(() => ({
    grid: { left: 8, right: 8, top: 16, bottom: 22, containLabel: true },
    tooltip: {
      trigger: 'axis',
      ...tooltipBase(t),
      valueFormatter: (v: number) => money(v),
    },
    xAxis: {
      type: 'category',
      data: months.map((m) => fmtMonth(m.month)),
      axisLine: { lineStyle: { color: t.grid } },
      axisTick: { show: false },
      axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: t.grid } },
      axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: (v: number) => money0(v) },
    },
    series: [{
      name: 'Spent',
      type: 'bar',
      data: months.map((m) => Number(m.spent)),
      itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] },
      barMaxWidth: 28,
    }],
  }), [months, t])

  return <Chart option={option} height={200} ariaLabel="Spending by month" />
}

function Totals({ d }: { d: SharedView }) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[
        { label: 'Money out', value: Number(d.spent) },
        { label: 'Money in', value: Number(d.earned) },
        { label: 'Net', value: Number(d.net) },
        { label: 'Transactions', value: null, raw: String(d.transactions) },
      ].map((t) => (
        <div key={t.label} className="sheet rounded-2xl border border-line bg-surface px-4 py-3">
          <div className="text-[12px] text-ink-3">{t.label}</div>
          <div className={cx('mt-0.5 text-[20px] font-semibold tracking-tight tnum',
            t.value != null && t.label === 'Net' && t.value < 0 ? 'text-negative' : 'text-ink')}>
            {t.raw ?? <Money value={t.value as number} size="lg" />}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Shared() {
  const { token = '' } = useParams<{ token: string }>()
  const q = useQuery({
    queryKey: ['shared', token],
    queryFn: () => api.readShared(token),
    retry: false,
  })
  const d = q.data

  if (q.isError) {
    return (
      <Frame>
        <div className="sheet mx-auto max-w-[460px] rounded-2xl border border-line bg-surface px-6 py-10 text-center">
          <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-hover text-ink-2">
            <LockKey size={20} />
          </div>
          <h1 className="text-[16px] font-semibold text-ink">This link is no longer open</h1>
          <p className="mx-auto mt-1.5 max-w-[42ch] text-[13px] text-ink-3">
            It has either expired or been turned off by the person who sent it. Ask them for a new one —
            there is nothing to fix at this end.
          </p>
        </div>
      </Frame>
    )
  }

  if (!d) {
    return (
      <Frame>
        <Skeleton className="mb-4 h-16 rounded-2xl" />
        <Skeleton className="mb-4 h-24 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </Frame>
    )
  }

  const expenses = d.categories.filter((c) => Number(c.spent) > 0)
  const incomes = d.categories.filter((c) => Number(c.earned) > 0)

  return (
    <Frame>
      <div className="mb-5">
        <h1 className="text-[24px] font-semibold tracking-tight text-ink">{d.label}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-3">
          <span className="inline-flex items-center gap-1.5">
            <CalendarBlank size={13} /> {fmtShort(d.start)} – {fmtShort(d.end)}
          </span>
          <span>{d.detail === 'transactions' ? 'Totals and every transaction' : 'Totals and categories'}</span>
          {d.expires_on && <span className="no-print">Link stops working {fmtShort(d.expires_on)}</span>}
        </div>
      </div>

      <Totals d={d} />

      {d.months.length > 1 && (
        <section className="sheet print-break mb-4 rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-1 text-[15px] font-semibold tracking-tight text-ink">By month</h2>
          <Months months={d.months} />
        </section>
      )}

      <section className="sheet print-break mb-4 rounded-2xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-[15px] font-semibold tracking-tight text-ink">Where it went</h2>
        {expenses.length === 0 ? (
          <p className="text-[13px] text-ink-3">No spending in this period.</p>
        ) : (
          <ul className="divide-y divide-line">
            {expenses.map((c) => (
              <li key={c.category} className="flex items-center gap-3 py-2.5">
                <CategoryIcon name={c.icon} size={16} className="shrink-0 text-ink-3" />
                <span className="min-w-0 flex-1 truncate text-[14px] text-ink">{c.label}</span>
                <span className="shrink-0 text-[12px] text-ink-3 tnum">{c.count}</span>
                <Money value={Number(c.spent)} className="w-24 shrink-0 text-right text-[14px] text-ink" />
              </li>
            ))}
          </ul>
        )}
      </section>

      {incomes.length > 0 && (
        <section className="sheet print-break mb-4 rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-[15px] font-semibold tracking-tight text-ink">What came in</h2>
          <ul className="divide-y divide-line">
            {incomes.map((c) => (
              <li key={c.category} className="flex items-center gap-3 py-2.5">
                <CategoryIcon name={c.icon} size={16} className="shrink-0 text-ink-3" />
                <span className="min-w-0 flex-1 truncate text-[14px] text-ink">{c.label}</span>
                <span className="shrink-0 text-[12px] text-ink-3 tnum">{c.count}</span>
                <Money value={Number(c.earned)} className="w-24 shrink-0 text-right text-[14px] text-positive" />
              </li>
            ))}
          </ul>
        </section>
      )}

      {d.tags.length > 0 && (
        <section className="sheet print-break mb-4 rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-[15px] font-semibold tracking-tight text-ink">Tagged</h2>
          <ul className="flex flex-wrap gap-2">
            {d.tags.map((t) => (
              <li key={t.tag} className="rounded-full border border-line px-3 py-1.5 text-[13px] text-ink">
                {t.tag} <span className="text-ink-3">{money0(Number(t.total))} · {t.count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {d.rows && (
        <section className="sheet rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-3 text-[15px] font-semibold tracking-tight text-ink">
            Transactions <span className="font-normal text-ink-3">({d.rows.length})</span>
          </h2>
          <div className="-mx-2 overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-line text-left text-[12px] text-ink-3">
                  <th className="px-2 py-2 font-medium">Date</th>
                  <th className="px-2 py-2 font-medium">Description</th>
                  <th className="px-2 py-2 font-medium">Category</th>
                  <th className="px-2 py-2 font-medium">Account</th>
                  <th className="px-2 py-2 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.id} className="border-b border-line last:border-0">
                    <td className="whitespace-nowrap px-2 py-2 text-ink-3 tnum">{fmtShort(r.date)}</td>
                    <td className="px-2 py-2 text-ink">
                      {r.display_name}
                      {r.tags.length > 0 && (
                        <span className="ml-1.5 text-[11px] text-ink-3">{r.tags.join(' · ')}</span>
                      )}
                      {r.note && <span className="block text-[12px] text-ink-3">{r.note}</span>}
                    </td>
                    <td className="px-2 py-2 text-ink-2">{r.category_label}</td>
                    <td className="px-2 py-2 text-ink-3">{r.account_name}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-right tnum">
                      <Money value={Number(r.amount)} className={r.kind === 'income' ? 'text-positive' : 'text-ink'} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <p className="mt-5 text-[12px] text-ink-3">
        Read-only, and limited to {fmtShort(d.start)} – {fmtShort(d.end)}. Figures come straight from the
        connected bank accounts.
      </p>
    </Frame>
  )
}
