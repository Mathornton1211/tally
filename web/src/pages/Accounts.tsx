import { ArrowsClockwise, Bank, CaretRight, LockKey, Plus } from '@phosphor-icons/react'
import { useState } from 'react'
import { AccountDetails } from '../components/AccountDetails'
import { AiStatusPanel, NotifyPanel } from '../components/AiBits'
import { ManualAccountsPanel } from '../components/Manual'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Item } from '../api'
import { Button, cx, Empty, ErrorNote, Money, PageHeader, Panel, Skeleton } from '../components/ui'
import { ago } from '../lib/format'
import { usePlaid } from '../usePlaid'

const STATUS: Record<Item['status'], { label: string; tone: string }> = {
  ok: { label: 'Connected', tone: 'bg-accent-soft text-positive' },
  login_required: { label: 'Needs re-login', tone: 'bg-warn-soft text-warn' },
  error: { label: 'Sync error', tone: 'bg-bad-soft text-negative' },
  disconnected: { label: 'Disconnected', tone: 'bg-hover text-ink-2' },
}

export default function Accounts() {
  const qc = useQueryClient()
  const items = useQuery({ queryKey: ['items'], queryFn: api.items, refetchInterval: 15000 })
  // Every account, hidden ones included, so a hidden account can be un-hidden here.
  const all = useQuery({ queryKey: ['all-accounts'], queryFn: api.allAccounts })
  const plaid = usePlaid()
  const syncOne = useMutation({ mutationFn: api.syncItem, onSettled: () => qc.invalidateQueries() })
  const [editing, setEditing] = useState<string | null>(null)

  return (
    <>
      <PageHeader title="Accounts" sub="Every bank Tally reads from. Click an account to add rates and fees Plaid can't see.">
        <Button variant="primary" onClick={() => plaid.start()} disabled={plaid.busy}>
          <Plus size={15} weight="bold" /> {plaid.busy ? 'Opening Plaid…' : 'Add account'}
        </Button>
      </PageHeader>
      {plaid.error && <div className="mb-4"><ErrorNote error={new Error(plaid.error)} /></div>}
      {syncOne.error && <div className="mb-4"><ErrorNote error={syncOne.error} /></div>}

      {items.isLoading ? <Skeleton className="h-64 rounded-[18px]" /> : items.data?.length === 0 ? (
        <Panel><Empty title="No banks connected" icon={<Bank size={18} />}>Add your first account. You log in through Plaid; Tally never sees your bank password and can only read.</Empty></Panel>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {items.data?.map((it, i) => {
            const accts = all.data?.filter((a) => a.item_id === it.id) ?? []
            const st = STATUS[it.status]
            return (
              <Panel key={it.id} className="flex flex-col" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="flex items-start justify-between gap-3 px-5 pt-5">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full text-white" style={{ background: it.primary_color || 'var(--ink-2)' }}>
                      <Bank size={19} weight="fill" />
                    </div>
                    <div>
                      <div className="text-[15px] font-semibold text-ink">{it.institution || 'Unknown bank'}</div>
                      <div className="text-[12px] text-ink-3">Synced {ago(it.last_synced_at)}{it.update_status && it.update_status !== 'HISTORICAL_UPDATE_COMPLETE' && ' · history still loading'}</div>
                    </div>
                  </div>
                  <span className={cx('rounded-full px-2 py-0.5 text-[12px] font-medium', st.tone)}>{st.label}</span>
                </div>
                <ul className="mt-3 divide-y divide-line">
                  {accts.map((a) => (
                    <li key={a.id}>
                      <button onClick={() => setEditing(a.id)} className="group flex w-full items-center justify-between gap-3 px-5 py-2.5 text-left hover:bg-hover">
                        <span className={cx('text-[14px] text-ink', a.hidden && 'opacity-50')}>{a.name}{a.mask && <span className="text-ink-3"> ··{a.mask}</span>}{a.hidden && <span className="ml-2 rounded-full bg-hover px-1.5 py-0.5 text-[11px] text-ink-2">Hidden</span>}</span>
                        <span className="flex items-center gap-2">
                          <Money value={Number(a.current_balance || 0)} className="text-[14px] font-medium text-ink" />
                          <CaretRight size={12} className="text-ink-3 transition-transform group-hover:translate-x-0.5" />
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                {it.status !== 'ok' && it.error_message && <div className="mx-5 mt-2 rounded-lg bg-bad-soft px-3 py-2 text-[12px] text-negative">{it.error_message}</div>}
                <div className="mt-auto flex items-center justify-end gap-2 border-t border-line px-4 py-2.5">
                  {it.status === 'login_required' ? (
                    <Button onClick={() => plaid.start(it.id)}><LockKey size={14} /> Re-login</Button>
                  ) : (
                    <Button variant="ghost" onClick={() => syncOne.mutate(it.id)} disabled={syncOne.isPending}>
                      <ArrowsClockwise size={14} className={syncOne.isPending && syncOne.variables === it.id ? 'animate-spin' : ''} /> Sync now
                    </Button>
                  )}
                </div>
              </Panel>
            )
          })}
        </div>
      )}
      <ManualAccountsPanel />
      <NotifyPanel />
      <AiStatusPanel />
      <AccountDetails accountId={editing} onClose={() => setEditing(null)} />
      <p className="mt-6 flex items-center gap-1.5 text-[12px] text-ink-3">
        <LockKey size={13} /> Read-only access through Plaid. Tally cannot move money.
      </p>
    </>
  )
}
