import {
  ArrowsClockwise, Bell, ChartDonut, ChartLineUp, DotsThreeOutline, House, Lightbulb, ListBullets, Receipt,
  Binoculars, ChartPieSlice, Compass, Flag, Funnel, MagnifyingGlass, PiggyBank, SignOut,
  SlidersHorizontal, Target, Receipt as ReceiptIcon, Repeat, Sparkle, TrendUp, UsersThree,
  Wallet, ClockCounterClockwise, ClipboardText,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { ago } from '../lib/format'
import { cx, usePopover } from './ui'

type NavItem = { to: string; label: string; icon: typeof House; end?: boolean
                 badge?: 'alerts' | 'review' }

const SECTIONS: { title?: string; items: NavItem[] }[] = [
  { items: [
    { to: '/', label: 'Dashboard', icon: House, end: true },
    { to: '/review', label: 'Review', icon: ClipboardText, badge: 'review' },
    { to: '/plan', label: 'Plan', icon: Compass },
    { to: '/funds', label: 'Saving for', icon: PiggyBank },
    { to: '/assistant', label: 'Ask Tally', icon: Sparkle },
    { to: '/transactions', label: 'Transactions', icon: ListBullets },
    { to: '/budget', label: 'Budget', icon: Target },
    { to: '/spending', label: 'Spending', icon: ChartDonut },
    { to: '/recurring', label: 'Recurring', icon: Repeat },
    { to: '/cash-flow', label: 'Cash flow', icon: ChartLineUp },
    { to: '/net-worth', label: 'Net worth', icon: TrendUp },
    { to: '/goals', label: 'Goals', icon: Flag },
    { to: '/findings', label: 'Findings', icon: Binoculars },
    { to: '/trends', label: 'Trends', icon: ClockCounterClockwise },
    { to: '/investments', label: 'Investments', icon: ChartPieSlice },
    { to: '/receipts', label: 'Receipts', icon: ReceiptIcon },
  ] },
  { title: 'Protect & save', items: [
    { to: '/alerts', label: 'Alerts', icon: Bell, badge: 'alerts' },
    { to: '/fees', label: 'Fees', icon: Receipt },
    { to: '/subscriptions', label: 'Subscriptions', icon: ArrowsClockwise },
    { to: '/insights', label: 'Insights', icon: Lightbulb },
  ] },
  { title: 'Set up', items: [
    { to: '/accounts', label: 'Accounts', icon: Wallet },
    { to: '/rules', label: 'Rules & tags', icon: Funnel },
    { to: '/household', label: 'Household', icon: UsersThree },
    { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
  ] },
]
const ALL = SECTIONS.flatMap((s) => s.items)
const MOBILE = ['/', '/plan', '/transactions', '/alerts']

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="9" fill="var(--accent)" />
        <path d="M9 11.5h14M16 11.5V23" stroke="var(--accent-ink)" strokeWidth="3.2" strokeLinecap="round" />
      </svg>
      <span className="text-[17px] font-semibold tracking-tight text-ink">Tally</span>
    </div>
  )
}

function useAlertCount() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard, refetchInterval: 5 * 60_000 })
  return q.data?.alerts
}

/** How many charges are waiting on a person. Never urgent -- reviewing is a
 *  chore the app is asking for, not something going wrong. */
function useReviewCount() {
  const q = useQuery({ queryKey: ['review', '45'], queryFn: () => api.reviewQueue(45), staleTime: 60_000 })
  return q.data?.total ?? 0
}

function Badge({ n, urgent }: { n: number; urgent: boolean }) {
  if (!n) return null
  return (
    <span className={cx('ml-auto min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold leading-5 tnum',
      urgent ? 'bg-negative text-white' : 'bg-hover text-ink-2')}>
      {n}
    </span>
  )
}

