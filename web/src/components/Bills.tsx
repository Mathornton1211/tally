import { ArrowRight, CaretDown, Check, Copy, Phone, TrendUp } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Bill } from '../api'
import { fmtMonth, money, money0 } from '../lib/format'
import { cx, Empty, MerchantAvatar, Money, Panel, PanelHeader, Skeleton } from './ui'

function CopyScript({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500) } catch { /* blocked */ } }}
      className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[12px] font-medium text-ink-2 hover:bg-hover hover:text-ink">
      {done ? <><Check size={12} weight="bold" /> Copied</> : <><Copy size={12} /> Copy script</>}
    </button>
  )
}

function Row({ b }: { b: Bill }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="px-5 py-3">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 text-left">
        <MerchantAvatar logo={b.logo_url} icon="Lightning" name={b.name} size={34} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[14px] font-medium text-ink">{b.name}</span>
            {b.increased_from && (
              <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">
                <TrendUp size={10} weight="bold" /> up from {money(Number(b.increased_from))}
              </span>
            )}
          </div>
          <div className="truncate text-[12px] text-ink-3">
            {money(Number(b.monthly))}/mo · {money0(Number(b.annual))} a year · paying since {fmtMonth(b.since, true)}
          </div>
        </div>
        <div className="text-right">
          <Money value={Number(b.paid_so_far)} className="text-[13px] text-ink-2" />
          <div className="text-[11px] text-ink-3">paid so far</div>
        </div>
        <CaretDown size={13} className={cx('text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="mt-3 rounded-xl bg-surface-2 p-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-[13px] font-semibold text-ink"><Phone size={15} /> What to say</span>
            <CopyScript text={b.script} />
          </div>
          <p className="text-[14px] italic leading-relaxed text-ink-2">"{b.script}"</p>
          <p className="mt-2 text-[12px] text-ink-3">{b.why}</p>
        </div>
      )}
    </li>
  )
}

export function BillsPanel({ limit }: { limit?: number }) {
  const q = useQuery({ queryKey: ['bills'], queryFn: api.bills })
  const d = q.data
  if (q.isLoading) return <Skeleton className="h-72 rounded-[18px]" />
  if (!d || d.bills.length === 0) {
    return <Panel><Empty title="No bills to negotiate yet">Recurring bills show up here once Tally has seen a few.</Empty></Panel>
  }
  const shown = limit ? d.bills.slice(0, limit) : d.bills
  return (
    <Panel>
      <PanelHeader
        title="Lower these bills"
        sub={`${money(Number(d.total_monthly))} a month across ${d.bills.length} bills, ${money0(Number(d.total_annual))} a year`}
        action={<span className="hidden text-right text-[12px] text-ink-3 sm:block">Tap one for the numbers<br />and what to say</span>} />
      <ul className="mt-2 divide-y divide-line pb-1">
        {shown.map((b) => <Row key={b.name + b.account_name} b={b} />)}
      </ul>
      <div className="flex items-center gap-1.5 border-t border-line px-5 py-2.5 text-[12px] text-ink-3">
        <ArrowRight size={12} /> A 20 minute call that trims {money0(60)} a month is {money0(720)} a year, and it repeats every year.
      </div>
    </Panel>
  )
}
