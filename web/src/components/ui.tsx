import { ArrowDownRight, ArrowUpRight, CaretRight } from '@phosphor-icons/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { CategoryIcon } from './icons'
import { moneyParts } from '../lib/format'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

export function Panel({ children, className, style }: { children: ReactNode; className?: string; style?: React.CSSProperties }) {
  return <section className={cx('panel rise', className)} style={style}>{children}</section>
}

export function PanelHeader({ title, action, to, sub }: { title: string; action?: ReactNode; to?: string; sub?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 px-5 pt-5">
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
        {sub && <div className="mt-0.5 text-[13px] text-ink-3">{sub}</div>}
      </div>
      {action}
      {to && !action && (
        <Link to={to} className="flex items-center gap-0.5 text-[13px] font-medium text-ink-2 hover:text-ink">
          See all <CaretRight size={12} weight="bold" />
        </Link>
      )}
    </div>
  )
}

/** Dollars loud, cents quiet. The way people actually read balances. */
export function Money({ value, className, showPlus, colorIncome, size }: {
  value: number; className?: string; showPlus?: boolean; colorIncome?: boolean; size?: 'hero' | 'lg'
}) {
  const p = moneyParts(value)
  const sign = p.sign || (showPlus && value > 0 ? '+' : '')
  return (
    <span className={cx('tnum whitespace-nowrap', colorIncome && value > 0 && 'text-positive', className)}>
      {sign}{p.whole}
      <span className={cx(size === 'hero' ? 'text-[0.55em] align-[0.62em] ml-0.5' : size === 'lg' ? 'text-[0.7em]' : '', 'opacity-60')}>
        .{p.cents}
      </span>
    </span>
  )
}

export function Delta({ value, previous, invert, label }: { value: number; previous: number | null | undefined; invert?: boolean; label?: string }) {
  if (previous == null || previous === 0) return null
  const diff = value - previous
  const up = diff > 0
  // For spending, up is bad. For net worth, up is good.
  const good = invert ? !up : up
  const pctv = Math.abs(diff / previous)
  if (pctv < 0.005) return <span className="text-[13px] text-ink-3">Same as {label ?? 'before'}</span>
  const Arrow = up ? ArrowUpRight : ArrowDownRight
  return (
    <span className={cx('inline-flex items-center gap-0.5 text-[13px] font-medium', good ? 'text-positive' : 'text-negative')}>
      <Arrow size={13} weight="bold" />
      {(pctv * 100).toFixed(pctv < 0.1 ? 1 : 0)}%
      {label && <span className="ml-1 font-normal text-ink-3">vs {label}</span>}
    </span>
  )
}

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cx('skeleton', className)} style={style} />
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-hover text-ink-2">{icon}</div>}
      <div className="text-[15px] font-medium text-ink">{title}</div>
      {children && <div className="max-w-[46ch] text-[13px] text-ink-3">{children}</div>}
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <div className="rounded-xl border border-line bg-bad-soft px-4 py-3 text-[13px] text-negative">
      {(error as Error).message || 'Something went wrong'}
    </div>
  )
}

export function Button({ children, onClick, variant = 'default', disabled, className, type = 'button', title }: {
  children: ReactNode; onClick?: () => void; variant?: 'default' | 'primary' | 'ghost'; disabled?: boolean
  className?: string; type?: 'button' | 'submit'; title?: string
}) {
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        'inline-flex h-9 items-center justify-center gap-1.5 rounded-full px-4 text-[13px] font-medium transition-[background,transform,color] duration-200 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50',
        variant === 'primary' && 'bg-accent text-accent-ink hover:brightness-110',
        variant === 'default' && 'border border-line-strong bg-surface text-ink hover:bg-hover',
        variant === 'ghost' && 'text-ink-2 hover:bg-hover hover:text-ink',
        className,
      )}
    >
      {children}
    </button>
  )
}

export function MerchantAvatar({ logo, icon, name, size = 36 }: { logo?: string | null; icon: string; name: string; size?: number }) {
  const [failed, setFailed] = useState(false)
  if (logo && !failed) {
    return (
      <img
        src={logo}
        alt=""
        title={name}
        width={size}
        height={size}
        loading="lazy"
        onError={() => setFailed(true)}
        className="shrink-0 rounded-full border border-line bg-white object-cover"
        style={{ width: size, height: size }}
      />
    )
  }
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full bg-hover text-ink-2"
      style={{ width: size, height: size }}
      title={name}
    >
      <CategoryIcon name={icon} size={Math.round(size * 0.48)} />
    </div>
  )
}

export function usePopover() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return { open, setOpen, ref }
}

export function PageHeader({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-ink">{title}</h1>
        {sub && <div className="mt-1 text-[14px] text-ink-3">{sub}</div>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-full border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            'h-8 rounded-full px-3.5 text-[13px] font-medium transition-colors',
            o.value === value ? 'bg-ink text-page' : 'text-ink-2 hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
