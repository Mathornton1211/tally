import { ArrowRight, Bank, Copy, CreditCard, Lightbulb, PiggyBank, Receipt, SortDescending, TrendUp, Wallet } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Recommendation } from '../api'
import { cx, Empty, ErrorNote, Money, PageHeader, Panel, Skeleton } from '../components/ui'
import { money0 } from '../lib/format'

const KIND: Record<string, { icon: typeof Bank; label: string; to?: string }> = {
  cash_drag: { icon: PiggyBank, label: 'Earn more on cash', to: '/accounts' },
  card_interest: { icon: CreditCard, label: 'Interest', to: '/fees' },
  debt_order: { icon: SortDescending, label: 'Debt plan', to: '/accounts' },
  idle_account: { icon: Wallet, label: 'Consolidate', to: '/accounts' },
  duplicate_subscription: { icon: Copy, label: 'Subscriptions', to: '/recurring' },
  price_increase: { icon: TrendUp, label: 'Subscriptions', to: '/recurring' },
  fees: { icon: Receipt, label: 'Fees', to: '/fees' },
  consolidate_checking: { icon: Bank, label: 'Consolidate', to: '/accounts' },
}

function Rec({ r, i }: { r: Recommendation; i: number }) {
  const k = KIND[r.kind] ?? { icon: Lightbulb, label: 'Insight' }
  const Icon = k.icon
  const to = r.link ?? k.to
  const impact = Number(r.impact)
  return (
    <Panel className="flex flex-col" style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}>
      <div className="flex items-start gap-3 px-5 pt-5">
        <div className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
          r.priority === 'high' ? 'bg-accent-soft text-positive' : 'bg-hover text-ink-2')}>
          <Icon size={19} weight={r.priority === 'high' ? 'fill' : 'regular'} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-ink-3">{k.label}</div>
          <h3 className="mt-0.5 text-[16px] font-semibold leading-snug tracking-tight text-ink">{r.title}</h3>
        </div>
        {impact > 0 && (
          <div className="text-right">
            <div className="text-[18px] font-semibold tracking-tight text-positive"><Money value={impact} size="lg" /></div>
            <div className="text-[11px] text-ink-3">per year</div>
          </div>
        )}
      </div>
      <p className="px-5 pt-2 text-[14px] leading-relaxed text-ink-2">{r.detail}</p>
      <div className="mt-auto flex items-center justify-between gap-3 px-5 pb-4 pt-3">
        <span className="text-[12px] text-ink-3">{r.assumptions.join(' · ')}</span>
        {to && (
          <Link to={to} className="inline-flex shrink-0 items-center gap-1 text-[13px] font-medium text-ink hover:text-accent">
            Details <ArrowRight size={13} weight="bold" />
          </Link>
        )}
      </div>
    </Panel>
  )
}

export default function Insights() {
  const q = useQuery({ queryKey: ['insights'], queryFn: api.insights })
  const d = q.data
  const withImpact = d?.recommendations.filter((r) => Number(r.impact) > 0) ?? []
  const other = d?.recommendations.filter((r) => Number(r.impact) <= 0) ?? []

  return (
    <>
      <PageHeader title="Insights" sub="Where money is leaking, and which accounts to keep, merge, or close." />
      <ErrorNote error={q.error} />
      {!d ? (
        <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-48 rounded-[18px]" />)}</div>
      ) : d.recommendations.length === 0 ? (
        <Panel><Empty title="Nothing to fix" icon={<Lightbulb size={20} />}>No fees, idle accounts, or duplicate subscriptions found. Nice.</Empty></Panel>
      ) : (
        <>
          <Panel className="mb-4">
            <div className="flex flex-wrap items-end justify-between gap-4 px-5 py-5">
              <div>
                <div className="text-[13px] text-ink-3">Found this year, if you act on everything below</div>
                <div className="mt-1 text-[40px] font-semibold leading-none tracking-tight text-positive"><Money value={Number(d.total_impact)} size="hero" /></div>
                <div className="mt-2 text-[13px] text-ink-3">{d.recommendations.length} suggestions · about {money0(Number(d.total_impact) / 12)} a month</div>
              </div>
              <p className="max-w-[46ch] text-[13px] leading-relaxed text-ink-3">
                Estimates use today's balances and the last 90 days of interest. Add APRs and APYs in Accounts to replace estimates with exact figures.
              </p>
            </div>
          </Panel>
          <div className="grid gap-4 md:grid-cols-2">
            {withImpact.map((r, i) => <Rec key={r.kind + r.title} r={r} i={i} />)}
          </div>
          {other.length > 0 && (
            <>
              <h2 className="mb-3 mt-8 text-[15px] font-semibold text-ink">Also worth knowing</h2>
              <div className="grid gap-4 md:grid-cols-2">
                {other.map((r, i) => <Rec key={r.kind + r.title} r={r} i={i} />)}
              </div>
            </>
          )}
        </>
      )}
    </>
  )
}
