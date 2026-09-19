import { Check, Info, LinkSimple, Receipt as ReceiptIcon, Trash, UploadSimple } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type Receipt } from '../api'
import { Button, cx, Empty, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, Skeleton } from '../components/ui'
import { fmtShort, money } from '../lib/format'

export function ReceiptDropzone({ transactionId, onDone, compact }: { transactionId?: string; onDone?: () => void; compact?: boolean }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const upload = useMutation({
    mutationFn: (files: File[]) => Promise.all(files.map((f) => api.uploadReceipt(f, transactionId))),
    onSuccess: () => { qc.invalidateQueries(); onDone?.() },
  })
  const pick = (list: FileList | null) => { if (list?.length) upload.mutate(Array.from(list)) }

  return (
    <div>
      <button
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files) }}
        className={cx('flex w-full flex-col items-center justify-center gap-1 rounded-xl border border-dashed text-ink-2 transition-colors',
          compact ? 'px-3 py-3' : 'px-6 py-8',
          over ? 'border-accent bg-accent-soft text-ink' : 'border-line-strong hover:bg-hover')}
      >
        <UploadSimple size={compact ? 16 : 22} />
        <span className={cx('font-medium', compact ? 'text-[12px]' : 'text-[14px]')}>
          {upload.isPending ? 'Uploading…' : compact ? 'Attach a receipt' : 'Drop receipts here, or click to choose'}
        </span>
        {!compact && <span className="text-[12px] text-ink-3">Photos or PDFs, up to 12MB each</span>}
      </button>
      <input ref={input} type="file" accept="image/*,application/pdf" multiple hidden
             onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
      {upload.isError && <div className="mt-2 text-[12px] text-negative">{(upload.error as Error).message}</div>}
    </div>
  )
}

function Card({ r }: { r: Receipt }) {
  const qc = useQueryClient()
  const [picking, setPicking] = useState(false)
  const cands = useQuery({ queryKey: ['receipt-cands', r.id], queryFn: () => api.receiptCandidates(r.id), enabled: picking })
  const match = useMutation({
    mutationFn: (txnId: string) => api.patchReceipt(r.id, { transaction_id: txnId }),
    onSuccess: () => { setPicking(false); qc.invalidateQueries() },
  })
  const detach = useMutation({ mutationFn: () => api.patchReceipt(r.id, { detach: true }), onSuccess: () => qc.invalidateQueries() })
  const del = useMutation({ mutationFn: () => api.deleteReceipt(r.id), onSuccess: () => qc.invalidateQueries() })
  const isImage = r.content_type.startsWith('image/')

  return (
    <Panel className="flex flex-col overflow-hidden">
      <a href={`/api/receipts/${r.id}/file`} target="_blank" rel="noreferrer"
         className="flex h-40 items-center justify-center overflow-hidden border-b border-line bg-surface-2">
        {isImage
          ? <img src={`/api/receipts/${r.id}/file`} alt={r.filename} className="h-full w-full object-cover" loading="lazy" />
          : <div className="flex flex-col items-center gap-1 text-ink-3"><ReceiptIcon size={26} /><span className="text-[12px]">PDF</span></div>}
      </a>
      <div className="px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[14px] font-medium text-ink">{r.merchant ?? r.filename}</span>
          {r.amount != null && <Money value={Number(r.amount)} className="text-[14px] text-ink" />}
        </div>
        <div className="mt-0.5 text-[12px] text-ink-3">
          {r.receipt_date ? fmtShort(r.receipt_date) : `uploaded ${fmtShort(r.created_at.slice(0, 10))}`}
          {r.ocr_source === 'tesseract' && ' · read automatically'}
        </div>

        {r.transaction_id ? (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-accent-soft px-2.5 py-2">
            <Check size={14} weight="bold" className="shrink-0 text-positive" />
            <div className="min-w-0 flex-1 text-[12px]">
              <div className="truncate font-medium text-ink">{r.display_name}</div>
              <div className="truncate text-ink-3">
                {r.txn_date && fmtShort(r.txn_date)} · {money(Number(r.txn_amount))} · {r.account_name}
                {r.matched_by === 'auto' && ' · matched automatically'}
              </div>
            </div>
            <button onClick={() => detach.mutate()} className="shrink-0 text-[11px] text-ink-3 hover:text-ink">Undo</button>
          </div>
        ) : (
          <div className="mt-2">
            {!picking ? (
              <Button className="w-full" onClick={() => setPicking(true)}><LinkSimple size={14} /> Match to a transaction</Button>
            ) : (
              <div className="rounded-lg border border-line">
                {cands.isLoading && <div className="px-3 py-2 text-[12px] text-ink-3">Looking…</div>}
                {cands.data?.length === 0 && <div className="px-3 py-2 text-[12px] text-ink-3">Nothing close. Try a wider date or edit the amount.</div>}
                <ul className="max-h-56 divide-y divide-line overflow-y-auto">
                  {cands.data?.map((c) => (
                    <li key={c.id}>
                      <button onClick={() => match.mutate(c.id)} disabled={match.isPending}
                              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-hover">
                        <MerchantAvatar logo={c.logo_url} icon={c.category_icon} name={c.display_name} size={24} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] text-ink">{c.display_name}</div>
                          <div className="truncate text-[11px] text-ink-3">{fmtShort(c.date)} · {c.account_name} {c.exact_amount && '· exact amount'}</div>
                        </div>
                        <Money value={Number(c.amount)} className="text-[12px] text-ink" />
                      </button>
                    </li>
                  ))}
                </ul>
                <button onClick={() => setPicking(false)} className="w-full px-3 py-1.5 text-[12px] text-ink-3 hover:text-ink">Cancel</button>
              </div>
            )}
          </div>
        )}
      </div>
      <div className="mt-auto flex justify-end border-t border-line px-3 py-1.5">
        <button onClick={() => del.mutate()} className="inline-flex items-center gap-1 text-[11px] text-ink-3 hover:text-negative">
          <Trash size={11} /> Delete
        </button>
      </div>
    </Panel>
  )
}

