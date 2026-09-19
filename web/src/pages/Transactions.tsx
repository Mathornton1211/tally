import { ListBullets, Plus } from '@phosphor-icons/react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Txn } from '../api'
import { FilterBar } from '../components/Filters'
import { AddManualTransaction } from '../components/Manual'
import { GroupedTxns, TxnDrawer } from '../components/Transactions'
import { Button, Empty, ErrorNote, Money, PageHeader, Panel, Skeleton } from '../components/ui'
import { useFilters } from '../lib/range'

const PAGE = 100

export default function Transactions() {
  const f = useFilters('90d')
  const query = f.query()
  const [open, setOpen] = useState<Txn | null>(null)
  const [adding, setAdding] = useState(false)

  const q = useInfiniteQuery({
    queryKey: ['transactions', query],
    queryFn: ({ pageParam }) => api.transactions({ ...query, limit: String(PAGE), offset: String(pageParam) }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((n, p) => n + p.rows.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const first = q.data?.pages[0]
  const rows = q.data?.pages.flatMap((p) => p.rows) ?? []

  return (
    <>
      <PageHeader title="Transactions">
        <Button onClick={() => setAdding(true)}><Plus size={14} weight="bold" /> Add by hand</Button>
      </PageHeader>
      {adding && <AddManualTransaction onClose={() => setAdding(false)} />}
      <FilterBar f={f} search kinds />

      {first && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          <div className="panel px-4 py-3">
            <div className="text-[12px] text-ink-3">Transactions</div>
            <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink tnum">{first.total.toLocaleString()}</div>
          </div>
          <div className="panel px-4 py-3">
            <div className="text-[12px] text-ink-3">Spent</div>
            <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-ink"><Money value={Number(first.spending)} size="lg" /></div>
          </div>
          <div className="panel px-4 py-3">
            <div className="text-[12px] text-ink-3">Income</div>
            <div className="mt-0.5 text-[20px] font-semibold tracking-tight text-positive"><Money value={Number(first.income)} size="lg" /></div>
          </div>
        </div>
      )}

      <ErrorNote error={q.error} />
      <Panel className="overflow-hidden">
        {q.isLoading ? (
          <div className="space-y-3 p-5">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-11" />)}</div>
        ) : rows.length === 0 ? (
          <Empty title="No transactions match" icon={<ListBullets size={18} />}>Try a wider date range or clear a filter.</Empty>
        ) : (
          <GroupedTxns rows={rows} onOpen={setOpen} />
        )}
      </Panel>
      {q.hasNextPage && (
        <div className="mt-4 flex justify-center">
          <Button onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
            {q.isFetchingNextPage ? 'Loading…' : `Load more · ${(first!.total - rows.length).toLocaleString()} left`}
          </Button>
        </div>
      )}
      <TxnDrawer txn={open} onClose={() => setOpen(null)} />
    </>
  )
}
