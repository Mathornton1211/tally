import { X } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type AccountSettings } from '../api'
import { Button, ErrorNote } from './ui'

type Field = { key: keyof AccountSettings; label: string; help: string; suffix?: string; prefix?: string; show: (t: string, st: string | null) => boolean }

const FIELDS: Field[] = [
  { key: 'apy', label: 'Interest rate (APY)', help: 'What this account pays you. Used to spot cash earning less than it could.', suffix: '%', show: (t) => t === 'depository' },
  { key: 'min_balance_waiver', label: 'Balance that waives the monthly fee', help: 'Leave empty if there is no monthly fee.', prefix: '$', show: (t, st) => t === 'depository' && st === 'checking' },
  { key: 'apr', label: 'Purchase APR', help: 'On your statement. Orders which balance to pay first.', suffix: '%', show: (t) => t === 'credit' || t === 'loan' },
  { key: 'annual_fee', label: 'Annual fee', help: '0 if none.', prefix: '$', show: (t) => t === 'credit' },
  { key: 'reward_rate', label: 'Rewards, percent back', help: 'Rough flat rate. Used to check whether an annual fee pays for itself.', suffix: '%', show: (t) => t === 'credit' },
  { key: 'foreign_fee_pct', label: 'Foreign transaction fee', help: '0 if the card has none. Tally will point you to it for trips.', suffix: '%', show: (t) => t === 'credit' || t === 'depository' },
]

export function AccountDetails({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['account-settings', accountId], queryFn: () => api.accountSettings(accountId!), enabled: !!accountId })
  const [form, setForm] = useState<Record<string, string>>({})
  const [hidden, setHidden] = useState(false)

  useEffect(() => {
    if (!q.data) return
    const next: Record<string, string> = {}
    FIELDS.forEach((f) => { const v = q.data[f.key]; next[f.key] = v == null ? '' : String(Number(v)) })
    next.note = q.data.note ?? ''
    setForm(next)
    setHidden(q.data.hidden)
  }, [q.data])

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { note: form.note || null, hidden }
      FIELDS.forEach((f) => { body[f.key] = form[f.key] === '' || form[f.key] == null ? null : Number(form[f.key]) })
      return api.saveAccountSettings(accountId!, body as Partial<AccountSettings>)
    },
    onSuccess: () => { qc.invalidateQueries(); onClose() },
  })

  if (!accountId) return null
  const a = q.data
  const fields = a ? FIELDS.filter((f) => f.show(a.type, a.subtype)) : []

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label="Account details">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form
        onSubmit={(e) => { e.preventDefault(); save.mutate() }}
        className="relative max-h-[92dvh] w-full max-w-[480px] overflow-y-auto rounded-t-3xl border border-line bg-surface shadow-2xl sm:rounded-3xl"
        style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}
      >
        <div className="flex items-start justify-between px-6 pt-5">
          <div>
            <div className="text-[12px] text-ink-3">Account details</div>
            <h2 className="text-[18px] font-semibold tracking-tight text-ink">{a ? `${a.name}${a.mask ? ` ··${a.mask}` : ''}` : 'Loading…'}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        <p className="px-6 pt-2 text-[13px] leading-relaxed text-ink-3">
          Plaid doesn't share these. Each one you fill in turns an estimate on Fees and Insights into an exact number.
        </p>
        <div className="grid gap-4 px-6 pt-5">
          {fields.map((f) => (
            <label key={f.key} className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">{f.label}</span>
              <div className="flex items-center rounded-xl border border-line-strong bg-surface-2 focus-within:border-ink-3">
                {f.prefix && <span className="pl-3 text-[14px] text-ink-3">{f.prefix}</span>}
                <input
                  inputMode="decimal"
                  value={form[f.key] ?? ''}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value.replace(/[^\d.]/g, '') })}
                  className="h-10 w-full bg-transparent px-3 text-[14px] text-ink outline-none tnum"
                  placeholder="Not set"
                />
                {f.suffix && <span className="pr-3 text-[14px] text-ink-3">{f.suffix}</span>}
              </div>
              <span className="text-[12px] text-ink-3">{f.help}</span>
            </label>
          ))}
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">Note</span>
            <input value={form.note ?? ''} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Joint account, emergency fund…"
                   className="h-10 rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3" />
          </label>
          <label className="flex items-center gap-2.5 text-[13px] text-ink-2">
            <input type="checkbox" checked={hidden} onChange={(e) => setHidden(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
            Hide this account from totals and charts
          </label>
        </div>
        <div className="px-6 pt-3"><ErrorNote error={save.error || q.error} /></div>
        <div className="sticky bottom-0 mt-4 flex justify-end gap-2 border-t border-line bg-surface px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={save.isPending || !a}>{save.isPending ? 'Saving…' : 'Save'}</Button>
        </div>
      </form>
    </div>
  )
}
