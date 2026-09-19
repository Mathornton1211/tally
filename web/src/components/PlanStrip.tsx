import { ArrowRight, CalendarX, Coins, Flag, Target } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { money0, relativeDays } from '../lib/format'
import { cx, Money } from './ui'

/**
 * The three numbers that matter when money is tight, at the top of the
 * dashboard: how long the cash lasts, what is due next, and when the cards are
 * gone. In growth mode the same strip switches to goal progress, because the
 * question has changed.
 */
export function PlanStrip() {
  const q = useQuery({ queryKey: ['plan'], queryFn: api.plan })
  const d = q.data
  if (!d) return null

  const rw = d.runway
  const nextOut = rw.events.find((e) => Number(e.amount) > 0)
  const payoff = d.payoff?.chosen
  const growth = d.mode.mode === 'growth'

  const tiles = growth
    ? [
      { icon: Coins, label: 'Cash on hand', value: <Money value={Number(rw.cash)} size="lg" />,
        note: `${rw.days_of_cover_at_current_spending} days of everyday spending`, tone: 'good' },
      ...d.goals.slice(0, 2).map((g) => ({
        icon: Target, label: g.name,
        value: <span>{Math.round((g.percent ?? 0) * 100)}%</span>,
        note: `${money0(Number(g.remaining))} to go`, tone: 'good' as const,
      })),
    ]
    : [
      { icon: Coins, label: rw.days_until_zero == null ? 'Cash on hand' : 'Cash runs out',
        value: rw.days_until_zero == null
          ? <Money value={Number(rw.cash)} size="lg" />
          : <span>{rw.days_until_zero} {rw.days_until_zero === 1 ? 'day' : 'days'}</span>,
        note: rw.days_until_zero == null
          ? `${rw.days_of_cover_at_current_spending} days of cover`
          : `${money0(Number(rw.cash))} left, about ${money0(Number(rw.daily_spending))} a day`,
        tone: rw.days_until_zero != null && rw.days_until_zero <= 21 ? 'bad' : 'plain' },
      { icon: CalendarX, label: 'Next payment',
        value: nextOut ? <Money value={Number(nextOut.amount)} size="lg" /> : <span>None</span>,
        note: nextOut ? `${nextOut.name} · ${relativeDays(nextOut.date)}` : 'nothing scheduled',
        tone: nextOut?.kind === 'overdue' ? 'bad' : 'plain' },
      { icon: Flag, label: 'Debt free',
        value: payoff?.payoff_date
          ? <span>{new Date(payoff.payoff_date).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}</span>
          : <span>—</span>,
        note: payoff?.months ? `${payoff.months} months at ${money0(Number(payoff.monthly_payment))}/mo` : 'set a payment on the Plan page',
        tone: 'plain' },
    ]

  return (
    <div className="grid gap-3 md:col-span-12 md:grid-cols-3">
      {tiles.map((t, i) => {
        const Icon = t.icon
        return (
          <Link key={i} to="/plan" className="panel rise group flex items-center gap-3 p-4 transition-colors hover:bg-hover"
                style={{ animationDelay: `${i * 40}ms` }}>
            <div className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
              t.tone === 'bad' ? 'bg-bad-soft text-negative' : t.tone === 'good' ? 'bg-accent-soft text-positive' : 'bg-hover text-ink-2')}>
              <Icon size={19} weight="fill" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[12px] text-ink-3">{t.label}</div>
              <div className={cx('text-[20px] font-semibold tracking-tight', t.tone === 'bad' ? 'text-negative' : 'text-ink')}>{t.value}</div>
              <div className="truncate text-[12px] text-ink-3">{t.note}</div>
            </div>
            <ArrowRight size={14} className="text-ink-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        )
      })}
    </div>
  )
}
