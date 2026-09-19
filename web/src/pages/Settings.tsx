import { Check, CurrencyDollar, Globe, Info, Lock, ShieldCheck, UsersThree, Warning } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  ACCENTS, MODES, getAccent, getContrast, getMode,
  setAccent, setContrast, setMode, type Mode,
} from '../lib/theme'
import { api, type CurrencyStatus } from '../api'
import { Button, cx, ErrorNote, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtShort } from '../lib/format'

const field = 'h-10 w-full rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3'
const small = 'h-9 rounded-lg border border-line-strong bg-surface-2 px-2 text-[13px] text-ink outline-none focus:border-ink-3'

function Fact({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div>
      <div className="text-[12px] text-ink-3">{label}</div>
      <div className="mt-0.5 text-[15px] font-medium text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-ink-3">{sub}</div>}
    </div>
  )
}

/* ---------------------------------------------------------------- rates */

function AddRate({ d }: { d: CurrencyStatus }) {
  const qc = useQueryClient()
  const [currency, setCurrency] = useState(d.missing[0] ?? '')
  const [rate, setRate] = useState('')
  const [asOf, setAsOf] = useState('')

  const save = useMutation({
    mutationFn: () => api.setRate({ currency, rate: Number(rate), as_of: asOf || null }),
    onSuccess: (next) => { qc.setQueryData(['currency'], next); setRate('') },
  })

  // Anything the household actually holds, plus the majors, so a rate can be
  // set before the first transaction in that currency arrives.
  const options = [...new Set([...d.in_use, ...d.common.map((c) => c.code)])]
    .filter((c) => c !== d.home).sort()

  return (
    <form className="flex flex-wrap items-end gap-2 px-5 pb-4 pt-3"
          onSubmit={(e) => { e.preventDefault(); if (currency && Number(rate) > 0) save.mutate() }}>
      <label className="flex flex-col gap-1.5">
        <span className="text-[12px] text-ink-2">Currency</span>
        <select value={currency} onChange={(e) => setCurrency(e.target.value)} className={cx(small, 'w-24')}>
          <option value="">—</option>
          {options.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <div className="pb-2 text-[13px] text-ink-3">1 {currency || '···'} =</div>
      <label className="flex flex-col gap-1.5">
        <span className="text-[12px] text-ink-2">In {d.home}</span>
        <input inputMode="decimal" value={rate} placeholder="1.08" aria-label={`Value of one ${currency} in ${d.home}`}
               onChange={(e) => setRate(e.target.value.replace(/[^\d.]/g, ''))}
               className={cx(small, 'w-28 tnum')} />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-[12px] text-ink-2">From (optional)</span>
        <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={cx(small, 'w-40')} />
      </label>
      <Button type="submit" variant="primary" disabled={save.isPending || !currency || !Number(rate)}>
        {save.isPending ? 'Saving…' : 'Set rate'}
      </Button>
      <div className="w-full"><ErrorNote error={save.error} /></div>
    </form>
  )
}

function Currency() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['currency'], queryFn: api.currency })
  const setHome = useMutation({
    mutationFn: (c: string) => api.setHomeCurrency(c),
    onSuccess: (next) => { qc.setQueryData(['currency'], next); qc.invalidateQueries() },
  })
  const d = q.data

  return (
    <Panel>
      <PanelHeader
        title="Currency"
        sub="Every total in Tally is added up in one currency. Everything else converts into it."
      />
      {!d ? (
        <div className="p-5"><Skeleton className="h-24 rounded-xl" /></div>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3 px-5 pt-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-[12px] text-ink-2">Home currency</span>
              <select value={d.home} onChange={(e) => setHome.mutate(e.target.value)}
                      className={cx(field, 'w-60')} disabled={setHome.isPending}>
                {d.common.map((c) => (
                  <option key={c.code} value={c.code}>{c.code} — {c.name}</option>
                ))}
              </select>
            </label>
            {d.in_use.length > 1 && (
              <div className="pb-2.5 text-[12px] text-ink-3">
                In your accounts: {d.in_use.join(', ')}
              </div>
            )}
          </div>
          <div className="px-5"><ErrorNote error={setHome.error || q.error} /></div>

          {!d.multi ? (
            <p className="px-5 pb-5 pt-3 text-[13px] text-ink-3">
              Everything is in {d.home}, so there is nothing to convert. Rates appear here as soon as an
              account in another currency is connected.
            </p>
          ) : (
            <>
              {d.missing.length > 0 && (
                <div className="mx-5 mt-4 flex items-start gap-2 rounded-xl bg-warn-soft px-3 py-2.5 text-[12px] text-ink">
                  <Warning size={14} weight="fill" className="mt-0.5 shrink-0 text-warn" />
                  <span>
                    No rate for <b>{d.missing.join(', ')}</b>. Until you set one, those amounts are counted
                    one-for-one against {d.home} — so every total that includes them is wrong by however far
                    the real rate is from 1.
                  </span>
                </div>
              )}

              {d.rates.length > 0 && (
                <ul className="mt-4 divide-y divide-line border-y border-line">
                  {d.rates.map((r) => (
                    <li key={r.currency} className="flex items-center gap-3 px-5 py-2.5">
                      <CurrencyDollar size={14} className="shrink-0 text-ink-3" />
                      <span className="min-w-0 flex-1 text-[13px] text-ink">
                        1 {r.currency} = <span className="tnum">{Number(r.rate)}</span> {d.home}
                      </span>
                      <span className="shrink-0 text-[12px] text-ink-3">from {fmtShort(r.as_of)}</span>
                    </li>
                  ))}
                </ul>
              )}

              <AddRate d={d} />

              <p className="flex items-start gap-1.5 border-t border-line px-5 py-3 text-[11px] text-ink-3">
                <Info size={12} className="mt-0.5 shrink-0" />
                A rate applies from its date forward. Setting today's rate does not change what last
                year's holiday cost — the amount the bank showed is kept as it was, always.
              </p>
            </>
          )}
        </>
      )}
    </Panel>
  )
}