function SyncStatus() {
  const qc = useQueryClient()
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, refetchInterval: 60_000 })
  const sync = useMutation({
    mutationFn: api.syncAll,
    onSuccess: () => setTimeout(() => qc.invalidateQueries(), 4000),
  })
  return (
    <div className="rounded-2xl border border-line bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] text-ink-3">Last synced</div>
          <div className="truncate text-[13px] font-medium text-ink">{ago(meta.data?.last_synced_at ?? null)}</div>
        </div>
        <button onClick={() => sync.mutate()} disabled={sync.isPending} title="Sync all banks now"
                className="rounded-full p-2 text-ink-2 hover:bg-hover hover:text-ink disabled:opacity-50">
          <ArrowsClockwise size={16} className={sync.isPending ? 'animate-spin' : ''} />
        </button>
      </div>
      {!!meta.data?.needs_attention && (
        <NavLink to="/accounts" className="mt-2 block rounded-lg bg-warn-soft px-2 py-1.5 text-[12px] font-medium text-warn">
          {meta.data.needs_attention} connection{meta.data.needs_attention > 1 ? 's' : ''} need attention
        </NavLink>
      )}
      {meta.data && meta.data.plaid_env !== 'production' && (
        <div className="mt-2 rounded-lg bg-hover px-2 py-1.5 text-[11px] text-ink-2">
          Demo data · Plaid {meta.data.plaid_env}
        </div>
      )}
    </div>
  )
}

/** Who you are, and the way out. Signing out only appears when Tally is the
 *  thing asking for the password -- behind an authenticating proxy that is the
 *  proxy's job, not ours. */
function WhoAmI() {
  const qc = useQueryClient()
  const { open, setOpen, ref } = usePopover()
  const q = useQuery({ queryKey: ['auth'], queryFn: api.authState, staleTime: 60_000 })
  const household = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 60_000 })
  const me = q.data?.me
  // Switching person only exists where a proxy did the authenticating. Where
  // Tally asks for the password, being someone else means signing in as them.
  const canSwitch = q.data?.mode === 'proxy' && (household.data?.people.length ?? 0) > 1
  const switchTo = useMutation({
    mutationFn: (id: number) => api.viewAs(id),
    onSuccess: () => { setOpen(false); qc.invalidateQueries() },
  })
  if (!me && !q.data?.required && !canSwitch) return null
  return (
    <div ref={ref} className="relative mt-2 flex items-center gap-2 px-2">
      {open && canSwitch && (
        <div className="absolute bottom-full left-2 mb-2 w-52 overflow-hidden rounded-2xl border border-line bg-surface p-1.5 shadow-[0_16px_40px_-12px_rgba(0,0,0,0.3)]">
          <div className="px-2 py-1 text-[11px] text-ink-3">Viewing as</div>
          {(household.data?.people ?? []).map((p) => (
            <button key={p.id} onClick={() => switchTo.mutate(p.id)}
                    className={cx('flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-[13px]',
                      p.id === me?.id ? 'bg-hover text-ink' : 'text-ink-2 hover:bg-hover hover:text-ink')}>
              <span className="h-5 w-5 shrink-0 rounded-full" style={{ background: `var(--${p.color})` }} />
              <span className="truncate">{p.name}</span>
            </button>
          ))}
          <div className="px-2 pb-1 pt-1.5 text-[11px] leading-snug text-ink-3">
            A view, not a wall — anyone past the proxy can switch.
          </div>
        </div>
      )}
      {me && (
        <>
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-page"
                style={{ background: `var(--${me.color})` }}>
            {me.name.slice(0, 1).toUpperCase()}
          </span>
          <button onClick={() => canSwitch && setOpen(!open)} disabled={!canSwitch}
                  className={cx('min-w-0 flex-1 truncate text-left text-[12px] text-ink-2',
                    canSwitch && 'hover:text-ink')}>
            {me.name}
          </button>
        </>
      )}
      {!me && canSwitch && (
        <button onClick={() => setOpen(!open)}
                className="flex-1 text-left text-[12px] text-ink-3 hover:text-ink">
          Viewing everything
        </button>
      )}
      {q.data?.required && (
        <form method="post" action="/api/auth/logout">
          <button type="submit" title="Sign out"
                  className="rounded-full p-1.5 text-ink-3 hover:bg-hover hover:text-ink">
            <SignOut size={14} />
          </button>
        </form>
      )}
    </div>
  )
}

