import {
  ArrowRight, Check, CheckCircle, Clock, Sparkle,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type SetupState, type SetupStep } from '../api'
import { Button, cx, ErrorNote, Money, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { fmtShort, money, money0 } from '../lib/format'

/**
 * A link that looks like a button. `Button` renders a real <button>, and an
 * <a> inside one is invalid markup that breaks keyboard navigation — so
 * anything that navigates is a Link wearing the button's clothes.
 */
function LinkButton({ to, children, primary }: { to: string; children: ReactNode; primary?: boolean }) {
  return (
    <Link
      to={to}
      className={cx(
        'inline-flex h-9 items-center justify-center gap-1.5 rounded-full px-4 text-[13px] font-medium',
        'transition-[background,transform,color] duration-200 active:scale-[0.98]',
        primary
          ? 'bg-accent text-accent-ink hover:brightness-110'
          : 'border border-line-strong bg-surface text-ink hover:bg-hover',
      )}
    >
      {children}
    </Link>
  )
}

/**
 * What Tally can already see, in one paragraph.
 *
 * A progress bar with nothing behind it is a worse version of an empty page,
 * so this goes first: real transactions, real totals, from the data that is
 * already there. If there is nothing yet it says that plainly rather than
 * rendering a row of zeroes.
 */
function AlreadyKnows({ s }: { s: SetupState['summary'] }) {
  if (!s.transactions) {
    return (
      <Panel className="mb-4">
        <div className="px-5 py-4 text-[14px] text-ink-2">
          Nothing to read yet. Once a bank is connected, Tally pulls up to two years of history and
          this fills in by itself.
        </div>
      </Panel>
    )
  }
  const spent = Number(s.spent)
  const earned = Number(s.earned)
  const fees = Number(s.fees.amount)
  return (
    <Panel className="mb-4">
      <PanelHeader title="What Tally can already see" sub={`Since ${fmtShort(s.since)}`} />
      <div className="px-5 pb-5 pt-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[
            { label: 'Transactions', value: s.transactions.toLocaleString() },
            { label: 'Spent', value: <Money value={spent} size="lg" /> },
            { label: 'Came in', value: <Money value={earned} size="lg" /> },
          ].map((t) => (
            <div key={t.label}>
              <div className="text-[12px] text-ink-3">{t.label}</div>
              <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink">{t.value}</div>
            </div>
          ))}
        </div>

        {s.top_categories.length > 0 && (
          <p className="mt-4 max-w-[62ch] text-[13px] text-ink-2">
            Most of it went on{' '}
            {s.top_categories.map((c, i) => (
              <span key={c.label}>
                {i > 0 && (i === s.top_categories.length - 1 ? ' and ' : ', ')}
                <span className="text-ink">{c.label.toLowerCase()}</span>{' '}
                <span className="tnum text-ink-3">{money0(Number(c.amount))}</span>
              </span>
            ))}
            .
          </p>
        )}

        {s.fees.count > 0 && (
          <p className="mt-2 max-w-[62ch] text-[13px] text-warn">
            {s.fees.count} {s.fees.count === 1 ? 'fee' : 'fees'} in there, {money(fees)} of them.{' '}
            <Link to="/fees" className="underline">See which ones are worth a phone call.</Link>
          </p>
        )}
      </div>
    </Panel>
  )
}

