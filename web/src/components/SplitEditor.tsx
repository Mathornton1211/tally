import { Plus, Trash } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Txn } from '../api'
import { money } from '../lib/format'
import { Button, cx, ErrorNote } from './ui'

/** One charge, two or more things. The parts must add up to the charge, so the
 *  totals stay honest no matter how it is carved up. */
export function SplitEditor({ txn, onDone }: { txn: Txn; onDone: () => void }) {
  const qc = useQueryClient()
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const total = Math.abs(Number(txn.amount))
  const [parts, setParts] = useState([
    { amount: (total / 2).toFixed(2), category: txn.category },
    { amount: (total - Number((total / 2).toFixed(2))).toFixed(2), category: 'other' },
  ])
  const sum = parts.reduce((s, p) => s + Number(p.amount || 0), 0)
  const off = Number((sum - total).toFixed(2))

  const save = useMutation({
    mutationFn: () => api.splitTransaction(txn.id, parts.map((p) => ({
      amount: Number(p.amount) * (Number(txn.amount) < 0 ? -1 : 1), category: p.category,
    }))),
    onSuccess: () => { qc.invalidateQueries(); onDone() },
  })

  const set = (i: number, patch: Partial<{ amount: string; category: string }>) =>
    setParts(parts.map((p, j) => (i === j ? { ...p, ...patch } : p)))

  return (
    <div className="rounded-xl border border-line p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[13px] font-semibold text-ink">Split {money(total)}</span>
        <span className={cx('text-[12px] tnum', off === 0 ? 'text-ink-3' : 'text-negative')}>
          {off === 0 ? 'adds up' : off > 0 ? `${money(off)} over` : `${money(-off)} left`}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {parts.map((p, i) => (
          <div key={i} className="flex items-center gap-2">
            <input inputMode="decimal" value={p.amount} onChange={(e) => set(i, { amount: e.target.value.replace(/[^\d.]/g, '') })}
                   className="h-9 w-24 rounded-lg border border-line-strong bg-surface-2 px-2 text-right text-[13px] text-ink outline-none focus:border-ink-3" />
            <select value={p.category} onChange={(e) => set(i, { category: e.target.value })}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-line-strong bg-surface-2 px-2 text-[13px] text-ink outline-none">
              {(meta.data?.categories ?? []).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
            {parts.length > 2 && (
              <button onClick={() => setParts(parts.filter((_, j) => j !== i))} className="p-1 text-ink-3 hover:text-negative" aria-label="Remove part">
                <Trash size={14} />
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between">
        <button onClick={() => setParts([...parts, { amount: Math.max(0, -off).toFixed(2), category: 'other' }])}
                className="inline-flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
          <Plus size={12} /> Add a part
        </button>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onDone}>Cancel</Button>
          <Button variant="primary" disabled={off !== 0 || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? 'Splitting…' : 'Split'}
          </Button>
        </div>
      </div>
      <ErrorNote error={save.error} />
    </div>
  )
}
