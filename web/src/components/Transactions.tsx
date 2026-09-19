import { ArrowCounterClockwise, ArrowsSplit, Check, Clock, PencilSimple, Sparkle, Trash, X } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type Txn } from '../api'
import { fmtDay, parseDate } from '../lib/format'
import { CategoryIcon } from './icons'
import { ReceiptDropzone } from '../pages/Receipts'
import { SplitEditor } from './SplitEditor'
import { cx, MerchantAvatar, Money } from './ui'

/** Plaid: positive = money out. People read spending as negative and income as positive. */
export const signed = (t: Pick<Txn, 'amount'>) => -Number(t.amount)

export function TxnRow({ t, onOpen, compact }: { t: Txn; onOpen?: (t: Txn) => void; compact?: boolean }) {
  const amt = signed(t)
  return (
    <button
      onClick={() => onOpen?.(t)}
      className="group flex w-full items-center gap-3 px-5 py-2.5 text-left transition-colors hover:bg-hover"
    >
      <MerchantAvatar logo={t.logo_url} icon={t.category_icon} name={t.display_name} size={compact ? 34 : 38} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[14px] font-medium text-ink">{t.display_name}</span>
          {t.pending && (
            <span className="inline-flex items-center gap-1 rounded-full bg-hover px-1.5 py-0.5 text-[11px] text-ink-2">
              <Clock size={11} /> Pending
            </span>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-[12px] text-ink-3">
          <CategoryIcon name={t.category_icon} size={12} />
          <span className={cx(t.category === 'fees' && 'font-medium text-warn')}>{t.category_label}</span>
          <span aria-hidden>·</span>
          <span className="truncate">{t.account_name}{t.account_mask ? ` ··${t.account_mask}` : ''}</span>
          {compact && <><span aria-hidden>·</span><span>{fmtDay(t.date).replace(/^\w+, /, '')}</span></>}
        </div>
      </div>
      <div className={cx('text-right text-[14px] font-medium', t.kind === 'transfer' ? 'text-ink-3' : amt > 0 ? 'text-positive' : 'text-ink')}>
        <Money value={amt} showPlus />
      </div>
    </button>
  )
}

export function GroupedTxns({ rows, onOpen }: { rows: Txn[]; onOpen: (t: Txn) => void }) {
  const groups: { date: string; rows: Txn[]; net: number }[] = []
  for (const t of rows) {
    const last = groups[groups.length - 1]
    if (last && last.date === t.date) { last.rows.push(t); if (t.kind !== 'transfer') last.net += signed(t) }
    else groups.push({ date: t.date, rows: [t], net: t.kind !== 'transfer' ? signed(t) : 0 })
  }
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return (
    <div>
      {groups.map((g) => {
        const days = Math.round((today.getTime() - parseDate(g.date).getTime()) / 86400000)
        const label = days === 0 ? 'Today' : days === 1 ? 'Yesterday' : fmtDay(g.date)
        return (
          <div key={g.date}>
            <div className="sticky top-0 z-10 flex items-center justify-between border-y border-line bg-surface-2/95 px-5 py-1.5 text-[12px] font-medium text-ink-3 backdrop-blur first:border-t-0">
              <span>{label}</span>
              <span className="tnum">{g.net !== 0 && <Money value={g.net} showPlus />}</span>
            </div>
            <div className="divide-y divide-line">
              {g.rows.map((t) => <TxnRow key={t.id} t={t} onOpen={onOpen} />)}
            </div>
          </div>
        )
      })}
    </div>
  )
}


/**
 * Tags on one transaction. Hand-applied tags and tags a rule adds are merged
 * on read, so a rule's tag shows here but cannot be removed from this row --
 * removing it means changing the rule, which is the honest place to do it.
 */
function TagEditor({ txn }: { txn: Txn }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const own = txn.tags ?? []
  const save = useMutation({
    mutationFn: (tags: string[]) => api.setTxnTags(txn.id, tags),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['transactions'] }); qc.invalidateQueries({ queryKey: ['tags'] }) },
  })
  const existing = useQuery({ queryKey: ['tags'], queryFn: api.tags, staleTime: 60_000 })
  const suggestions = (existing.data?.tags ?? [])
    .map((t) => t.tag)
    .filter((t) => !own.includes(t) && (!draft || t.startsWith(draft.toLowerCase())))
    .slice(0, 5)

  const add = (tag: string) => {
    const clean = tag.trim().toLowerCase()
    if (clean && !own.includes(clean)) save.mutate([...own, clean])
    setDraft('')
  }

  return (
    <div className="mt-5">
      <div className="mb-2 text-[13px] font-semibold text-ink">Tags</div>
      <div className="flex flex-wrap items-center gap-1.5">
        {own.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded-full bg-hover px-2 py-1 text-[12px] text-ink-2">
            {t}
            <button onClick={() => save.mutate(own.filter((x) => x !== t))}
                    className="text-ink-3 hover:text-negative" aria-label={`Remove ${t}`}>
              <X size={10} weight="bold" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(draft) } }}
          placeholder={own.length ? 'Add' : 'reimbursable, work, tax…'}
          aria-label="Add a tag"
          className="h-7 min-w-24 flex-1 rounded-full border border-line bg-surface-2 px-2.5 text-[12px] text-ink outline-none placeholder:text-ink-3 focus:border-line-strong"
        />
      </div>
      {suggestions.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {suggestions.map((t) => (
            <button key={t} onClick={() => add(t)}
                    className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3 hover:bg-hover hover:text-ink">
              + {t}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function TxnDrawer({ txn, onClose }: { txn: Txn | null; onClose: () => void }) {
  const qc = useQueryClient()
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const [note, setNote] = useState('')
  const [current, setCurrent] = useState<Txn | null>(txn)

  useEffect(() => { setCurrent(txn); setNote(txn?.note ?? ''); setApplied(null) }, [txn])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', k)
    return () => document.removeEventListener('keydown', k)
  }, [onClose])

  const [applied, setApplied] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [splitting, setSplitting] = useState(false)
  const unsplit = useMutation({
    mutationFn: () => api.unsplitTransaction(current!.id),
    onSuccess: () => qc.invalidateQueries(),
  })
  const removeManual = useMutation({
    mutationFn: () => api.deleteManualTransaction(current!.id),
    onSuccess: () => { qc.invalidateQueries(); onClose() },
  })
  const rename = useMutation({
    mutationFn: (name: string) => api.renameMerchant(current!.id, name),
    onSuccess: (res) => {
      setCurrent((c) => (c ? { ...c, display_name: res.name, name_source: 'user' } : c))
      setRenaming(null)
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'meta' })
    },
  })
  const preview = useQuery({
    queryKey: ['rule-preview', current?.merchant_key],
    queryFn: () => api.rulePreview(current!.merchant_key!),
    enabled: !!current?.merchant_key && !!current?.category_overridden,
  })
  const applyAll = useMutation({
    mutationFn: () => api.createCategoryRule(current!.merchant_key!, current!.category),
    onSuccess: (res) => {
      setApplied(`Applied to ${res.applied_to} transactions, including future ones`)
      setCurrent((c) => (c ? { ...c, category_overridden: false, category_from_rule: true } : c))
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'meta' })
    },
  })

  const funds = useQuery({ queryKey: ['funds'], queryFn: api.funds })
  const onFunds = useQuery({
    queryKey: ['funds-for', current?.id],
    queryFn: () => api.fundsForTransaction(current!.id),
    enabled: !!current?.id,
  })
  const linkFund = useMutation({
    mutationFn: ({ fundId, on }: { fundId: number; on: boolean }) =>
      on ? api.removeFundSpend(fundId, current!.id) : api.addFundSpend(fundId, current!.id),
    onSuccess: () => qc.invalidateQueries(),
  })

  const receipts = useQuery({
    queryKey: ['receipts-for', current?.id],
    queryFn: () => api.receipts({ transaction_id: current!.id }),
    enabled: !!current?.id,
  })

  const save = useMutation({
    mutationFn: (body: { category?: string; note?: string; reset_category?: boolean }) => api.patchTransaction(txn!.id, body),
    onSuccess: (res) => {
      setCurrent((c) => (c ? { ...c, ...res } as Txn : c))
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'meta' })
    },
  })

  if (!txn || !current) return null
  const amt = signed(current)

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Transaction details">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l border-line bg-surface shadow-2xl"
             style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-center justify-between px-5 pt-4">
          <span className="text-[13px] text-ink-3">{fmtDay(current.date)}</span>
          <button onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="flex flex-col items-center gap-2 px-5 pb-6 pt-2 text-center">
          <MerchantAvatar logo={current.logo_url} icon={current.category_icon} name={current.display_name} size={60} />
          {renaming === null ? (
            <button onClick={() => setRenaming(current.display_name)} className="group mt-1 flex items-center gap-1.5 text-[17px] font-semibold text-ink" title="Rename this merchant">
              {current.display_name}
              <PencilSimple size={14} className="text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); if (renaming.trim()) rename.mutate(renaming.trim()) }} className="mt-1 flex items-center gap-1.5">
              <input autoFocus value={renaming} onChange={(e) => setRenaming(e.target.value)} maxLength={48}
                     onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setRenaming(null) } }}
                     className="h-9 w-56 rounded-lg border border-line-strong bg-surface-2 px-2.5 text-center text-[15px] font-semibold text-ink outline-none focus:border-ink-3" />
              <button type="submit" disabled={rename.isPending} className="rounded-full bg-accent p-2 text-accent-ink" aria-label="Save name"><Check size={14} weight="bold" /></button>
            </form>
          )}
          {current.name_source === 'llm' && renaming === null && (
            <span className="inline-flex items-center gap-1 text-[11px] text-ink-3"><Sparkle size={11} weight="fill" /> Name written by your local AI from the bank text</span>
          )}
          <div className={cx('text-[34px] font-semibold tracking-tight', amt > 0 && current.kind !== 'transfer' ? 'text-positive' : 'text-ink')}>
            <Money value={amt} showPlus size="lg" />
          </div>
          {current.pending && <span className="rounded-full bg-hover px-2 py-0.5 text-[12px] text-ink-2">Pending</span>}
        </div>

        <dl className="mx-5 divide-y divide-line rounded-2xl border border-line text-[13px]">
          <div className="flex justify-between gap-4 px-4 py-3"><dt className="text-ink-3">Account</dt><dd className="text-right text-ink">{current.institution} {current.account_name}{current.account_mask ? ` ··${current.account_mask}` : ''}</dd></div>
          <div className="flex justify-between gap-4 px-4 py-3"><dt className="text-ink-3">Bank description</dt><dd className="break-all text-right font-mono text-[12px] text-ink-2">{current.bank_text ?? current.name}</dd></div>
          {current.payment_channel && <div className="flex justify-between gap-4 px-4 py-3"><dt className="text-ink-3">Channel</dt><dd className="capitalize text-ink">{current.payment_channel.replace('_', ' ')}</dd></div>}
        </dl>

        <div className="px-5 pt-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-ink">Category</h3>
            {current.category_overridden && (
              <button onClick={() => save.mutate({ reset_category: true })} className="inline-flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
                <ArrowCounterClockwise size={12} /> Use bank's category
              </button>
            )}
          </div>
          {current.category_overridden && current.merchant_key && (preview.data?.count ?? 0) > 1 && (
            <div className="mb-2 flex items-center justify-between gap-3 rounded-xl bg-accent-soft px-3 py-2.5">
              <span className="text-[12px] text-ink">
                Use <b>{current.category_label}</b> for all {preview.data!.count} {current.display_name} transactions?
              </span>
              <button onClick={() => applyAll.mutate()} disabled={applyAll.isPending}
                      className="shrink-0 rounded-full bg-accent px-3 py-1 text-[12px] font-medium text-accent-ink disabled:opacity-50">
                {applyAll.isPending ? 'Applying…' : 'Apply to all'}
              </button>
            </div>
          )}
          {applied && <div className="mb-2 rounded-xl bg-hover px-3 py-2 text-[12px] text-ink-2">{applied}</div>}
          {current.category_from_rule && !applied && (
            <div className="mb-2 text-[12px] text-ink-3">Set by your rule for {current.display_name}.</div>
          )}
          {current.category_source === 'ai' && (
            <div className="mb-2 flex items-center gap-1.5 text-[12px] text-ink-3">
              <Sparkle size={12} weight="fill" className="text-positive" /> Plaid wasn't sure, so your local AI picked this. Tap another to correct it.
            </div>
          )}
          <div className="grid grid-cols-2 gap-1.5">
            {(meta.data?.categories ?? []).map((c) => {
              const on = c.key === current.category
              return (
                <button key={c.key} disabled={save.isPending} onClick={() => !on && save.mutate({ category: c.key })}
                        className={cx('flex items-center gap-2 rounded-xl border px-2.5 py-2 text-left text-[12px] transition-colors',
                          on ? 'border-accent bg-accent-soft font-medium text-ink' : 'border-line text-ink-2 hover:bg-hover hover:text-ink')}>
                  <CategoryIcon name={c.icon} size={15} />
                  <span className="flex-1 truncate">{c.label}</span>
                  {on && <Check size={13} weight="bold" className="text-accent" />}
                </button>
              )
            })}
          </div>
        </div>

        {funds.data && funds.data.funds.length > 0 && (
          <div className="px-5 pt-6">
            <h3 className="mb-2 text-[13px] font-semibold text-ink">Count toward something you are saving for</h3>
            <div className="flex flex-wrap gap-1.5">
              {funds.data.funds.filter((x) => !x.bought).map((x) => {
                const on = (onFunds.data ?? []).some((y) => y.id === x.id)
                return (
                  <button key={x.id} disabled={linkFund.isPending}
                          onClick={() => linkFund.mutate({ fundId: x.id, on })}
                          className={cx('rounded-full border px-2.5 py-1 text-[12px]',
                            on ? 'border-accent bg-accent-soft font-medium text-ink' : 'border-line text-ink-2 hover:bg-hover')}>
                    {on && <Check size={11} weight="bold" className="mr-1 inline text-accent" />}{x.name}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        <div className="px-5 pt-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-ink">Split</h3>
            {!splitting && current.category_source !== 'split' && (
              <button onClick={() => setSplitting(true)} className="inline-flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
                <ArrowsSplit size={12} /> Split into parts
              </button>
            )}
          </div>
          {splitting ? (
            <SplitEditor txn={current} onDone={() => setSplitting(false)} />
          ) : current.category_source === 'split' ? (
            <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2 text-[12px] text-ink-2">
              Part of a split charge.
              <button onClick={() => unsplit.mutate(undefined)} className="text-ink-3 hover:text-ink">Undo split</button>
            </div>
          ) : (
            <p className="text-[12px] text-ink-3">One charge that was really two things? Split it so each part lands in the right category.</p>
          )}
        </div>

        <div className="px-5 pt-6">
          <h3 className="mb-2 text-[13px] font-semibold text-ink">Receipt</h3>
          {receipts.data?.receipts.length ? (
            <ul className="mb-2 flex flex-wrap gap-2">
              {receipts.data.receipts.map((r) => (
                <li key={r.id}>
                  <a href={`/api/receipts/${r.id}/file`} target="_blank" rel="noreferrer"
                     className="block h-20 w-20 overflow-hidden rounded-xl border border-line bg-surface-2">
                    {r.content_type.startsWith('image/')
                      ? <img src={`/api/receipts/${r.id}/file`} alt={r.filename} className="h-full w-full object-cover" />
                      : <span className="flex h-full items-center justify-center text-[11px] text-ink-3">PDF</span>}
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
          <ReceiptDropzone transactionId={current.id} compact />
        </div>

        <div className="px-5 pb-8 pt-6">
          <label htmlFor="txn-note" className="mb-2 block text-[13px] font-semibold text-ink">Note</label>
          <textarea id="txn-note" value={note} onChange={(e) => setNote(e.target.value)}
                    onBlur={() => note !== (current.note ?? '') && save.mutate({ note })}
                    rows={3} placeholder="Add a note"
                    className="w-full resize-none rounded-xl border border-line-strong bg-surface-2 p-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-ink-3" />
          {save.isError && <p className="mt-2 text-[12px] text-negative">{(save.error as Error).message}</p>}

          <TagEditor txn={current} />
          {current.source === 'manual' && (
            <button onClick={() => removeManual.mutate(undefined)} disabled={removeManual.isPending}
                    className="mt-4 inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-negative">
              <Trash size={12} /> Delete this transaction
            </button>
          )}
        </div>
      </aside>
    </div>
  )
}
