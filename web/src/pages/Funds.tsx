import {
  ArrowsClockwise, CalendarBlank, CaretDown, CheckCircle, GiftIcon, Plus, ShoppingBag, Storefront,
  Trash, Warning, X,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Fund, type FundCredit } from '../api'
import { CategoryIcon } from '../components/icons'
import { Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, Skeleton } from '../components/ui'
import { fmtShort, money, money0, relativeDays } from '../lib/format'

const CREDIT_KINDS = [
  { value: 'gift_card', label: 'Gift card' },
  { value: 'store_credit', label: 'Store credit' },
  { value: 'rebate', label: 'Rebate' },
  { value: 'trade_in', label: 'Trade-in' },
  { value: 'other', label: 'Other' },
]
const field = 'h-10 w-full rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3'

function AddFund({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', target_amount: '', target_date: '', note: '' })
  const save = useMutation({
    mutationFn: () => api.createFund({
      name: f.name.trim(), target_amount: Number(f.target_amount),
      target_date: f.target_date || null, note: f.note.trim() || null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['funds'] }); onClose() },
  })
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}
            className="relative w-full max-w-[440px] rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
            style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-start justify-between px-6 pt-5">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">Something to save for</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="grid gap-4 px-6 pt-5">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">What is it</span>
            <input autoFocus required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })}
                   placeholder="3D printer, truck tires, light bar" className={field} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Costs about</span>
              <input required inputMode="decimal" value={f.target_amount} placeholder="600"
                     onChange={(e) => setF({ ...f, target_amount: e.target.value.replace(/[^\d.]/g, '') })} className={field} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Want it by (optional)</span>
              <input type="date" value={f.target_date} onChange={(e) => setF({ ...f, target_date: e.target.value })} className={field} />
            </label>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">Note (optional)</span>
            <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })}
                   placeholder="Bambu A1, or 265/70R17" className={field} />
          </label>
        </div>
        <div className="px-6 pt-3"><ErrorNote error={save.error} /></div>
        <div className="mt-4 flex justify-end gap-2 border-t border-line px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={save.isPending || !f.name.trim() || !f.target_amount}>
            {save.isPending ? 'Adding…' : 'Add'}
          </Button>
        </div>
      </form>
    </div>
  )
}

function AddCredit({ fundId, onClose }: { fundId: number; onClose: () => void }) {
  const qc = useQueryClient()
  const [c, setC] = useState({ kind: 'gift_card', label: '', amount: '', merchant: '', expires_on: '' })
  const save = useMutation({
    mutationFn: () => api.addFundCredit(fundId, {
      kind: c.kind, label: c.label.trim(), amount: Number(c.amount),
      merchant: c.merchant.trim() || null, expires_on: c.expires_on || null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['funds'] }); onClose() },
  })
  return (
    <form onSubmit={(e) => { e.preventDefault(); save.mutate() }} className="rounded-xl bg-surface-2 p-3">
      <div className="mb-2 text-[12px] font-medium text-ink-3">Money you already have for this</div>
      <div className="grid gap-2 sm:grid-cols-2">
        <select value={c.kind} onChange={(e) => setC({ ...c, kind: e.target.value })} className={field}>
          {CREDIT_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        <input required value={c.label} onChange={(e) => setC({ ...c, label: e.target.value })}
               placeholder="Home Depot card" className={field} />
        <input required inputMode="decimal" value={c.amount} placeholder="Amount"
               onChange={(e) => setC({ ...c, amount: e.target.value.replace(/[^\d.]/g, '') })} className={field} />
        <label className="flex items-center gap-2 text-[12px] text-ink-3">
          Expires
          <input type="date" value={c.expires_on} onChange={(e) => setC({ ...c, expires_on: e.target.value })} className={field} />
        </label>
      </div>
      <ErrorNote error={save.error} />
      <div className="mt-2 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={save.isPending || !c.label.trim() || !c.amount}>Add</Button>
      </div>
    </form>
  )
}