/** The budgets Tally would set, and the one button that sets them. */
function BudgetOffer({ step }: { step: SetupStep }) {
  const qc = useQueryClient()
  const apply = useMutation({
    mutationFn: api.applySetupBudgets,
    // Budgets move most pages, not just this one.
    onSuccess: () => qc.invalidateQueries(),
  })
  const s = step.suggestion
  if (!s?.categories) return null

  return (
    <div className="mt-3 rounded-xl bg-surface-2 p-3">
      <div className="text-[13px] text-ink">
        From the last three months: <b>{s.categories}</b>{' '}
        {s.categories === 1 ? 'category' : 'categories'}, {money0(Number(s.total))} a month.
      </div>
      {s.top && s.top.length > 0 && (
        <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-surface">
          {s.top.map((t) => (
            <li key={t.label} className="flex items-center justify-between gap-3 px-3 py-1.5 text-[13px]">
              <span className="truncate text-ink">{t.label}</span>
              <Money value={Number(t.amount)} className="text-ink-2" />
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => apply.mutate()} disabled={apply.isPending}>
          <Check size={14} weight="bold" /> {apply.isPending ? 'Setting…' : 'Use these'}
        </Button>
        <Link to={step.action}
              className="text-[13px] text-ink-2 underline decoration-line-strong hover:text-ink">
          Pick them myself
        </Link>
      </div>
      <ErrorNote error={apply.error} />
    </div>
  )
}

/** The goals Tally would add, with the reasoning it gave for each. */
function GoalOffer({ step }: { step: SetupStep }) {
  const qc = useQueryClient()
  const apply = useMutation({
    mutationFn: api.applySetupGoals,
    onSuccess: () => qc.invalidateQueries(),
  })
  const ideas = step.suggestion?.ideas
  if (!ideas?.length) return null

  return (
    <div className="mt-3 rounded-xl bg-surface-2 p-3">
      <ul className="grid gap-2">
        {ideas.map((g) => (
          <li key={g.name} className="rounded-lg border border-line bg-surface px-3 py-2">
            <div className="text-[13px] font-medium text-ink">{g.name}</div>
            <div className="mt-0.5 max-w-[58ch] text-[12px] text-ink-3">{g.why}</div>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => apply.mutate()} disabled={apply.isPending}>
          <Check size={14} weight="bold" /> {apply.isPending ? 'Adding…' : 'Add these'}
        </Button>
        <Link to={step.action}
              className="text-[13px] text-ink-2 underline decoration-line-strong hover:text-ink">
          Set my own
        </Link>
      </div>
      <ErrorNote error={apply.error} />
    </div>
  )
}

/** A step that is finished: one quiet line, out of the way. */
function DoneRow({ step }: { step: SetupStep }) {
  return (
    <li className="flex items-center gap-3 px-5 py-2.5">
      <CheckCircle size={17} weight="fill" className="shrink-0 text-positive" />
      <span className="min-w-0 flex-1 truncate text-[14px] text-ink-2">{step.title}</span>
      <span className="shrink-0 truncate text-[12px] text-ink-3">{step.detail}</span>
    </li>
  )
}

function TodoRow({ step, lead }: { step: SetupStep; lead: boolean }) {
  // `ready` is only present on steps that can be waiting on data. Undefined
  // means it is always available.
  const waiting = step.ready === false
  return (
    <li className={cx('px-5 py-4', lead && 'bg-surface-2')}>
      <div className="flex items-start gap-3">
        <span className={cx('mt-0.5 flex h-[17px] w-[17px] shrink-0 items-center justify-center rounded-full border',
          waiting ? 'border-line-strong text-ink-3' : lead ? 'border-accent' : 'border-line-strong')}>
          {waiting && <Clock size={11} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className={cx('text-[14px]', lead ? 'font-semibold text-ink' : 'font-medium text-ink')}>
            {step.title}
            {step.optional && <span className="ml-2 text-[12px] font-normal text-ink-3">optional</span>}
          </div>
          <p className="mt-0.5 max-w-[64ch] text-[13px] text-ink-2">{step.why}</p>
          <p className="mt-1 text-[12px] text-ink-3">{step.detail}</p>

          {step.key === 'budget' && !waiting && <BudgetOffer step={step} />}
          {step.key === 'goal' && !waiting && <GoalOffer step={step} />}

          {!waiting && !step.suggestion && (
            <div className="mt-3">
              <LinkButton to={step.action} primary={lead}>
                {step.action_label} <ArrowRight size={13} weight="bold" />
              </LinkButton>
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

export default function Welcome() {
  const q = useQuery({ queryKey: ['setup'], queryFn: api.setupState })
  const d = q.data

  if (!d) {
    return (
      <>
        <PageHeader title="Setting up" />
        <ErrorNote error={q.error} />
        <div className="grid gap-4">
          <Skeleton className="h-32 rounded-[18px]" />
          <Skeleton className="h-72 rounded-[18px]" />
        </div>
      </>
    )
  }

  const required = d.steps.filter((s) => !s.optional)
  const optional = d.steps.filter((s) => s.optional)
  // The first unfinished required step is the one worth making loud. Everything
  // after it is still listed, just not shouted.
  const leadKey = required.find((s) => !s.done && s.ready !== false)?.key

  return (
    <>
      <PageHeader
        title={d.complete ? 'Tally is set up' : 'Setting up'}
        sub={d.complete
          ? 'Nothing left on the list.'
          : `${d.done} of ${d.total} done. Each of these is here because skipping it leaves a page empty.`}
      >
        {d.complete && (
          <LinkButton to="/" primary>
            Go to the dashboard <ArrowRight size={13} weight="bold" />
          </LinkButton>
        )}
      </PageHeader>

      <ErrorNote error={q.error} />

      {!d.complete && (
        <div className="mb-4 flex h-1.5 overflow-hidden rounded-full bg-hover" aria-hidden>
          <div className="h-full bg-accent transition-[width] duration-500"
               style={{ width: `${(d.done / Math.max(d.total, 1)) * 100}%` }} />
        </div>
      )}

      <AlreadyKnows s={d.summary} />

      <Panel>
        <PanelHeader
          title="The list"
          sub={d.history_days > 0 ? `${d.history_days} days of history so far` : undefined}
        />
        <ul className="mt-2 divide-y divide-line">
          {required.map((s) => (
            s.done
              ? <DoneRow key={s.key} step={s} />
              : <TodoRow key={s.key} step={s} lead={s.key === leadKey} />
          ))}
        </ul>
      </Panel>

      {optional.length > 0 && (
        <Panel className="mt-4">
          <PanelHeader title="Worth knowing about" sub="None of these are needed to use Tally." />
          <ul className="mt-2 divide-y divide-line">
            {optional.map((s) => (
              s.done ? <DoneRow key={s.key} step={s} /> : <TodoRow key={s.key} step={s} lead={false} />
            ))}
          </ul>
        </Panel>
      )}

      {d.complete && (
        <p className="mt-4 flex items-center gap-2 px-1 text-[13px] text-ink-3">
          <Sparkle size={14} /> Tally syncs on its own from here. It will tell you when something needs you.
        </p>
      )}
    </>
  )
}
