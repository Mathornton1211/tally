import {
  ArrowsClockwise, CaretDown, CaretLeft, CaretRight, Check, Plus, Sparkle, Trash, Warning,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type BudgetMonth, type BudgetRow, type BudgetSuggestion } from '../api'
import { CategoryIcon } from '../components/icons'
import { Button, cx, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtMonth, fmtShort, money, money0 } from '../lib/format'

const field = 'h-9 w-28 rounded-lg border border-line-strong bg-surface-2 px-2 text-[14px] text-ink outline-none focus:border-ink-3 tnum'

const STATE_FILL = { under: 'bg-series-1', watch: 'bg-warn', over: 'bg-negative' } as const

function monthKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

/** What is left, said the way a person would say it. */
function leftLabel(r: BudgetRow) {
  const left = Number(r.left_after_commitments)
  if (Number(r.spent) > Number(r.available)) return { text: `${money(Number(r.spent) - Number(r.available))} over`, tone: 'text-negative' }
  if (left < 0) return { text: `${money(-left)} short for what is still due`, tone: 'text-warn' }
  return { text: `${money(left)} left`, tone: 'text-ink' }
}

/**
 * Spent, then what is already committed, against the budget. The notch is
 * today: a bar that is further along than the notch is running hot, which is
 * the whole question on the 14th of the month.
 */
function Bar({ r, pace, current }: { r: BudgetRow; pace: number; current: boolean }) {
  const avail = Number(r.available)
  const w = (n: number) => `${avail > 0 ? Math.max(0, Math.min((n / avail) * 100, 100)) : n > 0 ? 100 : 0}%`
  return (
    <div className="relative mt-2 h-2 overflow-hidden rounded-full bg-hover">
      <div className={cx('absolute inset-y-0 left-0', STATE_FILL[r.state])} style={{ width: w(Number(r.spent)) }} />
      {Number(r.committed) > 0 && (
        <div className="absolute inset-y-0 opacity-45" title="already committed this month"
             style={{ left: w(Number(r.spent)), width: w(Number(r.committed)), background: 'var(--ink-3)' }} />
      )}
      {current && pace > 0 && pace < 1 && (
        <div className="absolute inset-y-0 w-px bg-ink opacity-40" style={{ left: `${pace * 100}%` }} title="today" />
      )}
    </div>
  )
}

function Row({ r, month, pace, current }: { r: BudgetRow; month: string; pace: number; current: boolean }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState(String(Number(r.amount)))
  const invalidate = () => qc.invalidateQueries({ queryKey: ['budgets'] })
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.setBudget(r.category, { month, ...body }),
    onSuccess: invalidate,
  })
  const drop = useMutation({ mutationFn: () => api.clearBudget(r.category), onSuccess: invalidate })
  const left = leftLabel(r)

  return (
    <li className="px-5 py-3.5">
      <button onClick={() => setOpen(!open)} className="w-full text-left">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-hover text-ink-2">
            <CategoryIcon name={r.icon} size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-[14px] font-medium text-ink">{r.label}</span>
              <span className={cx('shrink-0 text-[13px] font-medium tnum', left.tone)}>{left.text}</span>
            </div>
            <Bar r={r} pace={pace} current={current} />
            <div className="mt-1.5 flex items-baseline justify-between gap-3 text-[12px] text-ink-3">
              <span className="tnum">
                {money(Number(r.spent))} of {money0(Number(r.available))}
                {Number(r.carry_in) !== 0 && (
                  <span className="ml-1.5 rounded-full bg-hover px-1.5 py-0.5 text-[11px] text-ink-2">
                    {Number(r.carry_in) > 0 ? '+' : '−'}{money0(Math.abs(Number(r.carry_in)))} rolled over
                  </span>
                )}
              </span>
              {Number(r.committed) > 0 && <span className="shrink-0">{money0(Number(r.committed))} still due</span>}
            </div>
          </div>
          <CaretDown size={13} className={cx('shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
        </div>
      </button>

      {open && (
        <div className="mt-3 rounded-xl bg-surface-2 p-3">
          {current && (
            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {[
                { label: 'A day from here',
                  value: r.per_day != null ? money(Number(r.per_day))
                    : Number(r.left_after_commitments) < 0 ? 'nothing left' : '—' },
                { label: 'Heading for', value: r.projected == null ? 'too early to say' : money0(Number(r.projected)) },
                { label: 'Transactions', value: String(r.transactions) },
              ].map((s) => (
                <div key={s.label}>
                  <div className="text-[11px] text-ink-3">{s.label}</div>
                  <div className="text-[14px] font-medium tnum text-ink">{s.value}</div>
                </div>
              ))}
            </div>
          )}

          {r.upcoming.length > 0 && (
            <div className="mb-3">
              <div className="mb-1 text-[12px] font-medium text-ink-3">Still to come this month</div>
              <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
                {r.upcoming.map((u, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 px-3 py-1.5 text-[13px]">
                    <span className="truncate text-ink">{u.name} <span className="text-ink-3">{fmtShort(u.date)}</span></span>
                    <Money value={Number(u.amount)} className="text-ink" />
                  </li>
                ))}
              </ul>
            </div>
          )}

          <form className="flex flex-wrap items-center gap-2"
                onSubmit={(e) => { e.preventDefault(); save.mutate({ amount: Number(amount), rollover: r.rollover }) }}>
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))}
                   className={field} aria-label={`${r.label} budget`} />
            <Button type="submit" disabled={save.isPending}>Save</Button>
            <label className="ml-1 flex items-center gap-1.5 text-[12px] text-ink-2">
              <input type="checkbox" checked={r.rollover} className="accent-[var(--accent)]"
                     onChange={(e) => save.mutate({ amount: Number(r.amount), rollover: e.target.checked })} />
              Carry the leftover into next month
            </label>
            <button type="button" onClick={() => drop.mutate()}
                    className="ml-auto inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-negative">
              <Trash size={12} /> Remove
            </button>
          </form>
          <ErrorNote error={save.error || drop.error} />
        </div>
      )}
    </li>
  )
}

