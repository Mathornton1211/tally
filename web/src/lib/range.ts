import { useSearchParams } from 'react-router-dom'
import { iso } from './format'

export type RangeKey = 'mtd' | 'last_month' | '30d' | '90d' | 'ytd' | '6m' | '12m' | 'custom'

export const PRESETS: { key: Exclude<RangeKey, 'custom'>; label: string }[] = [
  { key: 'mtd', label: 'This month' },
  { key: 'last_month', label: 'Last month' },
  { key: '30d', label: 'Last 30 days' },
  { key: '90d', label: 'Last 90 days' },
  { key: '6m', label: 'Last 6 months' },
  { key: 'ytd', label: 'Year to date' },
  { key: '12m', label: 'Last 12 months' },
]

export function presetDates(key: Exclude<RangeKey, 'custom'>, now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const back = (days: number) => new Date(today.getTime() - days * 86400000)
  switch (key) {
    case 'mtd': return { start: new Date(today.getFullYear(), today.getMonth(), 1), end: today }
    case 'last_month': return {
      start: new Date(today.getFullYear(), today.getMonth() - 1, 1),
      end: new Date(today.getFullYear(), today.getMonth(), 0),
    }
    case '30d': return { start: back(29), end: today }
    case '90d': return { start: back(89), end: today }
    case '6m': return { start: new Date(today.getFullYear(), today.getMonth() - 5, 1), end: today }
    case 'ytd': return { start: new Date(today.getFullYear(), 0, 1), end: today }
    case '12m': return { start: new Date(today.getFullYear(), today.getMonth() - 11, 1), end: today }
  }
}

/**
 * Date range + filters, all in the URL so any view is bookmarkable and the back
 * button works. `range=90d` stays relative; custom ranges store start/end.
 */
export function useFilters(defaultRange: Exclude<RangeKey, 'custom'> = 'mtd') {
  const [params, setParams] = useSearchParams()
  const rangeParam = (params.get('range') as RangeKey | null) ?? (params.get('start') ? 'custom' : defaultRange)

  let start: string, end: string, label: string
  if (rangeParam === 'custom') {
    start = params.get('start') || iso(presetDates(defaultRange).start)
    end = params.get('end') || iso(new Date())
    label = 'Custom'
  } else {
    const p = presetDates(rangeParam)
    start = iso(p.start)
    end = iso(p.end)
    label = PRESETS.find((x) => x.key === rangeParam)?.label ?? ''
  }

  const update = (fn: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(params)
    fn(next)
    next.delete('page')
    setParams(next, { replace: true })
  }

  return {
    range: rangeParam, start, end, label,
    accounts: params.getAll('account'),
    categories: params.getAll('category'),
    kind: params.get('kind') || '',
    q: params.get('q') || '',
    setPreset: (key: Exclude<RangeKey, 'custom'>) => update((n) => { n.set('range', key); n.delete('start'); n.delete('end') }),
    setCustom: (s: string, e: string) => update((n) => { n.set('range', 'custom'); n.set('start', s); n.set('end', e) }),
    setList: (name: 'account' | 'category', values: string[]) => update((n) => { n.delete(name); values.forEach((v) => n.append(name, v)) }),
    setValue: (name: string, value: string) => update((n) => { if (value) n.set(name, value); else n.delete(name) }),
    clear: () => update((n) => { ['account', 'category', 'kind', 'q', 'min_amount', 'max_amount'].forEach((k) => n.delete(k)) }),
    query: () => ({
      start, end,
      account: params.getAll('account'),
      category: params.getAll('category'),
      kind: params.get('kind') || undefined,
      q: params.get('q') || undefined,
    }),
  }
}

export type Filters = ReturnType<typeof useFilters>
