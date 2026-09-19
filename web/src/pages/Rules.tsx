import {
  Check, Funnel, Info, PencilSimple, Plus, Prohibit, Scissors, Tag as TagIcon, Trash, Warning, X,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, type Rule } from '../api'
import { CategoryIcon } from '../components/icons'
import { Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtShort, money0 } from '../lib/format'

const field = 'h-10 w-full rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3'
const small = 'h-9 w-full rounded-lg border border-line-strong bg-surface-2 px-2 text-[13px] text-ink outline-none focus:border-ink-3'

const FIELDS = [
  { value: 'display_name', label: 'Merchant name', hint: 'the cleaned-up name you see in the list' },
  { value: 'bank_text', label: 'Bank description', hint: 'the raw text the bank sent, numbers and all' },
  { value: 'merchant_key', label: 'Merchant key', hint: 'the lower-cased name, for exact matches' },
] as const

const TYPES = [
  { value: 'contains', label: 'contains' },
  { value: 'equals', label: 'is exactly' },
  { value: 'regex', label: 'matches regex' },
] as const

type SplitRow = { category: string; percent: string; amount: string }
type Form = {
  name: string
  pattern: string
  match_field: Rule['match_field']
  match_type: Rule['match_type']
  min_amount: string
  max_amount: string
  account_id: string
  set_category: string
  set_name: string
  add_tags: string
  set_note: string
  priority: string
  enabled: boolean
  splitMode: 'none' | 'percent' | 'amount'
  split: SplitRow[]
}

const BLANK: Form = {
  name: '', pattern: '', match_field: 'display_name', match_type: 'contains',
  min_amount: '', max_amount: '', account_id: '', set_category: '', set_name: '',
  add_tags: '', set_note: '', priority: '0', enabled: true,
  splitMode: 'none', split: [{ category: '', percent: '50', amount: '' }, { category: '', percent: '50', amount: '' }],
}

function fromRule(r: Rule): Form {
  const mode = !r.split?.length ? 'none' : r.split[0].percent != null ? 'percent' : 'amount'
  return {
    name: r.name, pattern: r.pattern, match_field: r.match_field, match_type: r.match_type,
    min_amount: r.min_amount == null ? '' : String(r.min_amount),
    max_amount: r.max_amount == null ? '' : String(r.max_amount),
    account_id: r.account_id ?? '', set_category: r.set_category ?? '', set_name: r.set_name ?? '',
    add_tags: r.add_tags.join(', '), set_note: r.set_note ?? '', priority: String(r.priority),
    enabled: r.enabled, splitMode: mode,
    split: r.split?.length
      ? r.split.map((p) => ({
          category: p.category ?? '',
          percent: p.percent == null ? '' : String(p.percent),
          amount: p.amount == null ? '' : String(p.amount),
        }))
      : BLANK.split,
  }
}

const num = (s: string) => (s.trim() === '' ? null : Number(s))

function splitParts(f: Form) {
  if (f.splitMode === 'none') return null
  return f.split
    .filter((p) => p.category)
    .map((p) => (f.splitMode === 'percent'
      ? { category: p.category, percent: Number(p.percent || 0) }
      : { category: p.category, amount: Number(p.amount || 0) }))
}

function toBody(f: Form) {
  return {
    name: f.name.trim() || f.pattern.trim(),
    pattern: f.pattern.trim(),
    match_field: f.match_field,
    match_type: f.match_type,
    min_amount: num(f.min_amount),
    max_amount: num(f.max_amount),
    account_id: f.account_id || null,
    set_category: f.set_category || null,
    set_name: f.set_name.trim() || null,
    add_tags: f.add_tags.split(',').map((t) => t.trim()).filter(Boolean),
    set_note: f.set_note.trim() || null,
    split: splitParts(f),
    priority: Number(f.priority) || 0,
    enabled: f.enabled,
  }
}

/** A rule, sent back whole, with one thing changed. The API takes the full
 *  shape on every edit, so a toggle has to carry everything else with it. */