function CreditRow({ fundId, c }: { fundId: number; c: FundCredit }) {
  const qc = useQueryClient()
  const del = useMutation({ mutationFn: () => api.deleteFundCredit(fundId, c.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['funds'] }) })
  const Icon = c.kind === 'store_credit' ? Storefront : GiftIcon
  return (
    <li className="flex items-center gap-2.5 px-1 py-1.5">
      <Icon size={15} className={cx('shrink-0', c.expiring ? 'text-warn' : 'text-ink-3')} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] text-ink">{c.label}</div>
        {c.expires_on && (
          <div className={cx('text-[11px]', c.expiring ? 'text-warn' : 'text-ink-3')}>
            expires {relativeDays(c.expires_on).toLowerCase()}
          </div>
        )}
      </div>
      <Money value={Number(c.remaining)} className="text-[13px] text-ink" />
      <button onClick={() => del.mutate()} className="p-1 text-ink-3 hover:text-negative" aria-label="Remove"><Trash size={12} /></button>
    </li>
  )
}


const AUTO_KINDS = [
  { value: 'per_paycheck', label: 'Every paycheck' },
  { value: 'percent_of_income', label: '% of income' },
  { value: 'monthly', label: 'Monthly' },
]

/**
 * Filling the fund automatically. The preview matters more than the form: a
 * percentage of a variable income is an abstraction until you see what it
 * would actually have set aside over the last six months of real paychecks.
 */
function AutoFill({ f }: { f: Fund }) {
  const qc = useQueryClient()
  const [kind, setKind] = useState<string>(f.auto_kind ?? 'per_paycheck')
  const [amount, setAmount] = useState(f.auto_amount ? String(Number(f.auto_amount)) : '')
  const [percent, setPercent] = useState(f.auto_percent ? String(Number(f.auto_percent)) : '10')

  const value = kind === 'percent_of_income' ? percent : amount
  const params = new URLSearchParams({ kind, months: '6' })
  if (kind === 'percent_of_income') params.set('percent', percent || '0')
  else params.set('amount', amount || '0')

  const preview = useQuery({
    queryKey: ['fund-auto-preview', kind, value],
    queryFn: () => api.fundAutoPreview(params.toString()),
    enabled: Number(value) > 0,
  })
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.setFundAuto(f.id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['funds'] }),
  })

  const on = !!f.auto_kind
  return (
    <div className="mt-4 rounded-xl bg-surface-2 p-3">
      <div className="mb-2 flex items-center gap-2">
        <ArrowsClockwise size={13} className={on ? 'text-positive' : 'text-ink-3'} />
        <span className="text-[12px] font-medium text-ink">
          {on ? 'Filling itself' : 'Fill this automatically'}
        </span>
        {on && (
          <button onClick={() => save.mutate({ kind: null })}
                  className="ml-auto text-[12px] text-ink-3 hover:text-negative">
            Turn off
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select value={kind} onChange={(e) => setKind(e.target.value)}
                className="h-9 rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-ink outline-none">
          {AUTO_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        {kind === 'percent_of_income' ? (
          <div className="flex items-center gap-1">
            <input inputMode="decimal" value={percent} aria-label="Percent of income"
                   onChange={(e) => setPercent(e.target.value.replace(/[^\d.]/g, ''))}
                   className="h-9 w-16 rounded-lg border border-line-strong bg-surface px-2 text-[13px] tnum text-ink outline-none" />
            <span className="text-[13px] text-ink-3">% of every deposit</span>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <span className="text-[13px] text-ink-3">$</span>
            <input inputMode="decimal" value={amount} aria-label="Amount"
                   onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))}
                   className="h-9 w-20 rounded-lg border border-line-strong bg-surface px-2 text-[13px] tnum text-ink outline-none" />
            <span className="text-[13px] text-ink-3">{kind === 'monthly' ? 'a month' : 'each paycheck'}</span>
          </div>
        )}
        <Button
          onClick={() => save.mutate(kind === 'percent_of_income'
            ? { kind, percent: Number(percent) }
            : { kind, amount: Number(amount) })}
          disabled={save.isPending || !(Number(value) > 0)}
        >
          {on ? 'Update' : 'Start'}
        </Button>
      </div>

      {preview.data && Number(value) > 0 && (
        <div className="mt-2 text-[12px] text-ink-3">
          Over the last 6 months that would have set aside{' '}
          <b className="text-ink">{money(Number(preview.data.total))}</b>
          {preview.data.deposits > 0 && <> across {preview.data.deposits} deposits</>}
          {' '}— about {money0(Number(preview.data.per_month))} a month.
        </div>
      )}
      {on && f.auto_through && (
        <div className="mt-1.5 text-[11px] text-ink-3">Taken its cut through {fmtShort(f.auto_through)}.</div>
      )}
    </div>
  )
}