/* ---------------------------------------------------------------- install */

function Install() {
  const auth = useQuery({ queryKey: ['auth'], queryFn: api.authState })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const cfg = useQuery({ queryKey: ['config'], queryFn: api.config, staleTime: Infinity })
  const a = auth.data

  return (
    <Panel>
      <PanelHeader title="This install" sub="How Tally is running, and who can get in." />
      {!a ? (
        <div className="p-5"><Skeleton className="h-20 rounded-xl" /></div>
      ) : (
        <>
          <div className="grid gap-4 px-5 py-4 sm:grid-cols-3">
            <Fact
              label="Signing in"
              value={
                <span className="inline-flex items-center gap-1.5">
                  {a.mode === 'password' ? <Lock size={14} className="text-positive" />
                    : <ShieldCheck size={14} className="text-warn" />}
                  {a.mode === 'password' ? 'Tally asks' : 'A proxy in front'}
                </span>
              }
              sub={a.me ? `signed in as ${a.me.name}` : undefined}
            />
            <Fact
              label="Household"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <UsersThree size={14} className="text-ink-3" />
                  {a.household} {a.household === 1 ? 'person' : 'people'}
                </span>
              }
            />
            <Fact
              label="Plaid"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <Globe size={14} className="text-ink-3" />
                  {meta.data?.plaid_env ?? '—'}
                </span>
              }
              sub={meta.data?.plaid_env === 'sandbox' ? 'fake banks, free and unlimited' : undefined}
            />
            <Fact
              label="Version"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <Info size={14} className="text-ink-3" />
                  <span className="font-mono">{cfg.data?.version ?? '—'}</span>
                </span>
              }
              sub="also at /healthz"
            />
            <Fact
              label="Dates and times"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <Globe size={14} className="text-ink-3" />
                  {cfg.data?.timezone ?? '—'}
                </span>
              }
              sub="the app and the database both use this"
            />
            <Fact
              label="Local AI"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <Info size={14} className="text-ink-3" />
                  {cfg.data?.ai_enabled ? 'On' : 'Off'}
                </span>
              }
              sub={cfg.data?.ai_enabled ? 'your model, never a cloud one' : 'every page still works'}
            />
          </div>

          {a.mode === 'proxy' ? (
            <div className="mx-5 mb-5 flex items-start gap-2 rounded-xl bg-warn-soft px-3 py-2.5 text-[12px] text-ink">
              <Warning size={14} weight="fill" className="mt-0.5 shrink-0 text-warn" />
              <span>
                Tally is not checking who you are — it trusts whatever sits in front of it to have done
                that. So the person switcher here is a convenience for changing the view, <b>not a
                security boundary</b>: anyone who gets past the proxy can view as anyone. For a household
                where people keep private accounts, set <span className="font-mono">TALLY_AUTH=password</span> instead.
              </span>
            </div>
          ) : (
            <p className="mx-5 mb-5 flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2.5 text-[12px] text-ink-2">
              <Check size={14} weight="bold" className="mt-0.5 shrink-0 text-positive" />
              Each person signs in as themselves, so an account marked as one person's really is visible
              to that person alone.
            </p>
          )}
        </>
      )}
    </Panel>
  )
}


