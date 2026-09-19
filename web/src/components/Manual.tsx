import { Plus, X } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { iso } from '../lib/format'
import { Button, ErrorNote, Panel } from './ui'

const TYPES = [
  { value: 'depository', label: 'Cash or bank', hint: 'wallet cash, an account Plaid cannot link' },
  { value: 'credit', label: 'Card or debt', hint: 'a card that will not link, money you owe someone' },
  { value: 'loan', label: 'Loan', hint: 'car, personal, family' },
  { value: 'investment', label: 'Investment', hint: 'crypto, a brokerage Plaid cannot see' },
  { value: 'other', label: 'Other asset', hint: 'a car, a deposit someone holds' },
]

const field = 'h-10 w-full rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3'

/** Add something Plaid cannot see. Without this it does not exist, and runway
 *  and net worth are quietly wrong. */
export function AddManualAccount({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: '', type: 'depository', subtype: '', institution_name: '', balance: '', limit: '' })
  const save = useMutation({
    mutationFn: () => api.createManualAccount({
      name: form.name.trim(), type: form.type, subtype: form.subtype.trim() || null,
      institution_name: form.institution_name.trim() || null,
      current_balance: Number(form.balance || 0),
      credit_limit: form.limit ? Number(form.limit) : null,
    }),
    onSuccess: () => { qc.invalidateQueries(); onClose() },
  })
  const owed = form.type === 'credit' || form.type === 'loan'

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}
            className="relative max-h-[92dvh] w-full max-w-[460px] overflow-y-auto rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
            style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-start justify-between px-6 pt-5">
          <div>
            <div className="text-[12px] text-ink-3">Add by hand</div>
            <h2 className="text-[18px] font-semibold tracking-tight text-ink">Something Plaid can't see</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="grid gap-4 px-6 pt-5">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">What is it</span>
            <input autoFocus required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                   placeholder="Cash in wallet, Dad's loan, the Civic" className={field} />
          </label>
          <div className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">Kind</span>
            <div className="grid gap-1.5">
              {TYPES.map((t) => (
                <label key={t.value} className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-line px-3 py-2 hover:bg-hover">
                  <input type="radio" name="type" value={t.value} checked={form.type === t.value}
                         onChange={() => setForm({ ...form, type: t.value })} className="mt-1 accent-[var(--accent)]" />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-ink">{t.label}</span>
                    <span className="block text-[12px] text-ink-3">{t.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">{owed ? 'Amount owed' : 'Value today'}</span>
            <input inputMode="decimal" value={form.balance} onChange={(e) => setForm({ ...form, balance: e.target.value.replace(/[^\d.]/g, '') })}
                   placeholder="0.00" className={field} />
            <span className="text-[12px] text-ink-3">You update this when it changes; Tally keeps the history.</span>
          </label>
          {form.type === 'credit' && (
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Credit limit (optional)</span>
              <input inputMode="decimal" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value.replace(/[^\d.]/g, '') })} className={field} />
            </label>
          )}
        </div>
        <div className="px-6 pt-3"><ErrorNote error={save.error} /></div>
        <div className="sticky bottom-0 mt-4 flex justify-end gap-2 border-t border-line bg-surface px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={save.isPending || !form.name.trim()}>
            {save.isPending ? 'Adding…' : 'Add account'}
          </Button>
        </div>
      </form>
    </div>
  )
}