function ruleToBody(r: Rule, over: Record<string, unknown> = {}) {
  return {
    name: r.name, pattern: r.pattern, match_field: r.match_field, match_type: r.match_type,
    min_amount: r.min_amount, max_amount: r.max_amount, account_id: r.account_id,
    set_category: r.set_category, set_name: r.set_name, add_tags: r.add_tags,
    set_note: r.set_note, split: r.split, priority: r.priority, enabled: r.enabled, ...over,
  }
}

function splitProblem(f: Form): string | null {
  if (f.splitMode === 'none') return null
  const parts = f.split.filter((p) => p.category)
  if (parts.length < 2) return 'A split needs at least two parts, each with a category.'
  if (f.splitMode === 'percent') {
    const total = parts.reduce((a, p) => a + Number(p.percent || 0), 0)
    if (Math.abs(total - 100) > 0.01) return `The percentages add up to ${total}, not 100.`
  } else if (parts.some((p) => !Number(p.amount))) {
    return 'Every part needs an amount.'
  }
  return null
}

/* ---------------------------------------------------------------- preview */

/** The live preview. A rule you cannot see the effect of is a rule nobody
 *  trusts, so this runs as the form is typed rather than after saving. */
function Preview({ f }: { f: Form }) {
  const [settled, setSettled] = useState(f)
  useEffect(() => {
    const t = setTimeout(() => setSettled(f), 300)
    return () => clearTimeout(t)
  }, [f])

  const pattern = settled.pattern.trim()
  // The split is deliberately left out: a half-typed one is rejected by the
  // server, and it does not change which transactions match anyway.
  const body = useMemo(() => ({ ...toBody(settled), split: null, name: settled.name.trim() || 'preview' }),
    [settled])

  const q = useQuery({
    queryKey: ['rule-preview', JSON.stringify(body)],
    queryFn: () => api.previewRule(body),
    enabled: pattern.length > 0,
  })

  if (!pattern) {
    return (
      <div className="rounded-2xl border border-line bg-surface-2 px-4 py-6 text-center text-[13px] text-ink-3">
        Type something to match on and the transactions it would catch appear here.
      </div>
    )
  }
  if (q.isError) {
    return <div className="rounded-2xl border border-line bg-bad-soft px-4 py-3 text-[13px] text-negative">
      {(q.error as Error).message}
    </div>
  }
  if (!q.data) return <Skeleton className="h-40 rounded-2xl" />

  const d = q.data
  const stale = settled !== f || q.isFetching
  return (
    <div className={cx('rounded-2xl border border-line bg-surface-2 transition-opacity', stale && 'opacity-60')}>
      <div className="flex items-baseline justify-between gap-3 px-4 pt-3.5">
        <span className="text-[13px] font-medium text-ink">
          {d.matches === 0 ? 'Nothing matches this yet'
            : `${d.matches.toLocaleString()} transaction${d.matches === 1 ? '' : 's'} match`}
        </span>
        {d.matches > 0 && (
          <span className="text-[13px] text-ink-3 tnum">{money0(Number(d.total_amount))} in all</span>
        )}
      </div>
      {d.matches === 0 ? (
        <p className="px-4 pb-4 pt-1 text-[12px] text-ink-3">
          {settled.match_type === 'regex'
            ? 'A regular expression that is not valid simply matches nothing — check the pattern.'
            : 'Try a shorter pattern, or match on the bank description instead of the merchant name.'}
        </p>
      ) : (
        <>
          <ul className="mt-2 divide-y divide-line border-t border-line">
            {d.sample.map((s) => (
              <li key={s.id} className="flex items-center gap-3 px-4 py-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] text-ink">{s.display_name}</div>
                  <div className="truncate text-[11px] text-ink-3">
                    {fmtShort(s.date)} · {s.account_name}
                    {settled.match_field === 'bank_text' && s.bank_text ? ` · ${s.bank_text}` : ''}
                  </div>
                </div>
                <Money value={Number(s.amount)} className="shrink-0 text-[13px] text-ink-2" />
              </li>
            ))}
          </ul>
          {d.matches > d.sample.length && (
            <div className="px-4 py-2 text-[11px] text-ink-3">
              and {(d.matches - d.sample.length).toLocaleString()} more
            </div>
          )}
        </>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- editor */

function Editor({ rule, onClose }: { rule: Rule | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState<Form>(rule ? fromRule(rule) : BLANK)
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const set = (patch: Partial<Form>) => setF((prev) => ({ ...prev, ...patch }))
  const categories = (meta.data?.categories ?? []).filter((c) => c.kind === 'expense')

  const save = useMutation({
    mutationFn: () => (rule ? api.editRule(rule.id, toBody(f)) : api.createRule(toBody(f))),
    // A rule changes names, categories and tags across the whole app, so
    // everything is refetched rather than just the rules list.
    onSuccess: () => { qc.invalidateQueries(); onClose() },
  })

  const problem = splitProblem(f)
  const canSave = f.pattern.trim().length > 0 && !problem

  const setRow = (i: number, patch: Partial<SplitRow>) =>
    set({ split: f.split.map((r, j) => (j === i ? { ...r, ...patch } : r)) })

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center overflow-y-auto sm:items-center sm:p-6"
         role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form
        onSubmit={(e) => { e.preventDefault(); if (canSave) save.mutate() }}
        className="relative my-auto w-full max-w-[860px] rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
        style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}
      >
        <div className="flex items-start justify-between px-6 pt-5">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">
            {rule ? 'Edit rule' : 'New rule'}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close"
                  className="rounded-full p-1.5 text-ink-2 hover:bg-hover"><X size={18} /></button>
        </div>

        <div className="grid gap-6 px-6 pt-5 md:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
          {/* ---- what it matches ---- */}
          <div className="grid gap-4">
            <div>
              <div className="mb-2 text-[12px] font-medium uppercase tracking-wider text-ink-3">When</div>
              <div className="grid gap-2 sm:grid-cols-2">
                <select value={f.match_field} className={field}
                        onChange={(e) => set({ match_field: e.target.value as Rule['match_field'] })}>
                  {FIELDS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <select value={f.match_type} className={field}
                        onChange={(e) => set({ match_type: e.target.value as Rule['match_type'] })}>
                  {TYPES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <input
                autoFocus
                value={f.pattern}
                onChange={(e) => set({ pattern: e.target.value })}
                placeholder={f.match_type === 'regex' ? '^AMZN.*MKTP' : 'costco'}
                aria-label="Pattern"
                className={cx(field, 'mt-2', f.match_type === 'regex' && 'font-mono text-[13px]')}
              />
              <p className="mt-1.5 text-[11px] text-ink-3">
                {FIELDS.find((o) => o.value === f.match_field)!.hint}
                {f.match_type === 'contains' && ' · not case sensitive'}
              </p>
              {f.match_type === 'regex' && (
                <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-warn">
                  <Warning size={12} weight="fill" className="mt-0.5 shrink-0" />
                  A regular expression that will not compile matches nothing at all — it does not
                  raise an error, the rule just quietly stops doing anything.
                </p>
              )}
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-ink-2">At least</span>
                <input inputMode="decimal" value={f.min_amount} placeholder="any"
                       onChange={(e) => set({ min_amount: e.target.value.replace(/[^\d.]/g, '') })}
                       className={small} />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-ink-2">At most</span>
                <input inputMode="decimal" value={f.max_amount} placeholder="any"
                       onChange={(e) => set({ max_amount: e.target.value.replace(/[^\d.]/g, '') })}
                       className={small} />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-ink-2">Account</span>
                <select value={f.account_id} onChange={(e) => set({ account_id: e.target.value })} className={small}>
                  <option value="">Any account</option>
                  {(meta.data?.accounts ?? []).map((a) => (
                    <option key={a.id} value={a.id}>{a.name}{a.mask ? ` ··${a.mask}` : ''}</option>
                  ))}
                </select>
              </label>
            </div>

            {/* ---- what it does ---- */}
            <div>
              <div className="mb-2 text-[12px] font-medium uppercase tracking-wider text-ink-3">Then</div>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12px] text-ink-2">Category</span>
                  <select value={f.set_category} onChange={(e) => set({ set_category: e.target.value })} className={small}>
                    <option value="">Leave it alone</option>
                    {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12px] text-ink-2">Rename to</span>
                  <input value={f.set_name} onChange={(e) => set({ set_name: e.target.value })}
                         placeholder="Victrola Coffee" className={small} />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12px] text-ink-2">Tags</span>
                  <input value={f.add_tags} onChange={(e) => set({ add_tags: e.target.value })}
                         placeholder="work, reimbursable" className={small} />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12px] text-ink-2">Note</span>
                  <input value={f.set_note} onChange={(e) => set({ set_note: e.target.value })}
                         placeholder="Quarterly estimated tax" className={small} />
                </label>
              </div>
              <p className="mt-1.5 text-[11px] text-ink-3">
                A name or note you typed on a transaction yourself always wins over a rule.
              </p>
            </div>

            {/* ---- split ---- */}
            <div>
              <div className="mb-2 flex items-center gap-2">
                <Scissors size={13} className="text-ink-3" />
                <span className="text-[12px] font-medium uppercase tracking-wider text-ink-3">Split it</span>
              </div>
              <div className="inline-flex rounded-full border border-line bg-surface p-0.5">
                {(['none', 'percent', 'amount'] as const).map((m) => (
                  <button key={m} type="button" onClick={() => set({ splitMode: m })}
                          className={cx('h-8 rounded-full px-3.5 text-[13px] font-medium transition-colors',
                            f.splitMode === m ? 'bg-ink text-page' : 'text-ink-2 hover:text-ink')}>
                    {m === 'none' ? "Don't" : m === 'percent' ? 'By percent' : 'By amount'}
                  </button>
                ))}
              </div>

              {f.splitMode !== 'none' && (
                <div className="mt-3 grid gap-2">
                  {f.split.map((p, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <select value={p.category} onChange={(e) => setRow(i, { category: e.target.value })}
                              className={cx(small, 'flex-1')}>
                        <option value="">Pick a category</option>
                        {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                      </select>
                      <input
                        inputMode="decimal"
                        className={cx(small, 'w-24 tnum')}
                        value={f.splitMode === 'percent' ? p.percent : p.amount}
                        placeholder={f.splitMode === 'percent' ? '%' : '$'}
                        onChange={(e) => setRow(i, f.splitMode === 'percent'
                          ? { percent: e.target.value.replace(/[^\d.]/g, '') }
                          : { amount: e.target.value.replace(/[^\d.]/g, '') })}
                      />
                      <button type="button" aria-label="Remove part"
                              onClick={() => set({ split: f.split.filter((_, j) => j !== i) })}
                              className="p-1.5 text-ink-3 hover:text-negative"><Trash size={13} /></button>
                    </div>
                  ))}
                  <div className="flex items-center gap-3">
                    <button type="button"
                            onClick={() => set({ split: [...f.split, { category: '', percent: '', amount: '' }] })}
                            className="inline-flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
                      <Plus size={12} /> Another part
                    </button>
                    {f.splitMode === 'percent' && (
                      <span className={cx('text-[12px] tnum',
                        Math.abs(f.split.reduce((a, p) => a + Number(p.percent || 0), 0) - 100) > 0.01
                          ? 'text-warn' : 'text-ink-3')}>
                        {f.split.reduce((a, p) => a + Number(p.percent || 0), 0)}% of 100
                      </span>
                    )}
                  </div>
                  <p className="flex items-start gap-1.5 text-[11px] text-ink-3">
                    <Info size={12} className="mt-0.5 shrink-0" />
                    Renaming, categorising and tagging apply to your whole history the moment you save.
                    Splitting makes real child transactions, so it runs after a sync — and a split you have
                    since edited by hand is left alone.
                  </p>
                </div>
              )}
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-ink-2">Name this rule</span>
                <input value={f.name} onChange={(e) => set({ name: e.target.value })}
                       placeholder={f.pattern.trim() || 'Costco groceries'} className={small} />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] text-ink-2">Priority</span>
                <input inputMode="numeric" value={f.priority} className={cx(small, 'tnum')}
                       onChange={(e) => set({ priority: e.target.value.replace(/[^\d-]/g, '') })} />
              </label>
            </div>
            <p className="-mt-2 text-[11px] text-ink-3">
              Only one rule applies to a transaction: the highest priority wins, and a tie goes to the
              older rule, so adding one never silently changes what another was doing.
            </p>
          </div>

          {/* ---- live preview ---- */}
          <div className="md:sticky md:top-4 md:self-start">
            <div className="mb-2 text-[12px] font-medium uppercase tracking-wider text-ink-3">What it catches</div>
            <Preview f={f} />
          </div>
        </div>

        {problem && (
          <div className="mx-6 mt-4 rounded-xl bg-warn-soft px-3 py-2 text-[12px] text-warn">{problem}</div>
        )}
        <div className="px-6 pt-3"><ErrorNote error={save.error} /></div>
        <div className="mt-4 flex justify-end gap-2 border-t border-line px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!canSave || save.isPending}>
            {save.isPending ? 'Saving…' : rule ? 'Save rule' : 'Create rule'}
          </Button>
        </div>
      </form>
    </div>
  )
}

/* ---------------------------------------------------------------- list */

function Does({ r }: { r: Rule }) {
  const bits: React.ReactNode[] = []
  if (r.set_category) {
    bits.push(
      <span key="c" className="inline-flex items-center gap-1 rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">
        <CategoryIcon name={r.category_icon ?? 'DotsThree'} size={11} />{r.category_label}
      </span>)
  }
  if (r.set_name) {
    bits.push(<span key="n" className="rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">
      renames to “{r.set_name}”</span>)
  }
  r.add_tags.forEach((t) => bits.push(
    <span key={`t-${t}`} className="inline-flex items-center gap-1 rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">
      <TagIcon size={10} />{t}
    </span>))
  if (r.set_note) {
    bits.push(<span key="note" className="rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">adds a note</span>)
  }
  if (r.split?.length) {
    bits.push(
      <span key="s" className="inline-flex items-center gap-1 rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">
        <Scissors size={10} />splits {r.split.length} ways
      </span>)
  }
  if (!bits.length) {
    return <span className="text-[11px] text-ink-3">does nothing yet</span>
  }
  return <div className="flex flex-wrap gap-1">{bits}</div>
}

function RuleRow({ r, onEdit }: { r: Rule; onEdit: () => void }) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries()
  const toggle = useMutation({
    mutationFn: () => api.editRule(r.id, ruleToBody(r, { enabled: !r.enabled })),
    onSuccess: refresh,
  })
  const del = useMutation({ mutationFn: () => api.deleteRule(r.id), onSuccess: refresh })

  return (
    <li className={cx('px-5 py-3.5', !r.enabled && 'opacity-55')}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-[14px] font-medium text-ink">{r.name}</span>
            {!r.enabled && <span className="shrink-0 text-[11px] text-ink-3">off</span>}
            {r.priority !== 0 && (
              <span className="shrink-0 text-[11px] text-ink-3 tnum">priority {r.priority}</span>
            )}
          </div>
          <div className="mt-0.5 truncate text-[12px] text-ink-3">
            {FIELDS.find((o) => o.value === r.match_field)?.label}{' '}
            {TYPES.find((o) => o.value === r.match_type)?.label}{' '}
            <span className={cx('text-ink-2', r.match_type === 'regex' && 'font-mono')}>{r.pattern}</span>
            {r.min_amount != null && ` · over ${money0(Number(r.min_amount))}`}
            {r.max_amount != null && ` · under ${money0(Number(r.max_amount))}`}
          </div>
          <div className="mt-1.5"><Does r={r} /></div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <span className="mr-1 text-[12px] text-ink-3 tnum">
            {r.matches.toLocaleString()} match{r.matches === 1 ? '' : 'es'}
          </span>
          <button onClick={() => toggle.mutate()} disabled={toggle.isPending}
                  title={r.enabled ? 'Turn this rule off' : 'Turn this rule on'}
                  aria-label={r.enabled ? 'Turn this rule off' : 'Turn this rule on'}
                  className="rounded-full p-1.5 text-ink-3 hover:bg-hover hover:text-ink">
            {r.enabled ? <Prohibit size={14} /> : <Check size={14} />}
          </button>
          <button onClick={onEdit} aria-label="Edit rule"
                  className="rounded-full p-1.5 text-ink-3 hover:bg-hover hover:text-ink">
            <PencilSimple size={14} />
          </button>
          <button onClick={() => del.mutate()} disabled={del.isPending} aria-label="Delete rule"
                  className="rounded-full p-1.5 text-ink-3 hover:bg-hover hover:text-negative">
            <Trash size={14} />
          </button>
        </div>
      </div>
      <ErrorNote error={toggle.error || del.error} />
    </li>
  )
}

export default function RulesPage() {
  const [editing, setEditing] = useState<Rule | null | undefined>(undefined)
  const q = useQuery({ queryKey: ['rules'], queryFn: api.rules2 })
  const d = q.data

  return (
    <>
      <PageHeader
        title="Rules & tags"
        sub="Standing instructions: rename a merchant, fix a category, tag a set of transactions, split a recurring charge."
      >
        <Button variant="primary" onClick={() => setEditing(null)}>
          <Plus size={14} weight="bold" /> New rule
        </Button>
      </PageHeader>

      <ErrorNote error={q.error} />
      {editing !== undefined && <Editor rule={editing} onClose={() => setEditing(undefined)} />}

      {!d ? (
        <Skeleton className="h-64 rounded-[18px]" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
          <Panel>
            <PanelHeader
              title="Rules"
              sub={d.rules.length ? 'Highest priority first. Only one rule applies to any transaction.' : undefined}
            />
            {d.rules.length === 0 ? (
              <Empty title="No rules yet" icon={<Funnel size={20} />}>
                A rule matches transactions and then does something to them, for every one past and
                future. Good first ones: rename the merchant your bank writes as
                <span className="font-mono"> SQ *COFFEE 4412</span>, or tag everything from one client
                as reimbursable.
              </Empty>
            ) : (
              <ul className="mt-2 divide-y divide-line">
                {d.rules.map((r) => (
                  <RuleRow key={r.id} r={r} onEdit={() => setEditing(r)} />
                ))}
              </ul>
            )}
          </Panel>

          <Panel className="h-fit">
            <PanelHeader title="Tags" sub="From rules and from transactions you tagged by hand." />
            {d.tags.length === 0 ? (
              <div className="px-5 pb-5 pt-2 text-[13px] text-ink-3">
                Nothing tagged yet. Tags cut across categories — useful for “reimbursable”, “tax
                deductible”, or one holiday.
              </div>
            ) : (
              <ul className="mt-2 divide-y divide-line border-t border-line">
                {d.tags.map((t) => (
                  <li key={t.tag} className="flex items-center gap-2 px-5 py-2">
                    <TagIcon size={13} className="shrink-0 text-ink-3" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{t.tag}</span>
                    <span className="shrink-0 text-[11px] text-ink-3 tnum">{t.count}</span>
                    <Money value={Number(t.total)} className="w-20 shrink-0 text-right text-[13px] text-ink-2" />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </>
  )
}
