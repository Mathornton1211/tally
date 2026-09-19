import { CaretDown, ChatText, Check, Copy, Lightbulb, PiggyBank, Question } from '@phosphor-icons/react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type FeePlay, type Fees as F } from '../api'
import { Chart, tooltipBase, useChartTheme } from '../components/Chart'
import { DateRangePicker } from '../components/Filters'
import { cx, Empty, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtMonth, fmtShort, money, moneyCompact } from '../lib/format'
import { useFilters } from '../lib/range'

function ByMonth({ d }: { d: F }) {
  const t = useChartTheme()
  const option = useMemo(() => ({
    animationDuration: 500,
    grid: { left: 4, right: 8, top: 10, bottom: 4, containLabel: true },
    xAxis: { type: 'category', data: d.by_month.map((m) => fmtMonth(m.month)), axisTick: { show: false }, axisLine: { lineStyle: { color: t.grid } }, axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11 } },
    yAxis: { type: 'value', splitNumber: 3, axisLabel: { color: t.axis, fontFamily: t.font, fontSize: 11, formatter: moneyCompact }, splitLine: { lineStyle: { color: t.grid } } },
    tooltip: {
      ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: t.grid + '80' } },
      formatter: (ps: { dataIndex: number }[]) => {
        const m = d.by_month[ps[0].dataIndex]
        return `<div style="color:${t.ink3}">${fmtMonth(m.month, true)}</div><b style="font-variant-numeric:tabular-nums">${money(Number(m.amount))} in fees</b>`
      },
    },
    series: [{ type: 'bar', data: d.by_month.map((m) => Number(m.amount)), barMaxWidth: 26, itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] } }],
  }), [d, t])
  return <Chart option={option} height={150} ariaLabel="Fees paid by month" />
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500) } catch { /* clipboard blocked */ } }}
      className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[12px] font-medium text-ink-2 hover:bg-hover hover:text-ink"
    >
      {done ? <><Check size={13} weight="bold" /> Copied</> : <><Copy size={13} /> Copy</>}
    </button>
  )
}

function Play({ p, open, onToggle, i }: { p: FeePlay; open: boolean; onToggle: () => void; i: number }) {
  return (
    <Panel className="overflow-hidden" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
      <button onClick={onToggle} className="flex w-full items-center gap-4 px-5 py-4 text-left hover:bg-hover" aria-expanded={open}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold text-ink">{p.label}</span>
            {p.avoidable === true && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-positive">Avoidable</span>}
            {p.avoidable === null && <span className="rounded-full bg-hover px-2 py-0.5 text-[11px] font-medium text-ink-2">Worth reviewing</span>}
          </div>
          <div className="mt-0.5 truncate text-[12px] text-ink-3">
            {p.count} charge{p.count === 1 ? '' : 's'} · last {fmtShort(p.last_date)} · {p.accounts.join(', ')}
          </div>
        </div>
        <Money value={Number(p.total)} className="text-[17px] font-semibold text-ink" />
        <CaretDown size={14} className={cx('text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="border-t border-line px-5 pb-5 pt-4">
          {p.facts.length > 0 && (
            <ul className="mb-4 space-y-1.5">
              {p.facts.map((f) => <li key={f} className="text-[14px] leading-relaxed text-ink-2">{f}</li>)}
            </ul>
          )}
          {p.steps.length > 0 && (
            <div className="rounded-xl bg-accent-soft p-4">
              <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-ink"><Lightbulb size={16} weight="fill" className="text-positive" /> How to stop paying this</div>
              <ol className="list-decimal space-y-1.5 pl-5 text-[14px] leading-relaxed text-ink">
                {p.steps.map((s) => <li key={s}>{s}</li>)}
              </ol>
            </div>
          )}
          {p.script && (
            <div className="mt-3 rounded-xl border border-line p-4">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-[13px] font-semibold text-ink"><ChatText size={16} /> Ask for it back</span>
                <CopyButton text={p.script} />
              </div>
              <p className="text-[14px] italic leading-relaxed text-ink-2">"{p.script}"</p>
            </div>
          )}
          {p.needs.length > 0 && (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-dashed border-line-strong p-3 text-[13px] text-ink-2">
              <Question size={16} className="mt-0.5 shrink-0 text-ink-3" />
              <span>
                Sharper advice needs one detail Plaid can't see: {p.needs.map((n) => n.ask).join(' ')}{' '}
                <Link to="/accounts" className="font-medium text-accent underline underline-offset-2">Add it in Accounts</Link>.
              </span>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

export default function Fees() {
  const f = useFilters('12m')
  const q = useQuery({ queryKey: ['fees', f.start, f.end], queryFn: () => api.fees({ start: f.start, end: f.end }), placeholderData: keepPreviousData })
  const d = q.data
  const [open, setOpen] = useState<string | null>(null)
  const openKey = open ?? d?.playbook[0]?.type ?? null

  return (
    <>
      <PageHeader title="Fees" sub="Every fee and interest charge found in your accounts, and how to stop each one."><DateRangePicker f={f} /></PageHeader>
      <ErrorNote error={q.error} />
      {!d ? <Skeleton className="h-[480px] rounded-[18px]" /> : d.count === 0 ? (
        <Panel><Empty title="No fees in this range" icon={<PiggyBank size={20} />}>Nothing that looks like a bank fee or interest charge. Keep it that way.</Empty></Panel>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          <Panel className="lg:col-span-12">
            <div className="grid gap-4 px-5 pt-5 sm:grid-cols-3">
              <div>
                <div className="text-[13px] text-ink-3">Paid in fees and interest</div>
                <div className="mt-1 text-[34px] font-semibold leading-none tracking-tight text-ink"><Money value={Number(d.total)} size="hero" /></div>
                <div className="mt-2 text-[13px] text-ink-3">{d.count} charges · {fmtShort(d.start)} – {fmtShort(d.end)}</div>
              </div>
              <div>
                <div className="text-[13px] text-ink-3">Avoidable</div>
                <div className="mt-1 text-[34px] font-semibold leading-none tracking-tight text-positive"><Money value={Number(d.avoidable)} size="hero" /></div>
                <div className="mt-2 text-[13px] text-ink-3">{Math.round((Number(d.avoidable) / Number(d.total)) * 100)}% of it has a fix below</div>
              </div>
              <div className="sm:col-span-1"><ByMonth d={d} /></div>
            </div>
            <div className="h-4" />
          </Panel>

          <div className="flex flex-col gap-3 lg:col-span-7">
            {d.playbook.map((p, i) => (
              <Play key={p.type} p={p} i={i} open={openKey === p.type} onToggle={() => setOpen(openKey === p.type ? '' : p.type)} />
            ))}
          </div>

          <Panel className="self-start lg:col-span-5">
            <PanelHeader title="Every fee" sub={`${d.fees.length} charges`} />
            <ul className="mt-2 max-h-[640px] divide-y divide-line overflow-y-auto pb-1">
              {d.fees.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] text-ink">{t.fee_label}</div>
                    <div className="truncate text-[12px] text-ink-3">{fmtShort(t.date)} · {t.account_name} ··{t.account_mask}</div>
                  </div>
                  <Money value={Number(t.amount)} className="text-[14px] font-medium text-ink" />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      )}
    </>
  )
}
