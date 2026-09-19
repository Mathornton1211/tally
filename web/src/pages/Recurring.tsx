import { ArrowRight, Copy, Repeat, TrendUp } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { api, type Stream } from '../api'
import { BillsPanel } from '../components/Bills'
import { cx, Empty, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { cadenceLabel, fmtShort, money, money0, relativeDays } from '../lib/format'

const SUBSCRIPTION_CATEGORIES = new Set(['entertainment', 'services', 'health', 'shopping'])

function StreamRow({ s }: { s: Stream }) {
  return (
    <li className={cx('flex items-center gap-3 px-5 py-3', !s.active && 'opacity-55')}>
      <MerchantAvatar logo={s.logo_url} icon="Repeat" name={s.name} size={38} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="truncate text-[14px] font-medium text-ink">{s.name}</span>
          {s.previous_amount != null && (
            <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">
              <TrendUp size={11} weight="bold" /> {money(Number(s.previous_amount))} <ArrowRight size={10} /> {money(Number(s.last_amount))}
            </span>
          )}
          {s.duplicate && (
            <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">
              <Copy size={11} weight="bold" /> Billed on 2 cards
            </span>
          )}
          {!s.active && <span className="rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">Stopped</span>}
        </div>
        <div className="mt-0.5 truncate text-[12px] text-ink-3">
          {cadenceLabel[s.cadence]} · {s.account_name} · since {fmtShort(s.first_date)}
        </div>
      </div>
      <div className="text-right">
        <Money value={Number(s.last_amount)} className={cx('text-[14px] font-medium', s.kind === 'income' ? 'text-positive' : 'text-ink')} />
        <div className="text-[12px] text-ink-3">{s.active ? relativeDays(s.next_date) : `Last ${fmtShort(s.last_date)}`}</div>
      </div>
    </li>
  )
}

function Section({ title, sub, items, delay }: { title: string; sub?: string; items: Stream[]; delay: number }) {
  if (!items.length) return null
  return (
    <Panel style={{ animationDelay: `${delay}ms` }}>
      <PanelHeader title={title} sub={sub} />
      <ul className="mt-2 divide-y divide-line pb-1">{items.map((s) => <StreamRow key={s.key + s.account_id} s={s} />)}</ul>
    </Panel>
  )
}

export default function Recurring() {
  const q = useQuery({ queryKey: ['recurring'], queryFn: api.recurring })
  const d = q.data
  const active = d?.streams.filter((s) => s.active) ?? []
  const expenses = active.filter((s) => s.kind === 'expense')
  const subs = expenses.filter((s) => SUBSCRIPTION_CATEGORIES.has(s.category))
  const bills = expenses.filter((s) => !SUBSCRIPTION_CATEGORIES.has(s.category))
  const income = active.filter((s) => s.kind === 'income')
  const soon = expenses.filter((s) => (s.days_until ?? 99) >= -2 && (s.days_until ?? 99) <= 7)
  const stopped = d?.streams.filter((s) => !s.active && s.kind === 'expense') ?? []
  const subsMonthly = subs.reduce((n, s) => n + Number(s.monthly_cost), 0)

  return (
    <>
      <PageHeader title="Recurring" sub="Found automatically from charges that repeat on a schedule." />
      <ErrorNote error={q.error} />
      {!d ? (
        <div className="grid gap-4"><Skeleton className="h-28 rounded-[18px]" /><Skeleton className="h-96 rounded-[18px]" /></div>
      ) : d.streams.length === 0 ? (
        <Panel><Empty title="Nothing recurring yet" icon={<Repeat size={18} />}>Tally needs to see a charge about three times before it calls it recurring.</Empty></Panel>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="grid grid-cols-2 gap-3 lg:col-span-12 lg:grid-cols-4">
            {[
              { label: 'Bills & subscriptions / mo', value: <Money value={Number(d.monthly_expense)} size="lg" /> },
              { label: 'Subscriptions alone / mo', value: <Money value={subsMonthly} size="lg" />, note: `${money0(subsMonthly * 12)} a year` },
              { label: 'Recurring income / mo', value: <Money value={Number(d.monthly_income)} size="lg" />, positive: true },
              { label: 'Needs a look', value: <span>{d.price_changes + d.duplicates}</span>, note: `${d.price_changes} price up · ${d.duplicates} duplicate` },
            ].map((x, i) => (
              <div key={i} className="panel rise px-4 py-3.5" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{x.label}</div>
                <div className={cx('mt-1 text-[22px] font-semibold tracking-tight', x.positive ? 'text-positive' : 'text-ink')}>{x.value}</div>
                {x.note && <div className="text-[12px] text-ink-3">{x.note}</div>}
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-4 lg:col-span-7">
            <Section title="Subscriptions" sub={`${subs.length} active`} items={subs} delay={80} />
            <Section title="Bills & loans" sub={`${bills.length} active`} items={bills} delay={120} />
            <div className="lg:col-span-12"><BillsPanel limit={6} /></div>
            <Section title="Stopped" sub="No charge in a while. Cancelled, or worth checking." items={stopped} delay={160} />
          </div>
          <div className="flex flex-col gap-4 lg:col-span-5">
            <Panel style={{ animationDelay: '100ms' }}>
              <PanelHeader title="Next 7 days" sub={soon.length ? `${money(soon.reduce((n, s) => n + Number(s.last_amount), 0))} going out` : 'Nothing due'} />
              <ul className="mt-2 divide-y divide-line pb-1">
                {soon.map((s) => (
                  <li key={s.key + s.account_id} className="flex items-center gap-3 px-5 py-2.5">
                    <div className="w-14 text-[12px] font-medium text-ink-2">{relativeDays(s.next_date)}</div>
                    <span className="flex-1 truncate text-[14px] text-ink">{s.name}</span>
                    <Money value={Number(s.last_amount)} className="text-[14px] font-medium text-ink" />
                  </li>
                ))}
              </ul>
            </Panel>
            <Section title="Income" items={income} delay={140} />
          </div>
        </div>
      )}
    </>
  )
}