function Suggestions({ month, onDone }: { month: string; onDone: () => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['budget-suggestions'], queryFn: api.budgetSuggestions })
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const list = q.data?.suggestions ?? []
  const chosen = picked ?? new Set(list.filter((s) => !s.already_budgeted).map((s) => s.category))
  const apply = useMutation({
    mutationFn: () => api.applyBudgetSuggestions({ month, categories: [...chosen] }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['budgets'] }); onDone() },
  })

  const toggle = (s: BudgetSuggestion) => {
    const next = new Set(chosen)
    if (next.has(s.category)) next.delete(s.category)
    else next.add(s.category)
    setPicked(next)
  }
  const total = list.filter((s) => chosen.has(s.category)).reduce((a, s) => a + Number(s.amount), 0)

  return (
    <Panel className="mb-4">
      <PanelHeader title="Start from what you actually spend"
                   sub="The middle month of the last three, rounded. Change anything you like — these are a starting point, not a verdict." />
      {!q.data ? <div className="p-5"><Skeleton className="h-32 rounded-xl" /></div> : list.length === 0 ? (
        <div className="px-5 pb-5 pt-3 text-[13px] text-ink-3">
          Not enough history yet. Once there are a couple of full months of transactions, Tally can suggest amounts.
        </div>
      ) : (
        <>
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {list.map((s) => (
              <li key={s.category}>
                <label className="flex cursor-pointer items-center gap-3 px-5 py-2.5 hover:bg-hover">
                  <input type="checkbox" checked={chosen.has(s.category)} onChange={() => toggle(s)}
                         className="accent-[var(--accent)]" />
                  <CategoryIcon name={s.icon} size={16} />
                  <span className="min-w-0 flex-1 truncate text-[14px] text-ink">
                    {s.label}
                    {s.already_budgeted && <span className="ml-2 text-[12px] text-ink-3">already budgeted</span>}
                    {s.rollover && <span className="ml-2 rounded-full bg-hover px-1.5 py-0.5 text-[11px] text-ink-2">rolls over</span>}
                  </span>
                  <span className="shrink-0 text-[12px] text-ink-3 tnum">
                    {s.months === 1 ? 'one month' : `worst ${money0(Number(s.worst))}`}
                  </span>
                  <Money value={Number(s.amount)} className="w-20 shrink-0 text-right text-[14px] font-medium text-ink" />
                </label>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
            <span className="text-[13px] text-ink-3">
              {chosen.size} {chosen.size === 1 ? 'category' : 'categories'} · {money0(total)} a month
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={onDone}>Not now</Button>
              <Button variant="primary" onClick={() => apply.mutate()} disabled={apply.isPending || chosen.size === 0}>
                <Check size={14} weight="bold" /> {apply.isPending ? 'Setting…' : 'Use these'}
              </Button>
            </div>
          </div>
          <div className="px-5 pb-3"><ErrorNote error={apply.error} /></div>
        </>
      )}
    </Panel>
  )
}

function Unbudgeted({ rows, month }: { rows: BudgetMonth['unbudgeted']; month: string }) {
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: ({ category, amount }: { category: string; amount: number }) =>
      api.setBudget(category, { month, amount }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['budgets'] }),
  })
  if (!rows.length) return null
  return (
    <Panel className="mt-4">
      <PanelHeader title="Not budgeted"
                   sub="Real spending with no target behind it. This is where a month quietly goes." />
      <ul className="mt-3 divide-y divide-line border-t border-line">
        {rows.map((u) => (
          <li key={u.category} className="flex items-center gap-3 px-5 py-2.5">
            <CategoryIcon name={u.icon} size={16} />
            <span className="min-w-0 flex-1 truncate text-[14px] text-ink">{u.label}</span>
            <Money value={Number(u.spent)} className="text-[14px] text-ink-2" />
            <button onClick={() => add.mutate({ category: u.category, amount: Math.ceil(Number(u.spent) / 10) * 10 })}
                    className="inline-flex items-center gap-1 rounded-full border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:bg-hover hover:text-ink">
              <Plus size={11} weight="bold" /> Budget it
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

export default function Budget() {
  const [offset, setOffset] = useState(0)
  const [suggesting, setSuggesting] = useState(false)
  const base = new Date()
  base.setDate(1)
  base.setMonth(base.getMonth() + offset)
  const month = monthKey(base)

  const q = useQuery({ queryKey: ['budgets', month], queryFn: () => api.budgets(month) })
  const d = q.data
  const over = d?.categories.filter((c) => c.state === 'over').length ?? 0
  const watch = d?.categories.filter((c) => c.state === 'watch').length ?? 0

  return (
    <>
      <PageHeader
        title="Budget"
        sub={d?.current
          ? `Day ${d.elapsed} of ${d.days} · ${d.days_left} left`
          : d ? fmtMonth(d.month, true) : undefined}
      >
        <div className="flex items-center gap-1 rounded-full border border-line bg-surface px-1 py-0.5">
          <button onClick={() => setOffset(offset - 1)} className="rounded-full p-1.5 text-ink-2 hover:bg-hover hover:text-ink" aria-label="Previous month">
            <CaretLeft size={14} weight="bold" />
          </button>
          <span className="min-w-[92px] text-center text-[13px] font-medium text-ink">{fmtMonth(month, true)}</span>
          <button onClick={() => setOffset(offset + 1)} disabled={offset >= 0}
                  className="rounded-full p-1.5 text-ink-2 hover:bg-hover hover:text-ink disabled:opacity-30" aria-label="Next month">
            <CaretRight size={14} weight="bold" />
          </button>
        </div>
        {d?.any && (
          <Button onClick={() => setSuggesting(!suggesting)}>
            <Sparkle size={14} /> Suggest amounts
          </Button>
        )}
      </PageHeader>

      <ErrorNote error={q.error} />
      {(suggesting || (d && !d.any)) && <Suggestions month={month} onDone={() => setSuggesting(false)} />}

      {!d ? (
        <div className="grid gap-4"><Skeleton className="h-24 rounded-[18px]" /><Skeleton className="h-64 rounded-[18px]" /></div>
      ) : !d.any ? null : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Budgeted', value: Number(d.budgeted) },
              { label: 'Spent', value: Number(d.spent) },
              { label: d.current ? 'Still committed' : 'Committed', value: Number(d.committed) },
              { label: 'Left to spend', value: Number(d.left_after_commitments) },
            ].map((t, i) => (
              <div key={t.label} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className={cx('mt-0.5 text-[20px] font-semibold tracking-tight',
                  i === 3 && t.value < 0 ? 'text-negative' : 'text-ink')}>
                  <Money value={t.value} size="lg" />
                </div>
              </div>
            ))}
          </div>

          {(over > 0 || watch > 0) && (
            <div className="mb-4 flex items-start gap-2 rounded-2xl border border-line bg-warn-soft px-4 py-3 text-[13px] text-ink">
              <Warning size={15} weight="fill" className="mt-0.5 shrink-0 text-warn" />
              <span>
                {over > 0 && <>{over} {over === 1 ? 'category is' : 'categories are'} over budget</>}
                {over > 0 && watch > 0 && ', and '}
                {watch > 0 && <>{watch} {watch === 1 ? 'is' : 'are'} on pace to go over</>}
                {d.current && d.days_left > 0 && <> with {d.days_left} days left.</>}
              </span>
            </div>
          )}

          <Panel>
            <PanelHeader
              title="By category"
              sub={d.current ? 'The notch on each bar is today.' : undefined}
              action={d.income > 0
                ? <span className="text-[13px] text-ink-3">{money0(Number(d.income))} came in</span>
                : undefined}
            />
            <ul className="mt-2 divide-y divide-line">
              {d.categories.map((r) => <Row key={r.category} r={r} month={month} pace={d.pace} current={d.current} />)}
            </ul>
          </Panel>

          <Unbudgeted rows={d.unbudgeted} month={month} />

          {d.unbudgeted_spent > 0 && (
            <div className="mt-3 flex items-center gap-2 px-1 text-[12px] text-ink-3">
              <ArrowsClockwise size={12} />
              {money(Number(d.total_spent))} spent in total this month, {money(Number(d.unbudgeted_spent))} of it outside a budget.
            </div>
          )}
        </>
      )}
    </>
  )
}
