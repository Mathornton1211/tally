import {
  CaretDown, Check, Copy, Phone, Repeat, Envelope, TrendUp, Lifebuoy,
} from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Subscription } from '../api'
import {
  cx, Empty, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, PanelHeader, Skeleton,
} from '../components/ui'
import { cadenceLabel, fmtShort, money, money0, relativeDays } from '../lib/format'

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => { setDone(true); setTimeout(() => setDone(false), 1800) },
          () => { /* blocked in some contexts; the text is on screen regardless */ },
        )
      }}
      className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] text-ink-2 hover:bg-hover hover:text-ink"
    >
      {done ? <Check size={11} weight="bold" /> : <Copy size={11} />}
      {done ? 'Copied' : 'Copy'}
    </button>
  )
}

/** Whitespace in these carries meaning, so it is preserved rather than collapsed. */
function Script({ title, when, icon: Icon, text }: {
  title: string; when: string; icon: typeof Phone; text: string
}) {
  return (
    <div className="mt-3">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
            <Icon size={13} className="text-ink-3" />{title}
          </div>
          <div className="text-[11px] text-ink-3">{when}</div>
        </div>
        <CopyButton text={text} />
      </div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-ink-2">
        {text}
      </pre>
    </div>
  )
}

function Row({ s }: { s: Subscription }) {
  const [open, setOpen] = useState(false)
  const rose = s.increased_from != null

  return (
    <li className="px-5 py-3">
      <button onClick={() => setOpen(!open)} className="w-full text-left">
        <div className="flex items-center gap-3">
          <MerchantAvatar logo={s.logo_url} icon="Repeat" name={s.name} size={32} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="truncate text-[14px] font-medium text-ink">{s.name}</span>
              {rose && (
                <span className="inline-flex items-center gap-1 rounded-full bg-warn-soft px-1.5 py-0.5 text-[11px] text-warn">
                  <TrendUp size={10} weight="bold" />
                  up from {money0(Number(s.increased_from))}
                </span>
              )}
            </div>
            <div className="truncate text-[12px] text-ink-3 tnum">
              {money(Number(s.amount))} {(cadenceLabel[s.cadence] ?? s.cadence).toLowerCase()}
              {' · '}{money0(Number(s.annual))} a year
              {' · '}next {relativeDays(s.next_date).toLowerCase()}
            </div>
          </div>
          <div className="hidden shrink-0 text-right sm:block">
            <Money value={Number(s.paid_so_far)} className="text-[14px] text-ink" />
            <div className="text-[11px] text-ink-3">
              paid since {fmtShort(s.since)}
            </div>
          </div>
          <CaretDown size={13} className={cx('shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
        </div>
      </button>

      {open && (
        <div className="mt-2 rounded-xl bg-surface-2 p-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Charged', value: `${s.charges}×` },
              { label: 'Held for', value: `${s.months} months` },
              { label: 'Paid so far', value: money(Number(s.paid_so_far)) },
              { label: 'On', value: s.account_name },
            ].map((f) => (
              <div key={f.label}>
                <div className="text-[11px] text-ink-3">{f.label}</div>
                <div className="truncate text-[13px] font-medium tnum text-ink">{f.value}</div>
              </div>
            ))}
          </div>

          {s.note && (
            <p className="rounded-xl bg-surface-2 px-3 py-2.5 text-[12px] text-ink-2">{s.note}</p>
          )}
          {s.cancel_script && (
            <Script
              title="On the phone"
              when="The one that works. Retention offers are held behind the word cancel."
              icon={Phone}
              text={s.cancel_script}
            />
          )}
          {s.cancel_email && (
            <Script
              title="By email"
              when="For the ones with no phone line. Short on purpose."
              icon={Envelope}
              text={s.cancel_email}
            />
          )}
          {s.lower_email && (
            <Script
              title="Keep it, pay less"
              when="If you want the thing and not the price. Ask before you threaten to leave."
              icon={Lifebuoy}
              text={s.lower_email}
            />
          )}
        </div>
      )}
    </li>
  )
}

export default function Subscriptions() {
  const q = useQuery({ queryKey: ['subscriptions'], queryFn: api.subscriptions })
  const d = q.data

  return (
    <>
      <PageHeader
        title="Subscriptions"
        sub="Every recurring charge, and a way out of each one."
      />
      <ErrorNote error={q.error} />

      {!d ? (
        <div className="grid gap-4">
          <Skeleton className="h-20 rounded-[18px]" />
          <Skeleton className="h-64 rounded-[18px]" />
        </div>
      ) : d.subscriptions.length === 0 ? (
        <Panel>
          <Empty title="No recurring charges found" icon={<Repeat size={20} />}>
            Tally spots these by looking for the same merchant charging the same amount on a regular
            cadence, so it needs a few months of history before anything shows up here.
          </Empty>
        </Panel>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-3">
            {[
              { label: 'A month', value: Number(d.monthly_total), sub: 'across all of them' },
              { label: 'A year', value: Number(d.annual_total), sub: 'if nothing changes' },
              { label: 'Paid so far', value: Number(d.paid_so_far_total), sub: 'since each one started' },
            ].map((t, i) => (
              <div key={t.label} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">
                  <Money value={t.value} size="lg" />
                </div>
                <div className="mt-0.5 text-[11px] text-ink-3">{t.sub}</div>
              </div>
            ))}
          </div>

          <Panel className="mb-4">
            <PanelHeader
              title="What they will offer you"
              sub="In this order. Knowing the sequence is most of the advantage — the first offer is never the last one."
            />
            <ol className="mt-3 divide-y divide-line border-y border-line">
              {d.ladder.map((step, i) => (
                <li key={step} className="flex gap-3 px-5 py-2">
                  <span className="shrink-0 text-[12px] font-medium tnum text-ink-3">{i + 1}</span>
                  <span className="text-[13px] text-ink-2">{step}</span>
                </li>
              ))}
            </ol>
            <ul className="px-5 py-3">
              {d.tips.map((tip) => (
                <li key={tip} className="flex gap-2 py-1 text-[12px] leading-relaxed text-ink-3">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-3" />
                  <span>{tip}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel>
            <PanelHeader
              title="Running now"
              sub="Biggest first. Open one for the scripts."
            />
            <ul className="mt-2 divide-y divide-line">
              {d.subscriptions.map((s) => <Row key={s.name} s={s} />)}
            </ul>
          </Panel>
        </>
      )}
    </>
  )
}