export default function Receipts() {
  const [filter, setFilter] = useState<'all' | 'unmatched'>('all')
  const q = useQuery({ queryKey: ['receipts', filter], queryFn: () => api.receipts(filter === 'unmatched' ? { unmatched: 'true' } : {}) })
  const d = q.data

  return (
    <>
      <PageHeader title="Receipts" sub="Keep the paper with the charge. Useful at tax time, and for anything you may return.">
        {d && d.unmatched > 0 && (
          <Button onClick={() => setFilter(filter === 'all' ? 'unmatched' : 'all')}>
            {filter === 'all' ? `Show ${d.unmatched} unmatched` : 'Show all'}
          </Button>
        )}
      </PageHeader>
      <ErrorNote error={q.error} />
      <div className="mb-4"><ReceiptDropzone /></div>
      {d && !d.ocr && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-line bg-surface px-4 py-3 text-[12px] text-ink-3">
          <Info size={14} className="mt-0.5 shrink-0" />
          Automatic reading is off on this server, so amounts and dates need filling in by hand. It works on the home server, where tesseract is installed.
        </div>
      )}
      {!d ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-64 rounded-[18px]" />)}</div>
      ) : d.receipts.length === 0 ? (
        <Panel><Empty title="No receipts yet" icon={<ReceiptIcon size={20} />}>
          Snap a photo at the register and drop it here, or attach one from any transaction.
        </Empty></Panel>
      ) : (
        <>
          <div className="mb-3 text-[13px] text-ink-3">
            {d.total} receipt{d.total === 1 ? '' : 's'} · {d.unmatched} unmatched · {money(Number(d.total_amount))} captured
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {d.receipts.map((r) => <Card key={r.id} r={r} />)}
          </div>
        </>
      )}
    </>
  )
}