function FundCard({ f }: { f: Fund }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [cash, setCash] = useState('')
  const contribute = useMutation({
    mutationFn: () => api.contributeToFund(f.id, Number(cash)),
    onSuccess: () => { setCash(''); qc.invalidateQueries({ queryKey: ['funds'] }) },
  })
  const mark = useMutation({ mutationFn: (bought: boolean) => api.patchFund(f.id, { bought }), onSuccess: () => qc.invalidateQueries({ queryKey: ['funds'] }) })
  const del = useMutation({ mutationFn: () => api.deleteFund(f.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['funds'] }) })

  const target = Number(f.target_amount)
  const credits = Number(f.credits_total)
  const saved = Number(f.saved)
  const spent = Number(f.spent)
  const pct = (n: number) => `${Math.min((n / target) * 100, 100)}%`
  const a = f.affordability

  return (
    <Panel className={cx('flex flex-col', f.bought && 'opacity-70')}>
      <button onClick={() => setOpen(!open)} className="px-5 pt-5 text-left">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
              f.complete || f.bought ? 'bg-accent-soft text-positive' : 'bg-hover text-ink-2')}>
              <CategoryIcon name={f.icon} size={19} />
            </div>
            <div className="min-w-0">
              <div className="truncate text-[15px] font-semibold text-ink">{f.name}</div>
              <div className="truncate text-[12px] text-ink-3">
                {f.bought ? `bought ${fmtShort(f.bought_on!)}`
                  : f.complete ? 'ready to buy'
                  : `${money(Number(f.still_needed))} to go of ${money0(target)}`}
                {f.target_date && !f.bought && ` · wanted by ${fmtShort(f.target_date)}`}
              </div>
            </div>
          </div>
          <CaretDown size={14} className={cx('mt-1 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
        </div>

        <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-hover">
          <div className="h-full bg-positive" style={{ width: pct(spent) }} title="already spent" />
          <div className="h-full bg-series-1" style={{ width: pct(credits) }} title="gift cards and credit" />
          <div className="h-full bg-series-2" style={{ width: pct(saved) }} title="cash set aside" />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-3">
          {credits > 0 && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-series-1" />{money(credits)} credit</span>}
          {saved > 0 && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-series-2" />{money(saved)} saved</span>}
          {spent > 0 && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-positive" />{money(spent)} spent</span>}
          {credits === 0 && saved === 0 && spent === 0 && <span>nothing set aside yet</span>}
        </div>
      </button>

      {!f.bought && a && (
        <div className={cx('mx-5 mt-3 rounded-xl px-3 py-2 text-[12px]',
          a.affordable_now ? 'bg-accent-soft text-ink' : 'bg-surface-2 text-ink-2')}>
          {a.affordable_now ? <CheckCircle size={13} weight="fill" className="mr-1 inline text-positive" />
            : <Warning size={13} weight="fill" className="mr-1 inline text-warn" />}
          {Number(a.cash_needed) <= 0
            ? 'Covered by credit and what you have set aside.'
            : <>Needs <b>{money(Number(a.cash_needed))}</b> in cash at the till. {a.note}
              {a.days_of_cash_after != null && a.days_of_cash_now != null &&
                ` Buying today would leave ${a.days_of_cash_after} days of cash instead of ${a.days_of_cash_now}.`}</>}
        </div>
      )}

      {open && (
        <div className="px-5 pb-4 pt-4">
          {f.credits.length > 0 && (
            <ul className="mb-3 divide-y divide-line rounded-xl border border-line px-2">
              {f.credits.map((c) => <CreditRow key={c.id} fundId={f.id} c={c} />)}
            </ul>
          )}
          {adding ? <AddCredit fundId={f.id} onClose={() => setAdding(false)} /> : (
            <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
              <Plus size={12} /> Add a gift card or store credit
            </button>
          )}

          <form onSubmit={(e) => { e.preventDefault(); contribute.mutate() }} className="mt-4 flex items-center gap-2">
            <input inputMode="decimal" value={cash} placeholder="Put aside…"
                   onChange={(e) => setCash(e.target.value.replace(/[^\d.]/g, ''))}
                   className="h-9 w-32 rounded-lg border border-line-strong bg-surface-2 px-2 text-[13px] text-ink outline-none" />
            <Button type="submit" disabled={!cash || contribute.isPending}>Add cash</Button>
            {f.pace_per_month != null && Number(f.pace_per_month) > 0 && (
              <span className="text-[12px] text-ink-3">
                {money0(Number(f.pace_per_month))}/mo so far
                {f.months_left_at_pace ? ` · ${f.months_left_at_pace} months to go at that pace` : ''}
              </span>
            )}
          </form>
          {f.needed_per_month_for_target_date != null && !f.complete && (
            <div className="mt-2 flex items-center gap-1.5 text-[12px] text-ink-3">
              <CalendarBlank size={12} /> {money(Number(f.needed_per_month_for_target_date))} a month hits {fmtShort(f.target_date!)}.
            </div>
          )}

          <AutoFill f={f} />

          {f.spends.length > 0 && (
            <div className="mt-4">
              <div className="mb-1 text-[12px] font-medium text-ink-3">Bought toward this</div>
              <ul className="divide-y divide-line rounded-xl border border-line">
                {f.spends.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2">
                    <span className="truncate text-[13px] text-ink">{s.display_name} <span className="text-ink-3">{fmtShort(s.date)}</span></span>
                    <Money value={Number(s.amount)} className="text-[13px] text-ink" />
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {!f.bought
              ? <Button onClick={() => mark.mutate(true)}>Mark as bought</Button>
              : <Button variant="ghost" onClick={() => mark.mutate(false)}>Not bought after all</Button>}
            <button onClick={() => del.mutate()} className="ml-auto inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-negative">
              <Trash size={12} /> Delete fund
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}

export default function Funds() {
  const [adding, setAdding] = useState(false)
  const q = useQuery({ queryKey: ['funds'], queryFn: api.funds })
  const d = q.data

  return (
    <>
      <PageHeader title="Saving for" sub="One pot per thing, with gift cards and store credit counted where they actually work.">
        <Button variant="primary" onClick={() => setAdding(true)}><Plus size={14} weight="bold" /> Add</Button>
      </PageHeader>
      <ErrorNote error={q.error} />
      {adding && <AddFund onClose={() => setAdding(false)} />}
      {!d ? (
        <div className="grid gap-4 md:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-44 rounded-[18px]" />)}</div>
      ) : d.funds.length === 0 ? (
        <Panel><Empty title="Nothing on the list yet" icon={<ShoppingBag size={20} />}>
          A 3D printer, truck tires, a light bar. Add what it costs, then add any gift cards or store credit you
          already have toward it, and Tally tracks what is actually left to find.
        </Empty></Panel>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'On the list', value: <Money value={Number(d.total_target)} size="lg" /> },
              { label: 'Gift cards & credit', value: <Money value={Number(d.total_credits)} size="lg" /> },
              { label: 'Cash set aside', value: <Money value={Number(d.total_saved)} size="lg" /> },
              { label: 'Still to find', value: <Money value={Number(d.total_still_needed)} size="lg" /> },
            ].map((t, i) => (
              <div key={i} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">{t.value}</div>
              </div>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {d.funds.map((f) => <FundCard key={f.id} f={f} />)}
          </div>
        </>
      )}
    </>
  )
}
