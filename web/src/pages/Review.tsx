import {
  Check, ClipboardText, Sparkle, Stack, Tag, X,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, type Category, type ReviewGroup, type ReviewItem, type ReviewQueue } from '../api'
import {
  Button, cx, ErrorNote, MerchantAvatar, Money, PageHeader, Panel, Segmented, Skeleton,
} from '../components/ui'
import { fmtShort, money } from '../lib/format'

type Window = '45' | '90' | '400'

const WINDOWS: { value: Window; label: string }[] = [
  { value: '45', label: '45 days' },
  { value: '90', label: '90 days' },
  { value: '400', label: 'Everything' },
]

/** Short labels for the chip. The full sentence comes from the API as `why`. */
const REASON_LABEL: Record<string, string> = {
  new_merchant: 'New here',
  uncategorised: 'Uncategorised',
  low_confidence: 'Unsure',
  guessed: 'Guessed',
  large: 'Large',
}
const REASON_ORDER = ['new_merchant', 'uncategorised', 'low_confidence', 'guessed', 'large']

const selectCx =
  'h-9 rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-ink outline-none focus:border-ink-3'

function CategorySelect({ value, categories, onPick, label, disabled }: {
  value?: string
  categories: Category[]
  onPick: (key: string) => void
  label: string
  disabled?: boolean
}) {
  return (
    <select
      aria-label={label}
      disabled={disabled}
      value={value ?? ''}
      onChange={(e) => e.target.value && onPick(e.target.value)}
      className={cx(selectCx, 'max-w-44 disabled:opacity-50')}
    >
      <option value="">Category…</option>
      {categories.filter((c) => c.kind === 'expense').map((c) => (
        <option key={c.key} value={c.key}>{c.label}</option>
      ))}
    </select>
  )
}

/**
 * The element that decides whether this page is usable on a real install.
 * Two years of history is two thousand decisions, and nobody makes those — so
 * the honest offer is a starting line rather than a backlog.
 */
function Backlog({ d, windowStart, onApplied }: {
  d: ReviewQueue
  windowStart: string
  onApplied: (q: ReviewQueue) => void
}) {
  const qc = useQueryClient()
  const clear = useMutation({
    mutationFn: () => api.reviewClearBacklog(windowStart),
    onSuccess: (q) => { onApplied(q); qc.invalidateQueries() },
  })
  if (!d.backlog) return null

  return (
    <Panel className="mb-4">
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
        <div className="min-w-0 max-w-[62ch]">
          <div className="text-[14px] font-medium text-ink">
            {d.backlog.toLocaleString()} charges from before {fmtShort(windowStart)}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
            Marking them reviewed is not skipping anything — nothing is deleted, hidden, or
            recategorised. It picks where you start, so the list ahead of you has an end.
          </p>
        </div>
        <Button variant="primary" onClick={() => clear.mutate()} disabled={clear.isPending}>
          <Check size={13} weight="bold" />
          {clear.isPending ? 'Marking…' : 'Start from here'}
        </Button>
      </div>
      <div className="px-5 pb-4"><ErrorNote error={clear.error} /></div>
    </Panel>
  )
}

function ReasonChip({ reason }: { reason: string }) {
  return (
    <span className="rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">
      {REASON_LABEL[reason] ?? reason.replace(/_/g, ' ')}
    </span>
  )
}

/** One decision for a dozen charges. This is where the time actually goes. */
function GroupRow({ g, categories, onApplied }: {
  g: ReviewGroup
  categories: Category[]
  onApplied: (q: ReviewQueue) => void
}) {
  const qc = useQueryClient()
  const apply = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.reviewApply({ ids: g.ids, ...body }),
    onSuccess: (q) => { onApplied(q); qc.invalidateQueries() },
  })
  const busy = apply.isPending

  return (
    <li className="flex flex-wrap items-center gap-3 px-5 py-3">
      <MerchantAvatar logo={g.logo_url} icon={g.category_icon} name={g.display_name} size={32} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[14px] font-medium text-ink">{g.display_name}</span>
          <ReasonChip reason={g.reason} />
        </div>
        <div className="mt-0.5 text-[12px] text-ink-3">
          {g.ids.length} charges · {money(Number(g.total))} · now {g.category_label}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <CategorySelect
          label={`Category for all ${g.ids.length} ${g.display_name} charges`}
          categories={categories}
          disabled={busy}
          onPick={(category) => apply.mutate({ category })}
        />
        <Button onClick={() => apply.mutate({})} disabled={busy}>
          <Check size={13} weight="bold" /> All fine
        </Button>
      </div>
      <ErrorNote error={apply.error} />
    </li>
  )
}