/** One box for "how much did I spend at Costco last year". */
function SearchBox() {
  const [q, setQ] = useState('')
  const go = useNavigate()
  return (
    <form
      className="relative mt-5"
      onSubmit={(e) => { e.preventDefault(); if (q.trim()) go(`/search?q=${encodeURIComponent(q.trim())}`) }}
    >
      <MagnifyingGlass size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Ask about your money"
        aria-label="Search transactions"
        className="h-9 w-full rounded-full border border-line bg-surface pl-8 pr-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-line-strong"
      />
    </form>
  )
}

function MoreMenu() {
  const { open, setOpen, ref } = usePopover()
  const loc = useLocation()
  const extra = ALL.filter((n) => !MOBILE.includes(n.to))
  const active = extra.some((n) => loc.pathname === n.to)
  return (
    <div ref={ref} className="relative flex">
      <button onClick={() => setOpen(!open)} className={cx('flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px]', active || open ? 'text-ink' : 'text-ink-3')}>
        <DotsThreeOutline size={22} weight={active ? 'fill' : 'regular'} />More
      </button>
      {open && (
        <div className="absolute bottom-full right-2 mb-2 w-56 overflow-hidden rounded-2xl border border-line bg-surface p-1.5 shadow-[0_16px_40px_-12px_rgba(0,0,0,0.3)]">
          {extra.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setOpen(false)}
                     className={({ isActive }) => cx('flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px]', isActive ? 'bg-hover text-ink' : 'text-ink-2')}>
              <Icon size={18} />{label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const alerts = useAlertCount()
  const toReview = useReviewCount()
  return (
    <div className="min-h-[100dvh] bg-page">
      <aside className="fixed inset-y-0 left-0 hidden w-[232px] flex-col overflow-y-auto border-r border-line bg-page px-4 py-5 lg:flex">
        <div className="px-2"><Logo /></div>
        <SearchBox />
        <nav className="mt-6 flex flex-col">
          {SECTIONS.map((s, si) => (
            <div key={si} className={cx('flex flex-col gap-0.5', si > 0 && 'mt-5')}>
              {s.title && <div className="mb-1 px-3 text-[11px] font-medium uppercase tracking-wider text-ink-3">{s.title}</div>}
              {s.items.map(({ to, label, icon: Icon, end, badge }) => (
                <NavLink key={to} to={to} end={end}
                         className={({ isActive }) => cx(
                           'flex items-center gap-3 rounded-xl px-3 py-2 text-[14px] transition-colors',
                           isActive ? 'bg-surface font-medium text-ink shadow-[0_1px_2px_rgba(0,0,0,0.04)] ring-1 ring-line' : 'text-ink-2 hover:bg-hover hover:text-ink',
                         )}>
                  {({ isActive }) => (<>
                    <Icon size={18} weight={isActive ? 'fill' : 'regular'} />{label}
                    {badge === 'alerts' && alerts && <Badge n={alerts.open} urgent={alerts.urgent > 0} />}
                    {badge === 'review' && <Badge n={toReview} urgent={false} />}
                  </>)}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="mt-auto pt-6"><SyncStatus /><WhoAmI /></div>
      </aside>

      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-line bg-page/90 px-4 py-3 backdrop-blur lg:hidden">
        <Logo />
      </header>

      <main className="px-4 pb-28 pt-5 md:px-8 lg:ml-[232px] lg:pb-12 lg:pt-8">
        <div className="mx-auto max-w-[1180px]">{children}</div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        {MOBILE.map((path) => ALL.find((n) => n.to === path)!).map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink key={to} to={to} end={end}
                   className={({ isActive }) => cx('relative flex flex-col items-center gap-0.5 py-2 text-[11px]', isActive ? 'text-ink' : 'text-ink-3')}>
            {({ isActive }) => (<>
              <Icon size={22} weight={isActive ? 'fill' : 'regular'} />{label}
              {badge === 'alerts' && !!alerts?.urgent && <span className="absolute right-[calc(50%-18px)] top-1.5 h-2 w-2 rounded-full bg-negative" />}
            </>)}
          </NavLink>
        ))}
        <MoreMenu />
      </nav>
    </div>
  )
}