export function AddManualTransaction({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const accounts = useQuery({ queryKey: ['all-accounts'], queryFn: api.allAccounts })
  const manual = (accounts.data ?? []).filter((a) => (a as { source?: string }).source === 'manual')
  const [form, setForm] = useState({ account_id: '', date: iso(new Date()), amount: '', name: '', category: '', direction: 'out' })
  const save = useMutation({
    mutationFn: () => api.createManualTransaction({
      account_id: form.account_id || manual[0]?.id, date: form.date,
      amount: form.direction === 'out' ? Number(form.amount) : -Number(form.amount),
      name: form.name.trim(), category: form.category || null,
    }),
    onSuccess: () => { qc.invalidateQueries(); onClose() },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}
            className="relative max-h-[92dvh] w-full max-w-[440px] overflow-y-auto rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
            style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-start justify-between px-6 pt-5">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">Add a transaction</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        {manual.length === 0 ? (
          <p className="px-6 py-6 text-[14px] text-ink-2">
            Transactions can only be added to accounts you added by hand. Add one first, like cash in your wallet.
          </p>
        ) : (
          <div className="grid gap-4 px-6 pt-5">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Account</span>
              <select value={form.account_id || manual[0].id} onChange={(e) => setForm({ ...form, account_id: e.target.value })} className={field}>
                {manual.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-[13px] font-medium text-ink">Date</span>
                <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={field} />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[13px] font-medium text-ink">Amount</span>
                <input required inputMode="decimal" value={form.amount} placeholder="0.00"
                       onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/[^\d.]/g, '') })} className={field} />
              </label>
            </div>
            <div className="inline-flex rounded-full border border-line-strong p-0.5">
              {[['out', 'Money out'], ['in', 'Money in']].map(([v, l]) => (
                <button type="button" key={v} onClick={() => setForm({ ...form, direction: v })}
                        className={`h-8 flex-1 rounded-full text-[13px] font-medium ${form.direction === v ? 'bg-ink text-page' : 'text-ink-2'}`}>{l}</button>
              ))}
            </div>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">What was it</span>
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="Farmers market, haircut, repaid Alex" className={field} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Category</span>
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className={field}>
                <option value="">Let Tally decide</option>
                {(meta.data?.categories ?? []).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </label>
          </div>
        )}
        <div className="px-6 pt-3"><ErrorNote error={save.error} /></div>
        <div className="sticky bottom-0 mt-4 flex justify-end gap-2 border-t border-line bg-surface px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {manual.length > 0 && (
            <Button variant="primary" type="submit" disabled={save.isPending || !form.amount || !form.name.trim()}>
              {save.isPending ? 'Adding…' : 'Add'}
            </Button>
          )}
        </div>
      </form>
    </div>
  )
}

export function ManualAccountsPanel() {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [value, setValue] = useState('')
  const accounts = useQuery({ queryKey: ['all-accounts'], queryFn: api.allAccounts })
  const manual = (accounts.data ?? []).filter((a) => (a as { source?: string }).source === 'manual')
  const save = useMutation({
    mutationFn: ({ id, balance }: { id: string; balance: number }) => api.setManualBalance(id, balance),
    onSuccess: () => { setEditing(null); qc.invalidateQueries() },
  })
  const del = useMutation({ mutationFn: api.deleteManualAccount, onSuccess: () => qc.invalidateQueries() })

  return (
    <Panel className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
        <div>
          <h2 className="text-[15px] font-semibold text-ink">Added by hand</h2>
          <div className="mt-0.5 text-[13px] text-ink-3">Cash, a card that won't link, money owed, a car. These count everywhere else in Tally.</div>
        </div>
        <Button onClick={() => setAdding(true)}><Plus size={14} weight="bold" /> Add</Button>
      </div>
      {manual.length > 0 && (
        <ul className="mt-3 divide-y divide-line pb-1">
          {manual.map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-5 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] text-ink">{a.name}</div>
                <div className="text-[12px] text-ink-3">{a.type === 'credit' || a.type === 'loan' ? 'owed' : 'value'} · updated by you</div>
              </div>
              {editing === a.id ? (
                <form onSubmit={(e) => { e.preventDefault(); save.mutate({ id: a.id, balance: Number(value) }) }} className="flex items-center gap-2">
                  <input autoFocus inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value.replace(/[^\d.]/g, ''))}
                         className="h-8 w-24 rounded-lg border border-line-strong bg-surface-2 px-2 text-right text-[13px] text-ink outline-none" />
                  <Button type="submit" variant="primary" disabled={save.isPending}>Save</Button>
                </form>
              ) : (
                <button onClick={() => { setEditing(a.id); setValue(String(a.current_balance ?? 0)) }}
                        className="text-[14px] font-medium text-ink hover:underline">
                  ${Number(a.current_balance ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </button>
              )}
              <button onClick={() => del.mutate(a.id)} className="text-[11px] text-ink-3 hover:text-negative">Remove</button>
            </li>
          ))}
        </ul>
      )}
      {adding && <AddManualAccount onClose={() => setAdding(false)} />}
    </Panel>
  )
}