// ---------------------------------------------------------------- appearance

/**
 * Two axes, not a list of themes. Bundling "dark plus orange" into one named
 * theme gives six themes and none of the twelve combinations anybody wanted.
 *
 * Stored in this browser only. It is a preference about this screen, not a
 * fact about the household, so it never goes near the database.
 */
function Appearance() {
  const [mode, setModeState] = useState<Mode>(getMode)
  const [accent, setAccentState] = useState(getAccent)
  const [contrast, setContrastState] = useState(getContrast)

  return (
    <Panel>
      <PanelHeader title="Appearance" sub="Saved in this browser. Everyone here picks their own." />

      <div className="px-5 pb-5 pt-4">
        <div className="mb-2 text-[13px] font-medium text-ink">Light or dark</div>
        <div className="flex flex-wrap gap-2">
          {MODES.map((m) => (
            <button
              key={m.key}
              onClick={() => { setMode(m.key); setModeState(m.key) }}
              aria-pressed={mode === m.key}
              className={cx(
                'rounded-xl border px-3 py-2 text-left transition-colors',
                mode === m.key
                  ? 'border-ink-3 bg-hover text-ink'
                  : 'border-line text-ink-2 hover:bg-hover hover:text-ink',
              )}
            >
              <div className="text-[13px] font-medium">{m.label}</div>
              <div className="text-[11px] text-ink-3">{m.hint}</div>
            </button>
          ))}
        </div>

        <div className="mb-2 mt-5 text-[13px] font-medium text-ink">Accent</div>
        <div className="flex flex-wrap gap-2">
          {ACCENTS.map((a) => (
            <button
              key={a.key}
              onClick={() => { setAccent(a.key); setAccentState(a.key) }}
              aria-pressed={accent === a.key}
              title={a.label}
              className={cx(
                'flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3 text-[12px] transition-colors',
                accent === a.key
                  ? 'border-ink-3 bg-hover text-ink'
                  : 'border-line text-ink-2 hover:bg-hover hover:text-ink',
              )}
            >
              <span className="h-5 w-5 rounded-full" style={{ background: a.swatch }} />
              {a.label}
            </button>
          ))}
        </div>
        <p className="mt-2 max-w-[62ch] text-[12px] text-ink-3">
          Chart colours do not change with the accent. They are picked to stay apart from each
          other for colourblind readers, which a theme repainting them would quietly undo.
        </p>

        <label className="mt-5 flex max-w-[62ch] cursor-pointer items-start gap-2.5">
          <input
            type="checkbox"
            checked={contrast}
            onChange={(e) => { setContrast(e.target.checked); setContrastState(e.target.checked) }}
            className="mt-0.5 accent-[var(--accent)]"
          />
          <span>
            <span className="block text-[13px] font-medium text-ink">More contrast</span>
            <span className="block text-[12px] text-ink-3">
              Darker text and firmer borders. The default surfaces sit close together to keep a
              page of numbers calm, which is the wrong trade on a phone outdoors.
            </span>
          </span>
        </label>
      </div>
    </Panel>
  )
}

export default function Settings() {
  return (
    <>
      <PageHeader title="Settings" sub="How it looks, what it counts in, and how this install is put together." />
      <div className="grid gap-4">
        <Appearance />
        <Currency />
        <Install />
      </div>
    </>
  )
}