function ItemRow({ t, checked, onCheck, categories, onApplied }: {
  t: ReviewItem
  checked: boolean
  onCheck: (id: string, on: boolean) => void
  categories: Category[]
  onApplied: (q: ReviewQueue) => void
}) {
  const qc = useQueryClient()
  const apply = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.reviewApply({ ids: [t.id], ...body }),
    onSuccess: (q) => { onApplied(q); qc.invalidateQueries() },
  })
  const busy = apply.isPending

  return (
    <li className={cx('flex flex-wrap items-center gap-3 px-3 py-3 sm:px-5', checked && 'bg-hover')}>
      <label className="flex shrink-0 cursor-pointer items-center p-1.5" aria-label={`Select ${t.display_name}`}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onCheck(t.id, e.target.checked)}
          className="h-4 w-4 accent-[var(--accent)]"
        />
      </label>
      <MerchantAvatar logo={t.logo_url} icon={t.category_icon} name={t.display_name} size={32} />

      <div className="min-w-0 flex-1 basis-40">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="truncate text-[14px] font-medium text-ink">{t.display_name}</span>
          <span className="text-[12px] text-ink-3">{fmtShort(t.date)}</span>
        </div>
        <div className="truncate text-[12px] text-ink-3">
          {t.account_name}{t.account_mask ? ` ··${t.account_mask}` : ''} · {t.category_label}
          {t.owner_name && ` · ${t.owner_name}`}
        </div>
        <div className="mt-0.5 text-[11px] text-ink-3">{t.why}</div>
      </div>

      <Money value={-Number(t.amount)} className="shrink-0 text-[14px] font-medium text-ink" />

      <div className="flex shrink-0 items-center gap-2">
        <CategorySelect
          label={`Category for ${t.display_name}`}
          categories={categories}
          disabled={busy}
          onPick={(category) => apply.mutate({ category })}
        />
        <Button onClick={() => apply.mutate({})} disabled={busy} title="Confirm and take it off the list">
          <Check size={13} weight="bold" /> Looks right
        </Button>
      </div>
      <ErrorNote error={apply.error} />
    </li>
  )
}

/** Appears only when something is selected, and stays within thumb reach. */
function SelectionBar({ ids, categories, onApplied, onClear }: {
  ids: string[]
  categories: Category[]
  onApplied: (q: ReviewQueue) => void
  onClear: () => void
}) {
  const qc = useQueryClient()
  const [tag, setTag] = useState('')
  const apply = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.reviewApply({ ids, ...body }),
    onSuccess: (q) => { onApplied(q); onClear(); setTag(''); qc.invalidateQueries() },
  })
  if (!ids.length) return null
  const busy = apply.isPending

  return (
    // Above the mobile tab bar, not behind it: that nav is also fixed to the
    // bottom and renders later, so an equal z-index loses.
    <div className="fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-50 border-t border-line bg-surface/97 px-4 pb-3 pt-3 backdrop-blur lg:bottom-0 lg:left-[232px] lg:pb-[calc(env(safe-area-inset-bottom)+0.75rem)]">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-ink">{ids.length} selected</span>
        <button onClick={onClear} className="text-[12px] text-ink-3 hover:text-ink">Clear</button>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <CategorySelect
            label={`Category for ${ids.length} selected`}
            categories={categories}
            disabled={busy}
            onPick={(category) => apply.mutate({ category })}
          />
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => { e.preventDefault(); if (tag.trim()) apply.mutate({ add_tags: [tag.trim()] }) }}
          >
            <Tag size={13} className="text-ink-3" />
            <input
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              placeholder="Add a tag"
              aria-label={`Tag for ${ids.length} selected`}
              className="h-9 w-28 rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-ink outline-none"
            />
          </form>
          <Button variant="primary" onClick={() => apply.mutate({})} disabled={busy}>
            <Check size={13} weight="bold" /> {busy ? 'Working…' : 'Mark reviewed'}
          </Button>
        </div>
        <ErrorNote error={apply.error} />
      </div>
    </div>
  )
}

