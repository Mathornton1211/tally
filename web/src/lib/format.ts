const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export const money = (v: number | null | undefined) => (v == null ? '—' : usd.format(v))
export const money0 = (v: number | null | undefined) => (v == null ? '—' : usd0.format(v))

export function moneyCompact(v: number) {
  const a = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (a >= 1_000) return `${sign}$${(a / 1_000).toFixed(a >= 10_000 ? 0 : 1).replace(/\.0$/, '')}k`
  return `${sign}$${Math.round(a)}`
}

/** Split into dollars and cents so cents can be set quieter. */
export function moneyParts(v: number) {
  const s = usd.format(Math.abs(v))
  const [whole, cents] = s.split('.')
  return { sign: v < 0 ? '-' : '', whole, cents: cents ?? '00' }
}

export function pct(v: number | null | undefined, digits = 0) {
  if (v == null || !isFinite(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export const parseDate = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export const fmtDay = (s: string) =>
  parseDate(s).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })

export const fmtShort = (s: string) => parseDate(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

export const fmtMonth = (s: string, long = false) =>
  parseDate(s).toLocaleDateString('en-US', { month: long ? 'long' : 'short', year: long ? 'numeric' : undefined })

export function relativeDays(s: string) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((parseDate(s).getTime() - today.getTime()) / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days === -1) return 'Yesterday'
  if (days < 0) return `${-days} days ago`
  if (days < 7) return `In ${days} days`
  return fmtShort(s)
}

export function ago(isoTs: string | null) {
  if (!isoTs) return 'never'
  const mins = Math.round((Date.now() - new Date(isoTs).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`
  return `${Math.round(mins / 1440)}d ago`
}

export const cadenceLabel: Record<string, string> = {
  weekly: 'Weekly', biweekly: 'Every 2 weeks', monthly: 'Monthly', quarterly: 'Quarterly', yearly: 'Yearly',
}

export const accountTypeLabel: Record<string, string> = {
  depository: 'Cash', credit: 'Credit cards', loan: 'Loans', investment: 'Investments', other: 'Other',
}
