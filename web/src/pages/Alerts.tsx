import { CheckCircle, Info, ShieldCheck, ShieldWarning, Warning, X } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Alert } from '../api'
import { Button, cx, Empty, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, Segmented, Skeleton } from '../components/ui'
import { fmtDay, fmtShort } from '../lib/format'

const SEVERITY = {
  high: { label: 'Act now', icon: ShieldWarning, tone: 'bg-bad-soft text-negative', ring: 'border-l-negative' },
  medium: { label: 'Review', icon: Warning, tone: 'bg-warn-soft text-warn', ring: 'border-l-warn' },
  low: { label: 'FYI', icon: Info, tone: 'bg-hover text-ink-2', ring: 'border-l-line-strong' },
}

const RULE_LABEL: Record<string, string> = {
  card_testing: 'Card testing', duplicate_charge: 'Duplicate charge', amount_outlier: 'Unusual amount',
  new_merchant_large: 'New merchant', foreign_activity: 'Outside the US', velocity: 'Many charges',
  reversible_fee: 'Fee you can dispute', price_increase: 'Price increase',
}

const FRAUD_STEPS = [
  'Lock or freeze the card in your bank\'s app right now. It stops new charges and can be undone.',
  'Call the number on the back of the card and say you did not make these charges. Ask for a new card number.',
  'Ask them to reverse every charge you do not recognize. Under federal rules your liability for card fraud reported promptly is small or zero.',
  'Update any subscriptions or autopays that used the old card number once the new card arrives.',
]

function AlertCard({ a, i }: { a: Alert; i: number }) {
  const qc = useQueryClient()
  const [trust, setTrust] = useState(false)
  const [showFraud, setShowFraud] = useState(a.status === 'fraud')
  const s = SEVERITY[a.severity]
  const Icon = s.icon
  const update = useMutation({
    mutationFn: ({ status, trust }: { status: Alert['status']; trust?: boolean }) => api.updateAlert(a.id, status, trust),
    onSuccess: () => qc.invalidateQueries(),
  })
  const resolved = a.status !== 'open'

  return (
    <Panel className={cx('overflow-hidden border-l-4', s.ring, resolved && 'opacity-75')} style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
      <div className="flex items-start gap-3 px-5 pt-4">
        <div className={cx('mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full', s.tone)}>
          <Icon size={18} weight="fill" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-3">
            <span className={cx('rounded-full px-2 py-0.5 font-medium', s.tone)}>{s.label}</span>
            <span>{RULE_LABEL[a.rule] ?? a.rule}</span>
            <span aria-hidden>·</span>
            <span>{fmtDay(a.occurred_on)}</span>
            {resolved && <span className="rounded-full bg-hover px-2 py-0.5 text-ink-2">
              {a.status === 'fraud' ? 'Reported as fraud' : a.status === 'expected' ? 'Marked as expected' : 'Dismissed'}
            </span>}
          </div>
          <h3 className="mt-1.5 text-[16px] font-semibold tracking-tight text-ink">{a.title}</h3>
          <p className="mt-1 max-w-[72ch] text-[14px] leading-relaxed text-ink-2">{a.detail}</p>
        </div>
      </div>

      {a.transactions.length > 0 && (
        <ul className="mx-5 mt-3 divide-y divide-line rounded-xl border border-line">
          {a.transactions.map((t) => (
            <li key={t.id} className="flex items-center gap-3 px-3 py-2">
              <MerchantAvatar logo={t.logo_url} icon={t.category_icon} name={t.display_name} size={28} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-ink">{t.display_name}</div>
                <div className="truncate font-mono text-[11px] text-ink-3">{t.name} · {fmtShort(t.date)} · {t.account_name} ··{t.account_mask}</div>
              </div>
              <Money value={-Number(t.amount)} className="text-[13px] font-medium text-ink" />
            </li>
          ))}
        </ul>
      )}

      {showFraud && (
        <div className="mx-5 mt-3 rounded-xl bg-bad-soft p-4">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-negative"><ShieldWarning size={16} weight="fill" /> What to do now</div>
          <ol className="list-decimal space-y-1.5 pl-5 text-[13px] leading-relaxed text-ink">
            {FRAUD_STEPS.map((step) => <li key={step}>{step}</li>)}
          </ol>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-surface-2 px-4 py-2.5">
        {!resolved ? (
          <>
            <Button variant="primary" disabled={update.isPending} onClick={() => update.mutate({ status: 'expected', trust })}>
              <CheckCircle size={15} weight="bold" /> That was me
            </Button>
            <Button disabled={update.isPending} onClick={() => { setShowFraud(true); update.mutate({ status: 'fraud' }) }}
                    className="text-negative">
              <ShieldWarning size={15} weight="bold" /> Not me
            </Button>
            <Button variant="ghost" disabled={update.isPending} onClick={() => update.mutate({ status: 'dismissed' })}>
              <X size={14} /> Dismiss
            </Button>
            {a.merchant_key && !['card_testing', 'reversible_fee'].includes(a.rule) && (
              <label className="ml-auto flex cursor-pointer items-center gap-2 text-[12px] text-ink-2">
                <input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} className="accent-[var(--accent)]" />
                Don't flag {a.transactions[0]?.display_name ?? 'this merchant'} for this again
              </label>
            )}
          </>
        ) : (
          <Button variant="ghost" disabled={update.isPending} onClick={() => { setShowFraud(false); update.mutate({ status: 'open' }) }}>
            Reopen
          </Button>
        )}
      </div>
      <ErrorNote error={update.error} />
    </Panel>
  )
}

export default function Alerts() {
  const [status, setStatus] = useState<'open' | 'all'>('open')
  const q = useQuery({ queryKey: ['alerts', status], queryFn: () => api.alerts(status) })
  const d = q.data

  return (
    <>
      <PageHeader title="Alerts" sub="Rules that watch every synced transaction. Each alert says exactly what tripped it.">
        <Segmented value={status} onChange={setStatus} options={[{ value: 'open', label: `Open${d ? ` · ${d.counts.open}` : ''}` }, { value: 'all', label: 'All' }]} />
      </PageHeader>

      <div className="mb-5 flex items-start gap-2 rounded-2xl border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">
        <Info size={16} className="mt-0.5 shrink-0 text-ink-3" />
        <span>Bank data reaches Tally a few hours after a charge. Keep push alerts on in each bank's app; Tally is the second net that also catches patterns the banks don't, like the same subscription on two cards.</span>
      </div>

      <ErrorNote error={q.error} />
      {!d ? (
        <div className="grid gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-44 rounded-[18px]" />)}</div>
      ) : d.alerts.length === 0 ? (
        <Panel><Empty title={status === 'open' ? 'All clear' : 'No alerts yet'} icon={<ShieldCheck size={20} />}>
          {status === 'open' ? 'Nothing needs a look right now. New transactions are checked after every sync.' : 'Alerts appear here as rules find something.'}
        </Empty></Panel>
      ) : (
        <div className="grid gap-3">{d.alerts.map((a, i) => <AlertCard key={a.id} a={a} i={i} />)}</div>
      )}
    </>
  )
}