export default function Review() {
  const [days, setDays] = useState<Window>('45')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const qc = useQueryClient()

  const q = useQuery({
    queryKey: ['review', days],
    queryFn: () => api.reviewQueue(Number(days)),
  })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const categories = meta.data?.categories ?? []
  const d = q.data

  /**
   * A mutation answers with the queue it rebuilt, which saves a round trip —
   * but the API rebuilds it on its own default window, not the one on screen.
   * So the response is only trusted when those agree; otherwise refetch.
   */
  const onApplied = (next: ReviewQueue) => {
    setPicked(new Set())
    if (days === '45') qc.setQueryData(['review', days], next)
    else qc.invalidateQueries({ queryKey: ['review'] })
  }

  const toggle = (id: string, on: boolean) => {
    setPicked((prev) => {
      const s = new Set(prev)
      if (on) s.add(id)
      else s.delete(id)
      return s
    })
  }

  const grouped = useMemo(() => {
    const out = new Map<string, ReviewItem[]>()
    for (const r of REASON_ORDER) out.set(r, [])
    for (const t of d?.items ?? []) {
      if (!out.has(t.reason)) out.set(t.reason, [])
      out.get(t.reason)!.push(t)
    }
    return [...out.entries()].filter(([, v]) => v.length > 0)
  }, [d?.items])

  const windowStart = useMemo(() => {
    const dt = new Date()
    dt.setDate(dt.getDate() - Number(days))
    return dt.toISOString().slice(0, 10)
  }, [days])

  const allVisible = d?.items.map((t) => t.id) ?? []
  const allPicked = allVisible.length > 0 && allVisible.every((id) => picked.has(id))

  return (
    <>
      <PageHeader
        title="Review"
        sub="The charges Tally could not settle on its own. Everything else is left alone on purpose."
      >
        <Segmented value={days} options={WINDOWS} onChange={setDays} />
      </PageHeader>

      <ErrorNote error={q.error} />

      {!d ? (
        <div className="grid gap-4">
          <Skeleton className="h-20 rounded-[18px]" />
          <Skeleton className="h-64 rounded-[18px]" />
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {[
              {
                label: 'Need a look',
                node: <span>{d.total}</span>,
                sub: d.total === 1 ? 'charge in the last ' + d.window_days + ' days'
                  : `charges in the last ${d.window_days} days`,
              },
              {
                label: 'Reviewed',
                node: <span>{d.progress.reviewed.toLocaleString()}</span>,
                sub: `of ${d.progress.total_ever.toLocaleString()} charges, all time`,
              },
              {
                label: 'Today',
                node: <span>{d.progress.today}</span>,
                sub: d.progress.today === 1 ? 'cleared today' : 'cleared today',
              },
            ].map((t, i) => (
              <div key={t.label} className="panel rise px-4 py-3" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="text-[12px] text-ink-3">{t.label}</div>
                <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">{t.node}</div>
                <div className="mt-0.5 text-[11px] text-ink-3">{t.sub}</div>
              </div>
            ))}
          </div>

          <Backlog d={d} windowStart={windowStart} onApplied={onApplied} />

          {d.total === 0 ? (
            <Panel>
              <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
                <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-accent-soft text-positive">
                  <Check size={20} weight="bold" />
                </div>
                <div className="text-[15px] font-medium text-ink">Nothing to review</div>
                <p className="max-w-[48ch] text-[13px] text-ink-3">
                  Every charge in the last {d.window_days} days is either settled or clear enough to
                  leave alone.
                </p>
              </div>
            </Panel>
          ) : (
            <div className="grid gap-4">
              {d.groups.length > 0 && (
                <Panel>
                  <div className="flex items-start justify-between gap-3 px-5 pt-5">
                    <div>
                      <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight text-ink">
                        <Stack size={15} /> Same merchant, one decision
                      </h2>
                      <div className="mt-0.5 text-[13px] text-ink-3">
                        Pick a category once and it lands on all of them.
                      </div>
                    </div>
                  </div>
                  <ul className="mt-3 divide-y divide-line border-t border-line">
                    {d.groups.map((g) => (
                      <GroupRow
                        key={g.merchant_key}
                        g={g}
                        categories={categories}
                        onApplied={onApplied}
                      />
                    ))}
                  </ul>
                </Panel>
              )}

              {grouped.map(([reason, items]) => (
                <Panel key={reason}>
                  <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
                    <div className="min-w-0">
                      <h2 className="text-[15px] font-semibold tracking-tight text-ink">
                        {REASON_LABEL[reason] ?? reason}
                      </h2>
                      <div className="mt-0.5 max-w-[62ch] text-[13px] text-ink-3">
                        {d.reasons[reason as keyof typeof d.reasons] ?? items[0]?.why}
                      </div>
                    </div>
                    <span className="shrink-0 text-[12px] text-ink-3">{items.length}</span>
                  </div>
                  <ul className="mt-3 divide-y divide-line border-t border-line">
                    {items.map((t) => (
                      <ItemRow
                        key={t.id}
                        t={t}
                        checked={picked.has(t.id)}
                        onCheck={toggle}
                        categories={categories}
                        onApplied={onApplied}
                      />
                    ))}
                  </ul>
                </Panel>
              ))}

              <div className="flex flex-wrap items-center gap-3 px-1 pb-24">
                <button
                  onClick={() => setPicked(allPicked ? new Set() : new Set(allVisible))}
                  className="inline-flex items-center gap-1.5 text-[12px] text-ink-2 hover:text-ink"
                >
                  {allPicked ? <X size={12} /> : <ClipboardText size={12} />}
                  {allPicked ? 'Clear selection' : `Select all ${allVisible.length}`}
                </button>
                <span className="flex items-center gap-1.5 text-[11px] text-ink-3">
                  <Sparkle size={11} /> Changing anything counts as reviewing it — no second click.
                </span>
              </div>
            </div>
          )}
        </>
      )}

      <SelectionBar
        ids={[...picked]}
        categories={categories}
        onApplied={onApplied}
        onClear={() => setPicked(new Set())}
      />
    </>
  )
}
