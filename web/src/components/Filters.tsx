import { CalendarBlank, CaretDown, Check, MagnifyingGlass, X } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmtShort } from '../lib/format'
import { PRESETS, type Filters } from '../lib/range'
import { CategoryIcon } from './icons'
import { cx, usePopover } from './ui'

const trigger =
  'inline-flex h-9 items-center gap-2 rounded-full border border-line-strong bg-surface px-3.5 text-[13px] font-medium text-ink hover:bg-hover'

export function DateRangePicker({ f }: { f: Filters }) {
  const { open, setOpen, ref } = usePopover()
  const [s, setS] = useState(f.start)
  const [e, setE] = useState(f.end)
  useEffect(() => { setS(f.start); setE(f.end) }, [f.start, f.end])

  return (
    <div className="relative" ref={ref}>
      <button className={trigger} onClick={() => setOpen(!open)} aria-expanded={open}>
        <CalendarBlank size={15} />
        {f.range === 'custom' ? `${fmtShort(f.start)} – ${fmtShort(f.end)}` : f.label}
        <CaretDown size={12} className="text-ink-3" />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-64 overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_16px_40px_-12px_rgba(0,0,0,0.25)]">
          <div className="p-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                onClick={() => { f.setPreset(p.key); setOpen(false) }}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[13px] text-ink hover:bg-hover"
              >
                {p.label}
                {f.range === p.key && <Check size={15} weight="bold" className="text-accent" />}
              </button>
            ))}
          </div>
          <div className="border-t border-line p-3">
            <div className="mb-2 text-[12px] font-medium text-ink-3">Custom range</div>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1 text-[11px] text-ink-3">
                From
                <input type="date" value={s} max={e} onChange={(ev) => setS(ev.target.value)}
                       className="h-8 rounded-lg border border-line-strong bg-surface-2 px-2 text-[12px] text-ink" />
              </label>
              <label className="flex flex-col gap-1 text-[11px] text-ink-3">
                To
                <input type="date" value={e} min={s} onChange={(ev) => setE(ev.target.value)}
                       className="h-8 rounded-lg border border-line-strong bg-surface-2 px-2 text-[12px] text-ink" />
              </label>
            </div>
            <button
              onClick={() => { if (s && e) { f.setCustom(s, e); setOpen(false) } }}
              className="mt-2.5 h-8 w-full rounded-full bg-ink text-[12px] font-medium text-page"
            >
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

type Option = { value: string; label: string; hint?: string | null; icon?: string }

function MultiSelect({ label, options, selected, onChange, searchable }: {
  label: string; options: Option[]; selected: string[]; onChange: (v: string[]) => void; searchable?: boolean
}) {
  const { open, setOpen, ref } = usePopover()
  const [q, setQ] = useState('')
  const shown = options.filter((o) => !q || o.label.toLowerCase().includes(q.toLowerCase()))
  const toggle = (v: string) => onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v])
  const summary = selected.length === 0 ? label
    : selected.length === 1 ? options.find((o) => o.value === selected[0])?.label ?? label
    : `${label} · ${selected.length}`

  return (
    <div className="relative" ref={ref}>
      <button className={cx(trigger, selected.length > 0 && 'border-ink bg-ink text-page hover:bg-ink')} onClick={() => setOpen(!open)} aria-expanded={open}>
        {summary}
        <CaretDown size={12} className={selected.length ? 'text-page/70' : 'text-ink-3'} />
      </button>
      {open && (
        <div className="absolute left-0 z-30 mt-2 w-72 overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_16px_40px_-12px_rgba(0,0,0,0.25)]">
          {searchable && (
            <div className="border-b border-line p-2">
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Find ${label.toLowerCase()}`}
                     className="h-8 w-full rounded-lg bg-surface-2 px-2.5 text-[13px] text-ink outline-none placeholder:text-ink-3" />
            </div>
          )}
          <div className="max-h-80 overflow-y-auto p-1.5">
            {shown.map((o) => (
              <button key={o.value} onClick={() => toggle(o.value)}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-ink hover:bg-hover">
                <span className={cx('flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                  selected.includes(o.value) ? 'border-accent bg-accent text-accent-ink' : 'border-line-strong')}>
                  {selected.includes(o.value) && <Check size={11} weight="bold" />}
                </span>
                {o.icon && <CategoryIcon name={o.icon} size={15} className="text-ink-2" />}
                <span className="flex-1 truncate">{o.label}</span>
                {o.hint && <span className="text-[12px] text-ink-3">{o.hint}</span>}
              </button>
            ))}
          </div>
          {selected.length > 0 && (
            <div className="border-t border-line p-1.5">
              <button onClick={() => onChange([])} className="w-full rounded-lg px-2.5 py-2 text-left text-[13px] text-ink-2 hover:bg-hover">
                Clear selection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function FilterBar({ f, search, kinds, categories = true }: { f: Filters; search?: boolean; kinds?: boolean; categories?: boolean }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const [q, setQ] = useState(f.q)
  useEffect(() => setQ(f.q), [f.q])
  useEffect(() => {
    const t = setTimeout(() => { if (q !== f.q) f.setValue('q', q) }, 250)
    return () => clearTimeout(t)
  }, [q]) // eslint-disable-line react-hooks/exhaustive-deps

  const active = f.accounts.length + f.categories.length + (f.kind ? 1 : 0) + (f.q ? 1 : 0)

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2">
      {search && (
        <div className="relative w-full sm:w-64">
          <MagnifyingGlass size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search merchants"
                 className="h-9 w-full rounded-full border border-line-strong bg-surface pl-9 pr-3 text-[13px] text-ink outline-none placeholder:text-ink-3 focus:border-ink-3" />
        </div>
      )}
      <DateRangePicker f={f} />
      <MultiSelect
        label="Accounts"
        selected={f.accounts}
        onChange={(v) => f.setList('account', v)}
        options={(meta.data?.accounts ?? []).map((a) => ({ value: a.id, label: a.name, hint: a.mask ? `··${a.mask}` : a.institution }))}
      />
      {categories && (
        <MultiSelect
          label="Categories"
          searchable
          selected={f.categories}
          onChange={(v) => f.setList('category', v)}
          options={(meta.data?.categories ?? []).map((c) => ({ value: c.key, label: c.label, icon: c.icon }))}
        />
      )}
      {kinds && (
        <div className="inline-flex rounded-full border border-line-strong bg-surface p-0.5">
          {[['', 'All'], ['expense', 'Spending'], ['income', 'Income'], ['transfer', 'Transfers']].map(([v, l]) => (
            <button key={v} onClick={() => f.setValue('kind', v)}
                    className={cx('h-8 rounded-full px-3 text-[13px] font-medium', f.kind === v ? 'bg-ink text-page' : 'text-ink-2 hover:text-ink')}>
              {l}
            </button>
          ))}
        </div>
      )}
      {active > 0 && (
        <button onClick={f.clear} className="inline-flex h-9 items-center gap-1 rounded-full px-3 text-[13px] text-ink-2 hover:bg-hover hover:text-ink">
          <X size={13} /> Clear filters
        </button>
      )}
    </div>
  )
}
