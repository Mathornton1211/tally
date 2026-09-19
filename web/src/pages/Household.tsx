import {
  Check, Copy, Eye, Link as LinkIcon, LockKey, Plus, ShieldWarning, Trash, UsersThree, Warning, X,
} from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Account, type Person, type ShareLink } from '../api'
import { Button, cx, Empty, ErrorNote, PageHeader, Panel, PanelHeader, Skeleton } from '../components/ui'
import { accountTypeLabel, ago, fmtShort, iso } from '../lib/format'

/**
 * The accounts endpoint carries ownership now. `Account` in api.ts predates
 * that, so widen it here rather than editing a file three other pages share.
 */
type OwnedAccount = Account & { hidden: boolean; owner_id: number | null; owner_name: string | null }

const field = 'h-10 w-full rounded-xl border border-line-strong bg-surface-2 px-3 text-[14px] text-ink outline-none focus:border-ink-3'
const small = 'h-9 rounded-lg border border-line-strong bg-surface-2 px-2 text-[13px] text-ink outline-none focus:border-ink-3'

const ROLES = [
  { value: 'owner', label: 'Owner', blurb: 'Adds and removes people, connects banks, changes settings.' },
  { value: 'member', label: 'Member', blurb: 'Uses everything day to day.' },
  { value: 'viewer', label: 'Viewer', blurb: 'Can look, but cannot change anything.' },
] as const

function Dot({ color, name, size = 28 }: { color: string; name: string; size?: number }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full font-semibold text-page"
      style={{ background: `var(--${color})`, width: size, height: size, fontSize: size * 0.42 }}
      aria-hidden
    >
      {name.slice(0, 1).toUpperCase()}
    </span>
  )
}

// ---------------------------------------------------------------- people

function AddPerson({ needsPassword, onClose }: { needsPassword: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', username: '', password: '', role: 'member' })
  const save = useMutation({
    mutationFn: () => api.addPerson({
      name: f.name.trim(),
      username: f.username.trim() || null,
      password: f.password || null,
      role: f.role,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['people'] }); onClose() },
  })
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}
            className="relative w-full max-w-[440px] rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
            style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-start justify-between px-6 pt-5">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">Add someone</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="grid gap-4 px-6 pt-5">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">Their name</span>
            <input autoFocus required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })}
                   placeholder="Sam" className={field} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink">Username (optional)</span>
            <input value={f.username} autoCapitalize="none"
                   onChange={(e) => setF({ ...f, username: e.target.value })}
                   placeholder="made from their name if you leave it" className={field} />
          </label>
          {needsPassword && (
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-ink">Password</span>
              <input required type="password" minLength={8} value={f.password}
                     onChange={(e) => setF({ ...f, password: e.target.value })}
                     autoComplete="new-password" className={field} />
              <span className="text-[12px] text-ink-3">At least 8 characters. They can change it once they are in.</span>
            </label>
          )}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-[13px] font-medium text-ink">What they can do</legend>
            <div className="grid gap-1.5">
              {ROLES.map((r) => (
                <label key={r.value} className={cx('flex cursor-pointer items-start gap-2.5 rounded-xl border p-2.5',
                  f.role === r.value ? 'border-line-strong bg-surface-2' : 'border-line')}>
                  <input type="radio" name="role" value={r.value} checked={f.role === r.value}
                         onChange={() => setF({ ...f, role: r.value })}
                         className="mt-0.5 accent-[var(--accent)]" />
                  <span>
                    <span className="block text-[13px] font-medium text-ink">{r.label}</span>
                    <span className="block text-[12px] text-ink-3">{r.blurb}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="px-6 pt-3"><ErrorNote error={save.error} /></div>
        <div className="mt-4 flex justify-end gap-2 border-t border-line px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={save.isPending || !f.name.trim()}>
            {save.isPending ? 'Adding…' : 'Add'}
          </Button>
        </div>
      </form>
    </div>
  )
}

/**
 * Removing someone who owns accounts is never a silent default. Making them
 * the household's would expose exactly the accounts they chose to keep private;
 * the other way round throws away bank history. So it is asked, every time.
 */
function RemovePerson({ person, others, onClose }: { person: Person; others: Person[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [to, setTo] = useState<string>('')
  const remove = useMutation({
    mutationFn: () => api.removePerson(person.id, person.accounts ? Number(to) : undefined),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['people'] }); qc.invalidateQueries({ queryKey: ['accounts'] }); onClose() },
  })
  const needsChoice = (person.accounts ?? 0) > 0 && to === ''

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <div className="relative w-full max-w-[440px] rounded-t-3xl border border-line bg-surface sm:rounded-3xl"
           style={{ animation: 'rise .35s cubic-bezier(.16,1,.3,1) both' }}>
        <div className="flex items-start justify-between px-6 pt-5">
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">Remove {person.name}?</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-ink-2 hover:bg-hover" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="px-6 pt-4 text-[13px] text-ink-2">
          {!person.accounts ? (
            <>They own no accounts, so nothing else changes. They will no longer be able to sign in.</>
          ) : (
            <>
              {person.accounts} {person.accounts === 1 ? 'account belongs' : 'accounts belong'} to {person.name}.
              Those accounts have to go somewhere, and neither answer is safe to guess — making them the
              household&rsquo;s would show everyone exactly what {person.name} kept private.
            </>
          )}
        </div>
        {(person.accounts ?? 0) > 0 && (
          <div className="grid gap-1.5 px-6 pt-4">
            {[{ v: '0', label: "Make them the household's", blurb: 'Everyone in the household will see them.' },
              ...others.map((p) => ({ v: String(p.id), label: `Give them to ${p.name}`, blurb: `Only ${p.name} will see them.` }))]
              .map((o) => (
                <label key={o.v} className={cx('flex cursor-pointer items-start gap-2.5 rounded-xl border p-2.5',
                  to === o.v ? 'border-line-strong bg-surface-2' : 'border-line')}>
                  <input type="radio" name="reassign" value={o.v} checked={to === o.v}
                         onChange={() => setTo(o.v)} className="mt-0.5 accent-[var(--accent)]" />
                  <span>
                    <span className="block text-[13px] font-medium text-ink">{o.label}</span>
                    <span className="block text-[12px] text-ink-3">{o.blurb}</span>
                  </span>
                </label>
              ))}
          </div>
        )}
        <div className="px-6 pt-3"><ErrorNote error={remove.error} /></div>
        <div className="mt-4 flex justify-end gap-2 border-t border-line px-6 py-3">
          <Button variant="ghost" onClick={onClose}>Keep them</Button>
          <Button onClick={() => remove.mutate()} disabled={needsChoice || remove.isPending}
                  className="!bg-negative !text-white hover:brightness-110">
            {remove.isPending ? 'Removing…' : 'Remove'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function PersonRow({ p, me, canAdmin, others }: { p: Person; me: number | null; canAdmin: boolean; others: Person[] }) {
  const qc = useQueryClient()
  const [removing, setRemoving] = useState(false)
  const isMe = me === p.id
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.editPerson(p.id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['people'] }),
  })

  return (
    <li className="flex flex-wrap items-center gap-3 px-5 py-3">
      <Dot color={p.color} name={p.name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-medium text-ink">
          {p.name}{isMe && <span className="ml-1.5 text-[12px] font-normal text-ink-3">you</span>}
        </div>
        <div className="truncate text-[12px] text-ink-3">
          {p.username}
          {(p.accounts ?? 0) > 0 && ` · ${p.accounts} ${p.accounts === 1 ? 'account' : 'accounts'}`}
          {p.can_sign_in === false && ' · no password set'}
          {p.last_seen_at && ` · seen ${ago(p.last_seen_at)}`}
        </div>
      </div>
      {canAdmin ? (
        <select value={p.role} aria-label={`${p.name} role`} className={small}
                onChange={(e) => save.mutate({ role: e.target.value })}>
          {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      ) : (
        <span className="text-[12px] text-ink-3">{ROLES.find((r) => r.value === p.role)?.label}</span>
      )}
      {canAdmin && !isMe && (
        <button onClick={() => setRemoving(true)} className="p-1 text-ink-3 hover:text-negative"
                aria-label={`Remove ${p.name}`}>
          <Trash size={14} />
        </button>
      )}
      {removing && <RemovePerson person={p} others={others} onClose={() => setRemoving(false)} />}
      {save.error && <div className="w-full"><ErrorNote error={save.error} /></div>}
    </li>
  )
}

// ---------------------------------------------------------------- ownership

function Ownership({ people, canAdmin }: { people: Person[]; canAdmin: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['accounts'], queryFn: api.allAccounts })
  const setOwner = useMutation({
    mutationFn: ({ id, owner }: { id: string; owner: number | null }) => api.setAccountOwner(id, owner),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['accounts'] }); qc.invalidateQueries({ queryKey: ['people'] }) },
  })
  const accounts = (q.data ?? []) as OwnedAccount[]

  return (
    <Panel className="mt-4">
      <PanelHeader
        title="Who owns what"
        sub={canAdmin
          ? "The household's means everyone here sees it. One person's means only they do."
          : "The household's means everyone here sees it. Only an owner can move an account."}
      />
      {!q.data ? (
        <div className="p-5"><Skeleton className="h-32 rounded-xl" /></div>
      ) : accounts.length === 0 ? (
        <Empty title="No accounts yet">Connect a bank first and they will show up here.</Empty>
      ) : (
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {accounts.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] text-ink">
                  {a.name}{a.mask && <span className="text-ink-3"> ··{a.mask}</span>}
                </div>
                <div className="truncate text-[12px] text-ink-3">
                  {a.institution ?? accountTypeLabel[a.type] ?? a.type}
                </div>
              </div>
              {canAdmin ? (
                <select
                  aria-label={`Who owns ${a.name}`}
                  className={small}
                  value={a.owner_id == null ? '' : String(a.owner_id)}
                  onChange={(e) => setOwner.mutate({ id: a.id, owner: e.target.value === '' ? null : Number(e.target.value) })}
                >
                  <option value="">The household&rsquo;s</option>
                  {people.map((p) => <option key={p.id} value={p.id}>{p.name} only</option>)}
                </select>
              ) : (
                <span className="text-[13px] text-ink-3">
                  {a.owner_id == null ? "The household's"
                    : `${people.find((p) => p.id === a.owner_id)?.name ?? 'Someone'} only`}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="px-5 pb-4 pt-3"><ErrorNote error={setOwner.error} /></div>
    </Panel>
  )
}

// ---------------------------------------------------------------- share links

function todayISO() { return iso(new Date()) }
function yearStart(y: number) { return `${y}-01-01` }
function yearEnd(y: number) { return `${y}-12-31` }

function NewLink({ onCreated }: { onCreated: (url: string) => void }) {
  const qc = useQueryClient()
  const year = new Date().getFullYear()
  const [f, setF] = useState({
    label: `Accountant ${year - 1}`,
    start_date: yearStart(year - 1),
    end_date: yearEnd(year - 1),
    detail: 'summary',
    expires_on: '',
  })
  const create = useMutation({
    mutationFn: () => api.createShareLink({
      label: f.label.trim(), start_date: f.start_date, end_date: f.end_date,
      detail: f.detail, expires_on: f.expires_on || null,
    }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['share-links'] }); onCreated(`${window.location.origin}${r.url}`) },
  })

  const preset = (label: string, start: string, end: string) =>
    setF({ ...f, label, start_date: start, end_date: end })

  return (
    <form onSubmit={(e) => { e.preventDefault(); create.mutate() }} className="rounded-xl bg-surface-2 p-3">
      <div className="mb-2 flex flex-wrap gap-2">
        <button type="button" onClick={() => preset(`Accountant ${year - 1}`, yearStart(year - 1), yearEnd(year - 1))}
                className="rounded-full border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:bg-hover hover:text-ink">
          Last calendar year
        </button>
        <button type="button" onClick={() => preset(`${year} so far`, yearStart(year), todayISO())}
                className="rounded-full border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:bg-hover hover:text-ink">
          This year to date
        </button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-[12px] font-medium text-ink-3">What this link is for</span>
          <input required value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })}
                 placeholder="Accountant, 2025 taxes" className={field} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] font-medium text-ink-3">From</span>
          <input required type="date" value={f.start_date}
                 onChange={(e) => setF({ ...f, start_date: e.target.value })} className={field} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] font-medium text-ink-3">To</span>
          <input required type="date" value={f.end_date}
                 onChange={(e) => setF({ ...f, end_date: e.target.value })} className={field} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] font-medium text-ink-3">How much they see</span>
          <select value={f.detail} onChange={(e) => setF({ ...f, detail: e.target.value })} className={field}>
            <option value="summary">Totals and categories only</option>
            <option value="transactions">Totals and every transaction</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] font-medium text-ink-3">Stops working on</span>
          <input type="date" value={f.expires_on} onChange={(e) => setF({ ...f, expires_on: e.target.value })}
                 className={field} />
          <span className="text-[11px] text-ink-3">Left empty, it expires in 30 days.</span>
        </label>
      </div>
      <ErrorNote error={create.error} />
      <div className="mt-3 flex justify-end">
        <Button variant="primary" type="submit" disabled={create.isPending || !f.label.trim()}>
          {create.isPending ? 'Making it…' : 'Make the link'}
        </Button>
      </div>
    </form>
  )
}

function TokenOnce({ url, onDone }: { url: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard blocked: the text is on screen to copy by hand */ }
  }
  return (
    <div className="rounded-xl border border-line bg-accent-soft p-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-medium text-ink">
        <LinkIcon size={14} /> Copy this now — it is not shown again
      </div>
      <p className="mb-2 text-[12px] text-ink-2">
        The link itself is the password. Tally stores only a fingerprint of it, so if it is lost the
        link has to be replaced rather than looked up. Anyone who has it can read what it covers.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-lg border border-line bg-surface px-2.5 py-2 text-[12px] text-ink">
          {url}
        </code>
        <Button onClick={copy}>{copied ? <><Check size={13} weight="bold" /> Copied</> : <><Copy size={13} /> Copy</>}</Button>
        <Button variant="ghost" onClick={onDone}>Done</Button>
      </div>
    </div>
  )
}

function LinkRow({ l }: { l: ShareLink }) {
  const qc = useQueryClient()
  const revoke = useMutation({
    mutationFn: () => api.revokeShareLink(l.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['share-links'] }),
  })
  return (
    <li className={cx('flex flex-wrap items-center gap-3 px-5 py-3', l.dead && 'opacity-55')}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-medium text-ink">{l.label}</div>
        <div className="truncate text-[12px] text-ink-3">
          {fmtShort(l.start_date)} – {fmtShort(l.end_date)}
          {' · '}{l.detail === 'transactions' ? 'every transaction' : 'totals only'}
          {l.revoked ? ' · turned off'
            : l.expires_on ? ` · ${l.dead ? 'expired' : 'expires'} ${fmtShort(l.expires_on)}` : ' · no expiry'}
        </div>
      </div>
      <span className="flex items-center gap-1 text-[12px] text-ink-3" title={l.last_viewed_at ? `last opened ${ago(l.last_viewed_at)}` : 'never opened'}>
        <Eye size={13} /> {l.views === 0 ? 'not opened' : `${l.views}×`}
      </span>
      {!l.dead && (
        <button onClick={() => revoke.mutate()} disabled={revoke.isPending}
                className="inline-flex items-center gap-1 rounded-full border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:bg-hover hover:text-negative">
          Turn off
        </button>
      )}
    </li>
  )
}

function ShareLinks() {
  const [making, setMaking] = useState(false)
  const [fresh, setFresh] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['share-links'], queryFn: api.shareLinks })
  const links = q.data?.links ?? []

  return (
    <Panel className="mt-4">
      <PanelHeader
        title="Share links"
        sub="A read-only window for an accountant, over one date range. No login for them, no write access, and you can turn it off."
        action={!making && !fresh
          ? <Button onClick={() => setMaking(true)}><Plus size={14} weight="bold" /> New link</Button>
          : undefined}
      />
      <div className="px-5 pt-4">
        {fresh ? <TokenOnce url={fresh} onDone={() => { setFresh(null); setMaking(false) }} />
          : making ? (
            <>
              <NewLink onCreated={(url) => setFresh(url)} />
              <div className="mt-2 flex justify-end">
                <Button variant="ghost" onClick={() => setMaking(false)}>Cancel</Button>
              </div>
            </>
          ) : null}
      </div>
      <ErrorNote error={q.error} />
      {!q.data ? (
        <div className="p-5"><Skeleton className="h-20 rounded-xl" /></div>
      ) : links.length === 0 ? (
        <Empty title="No links yet" icon={<LinkIcon size={20} />}>
          Make one when somebody outside the household needs your numbers — an accountant, a lender, a
          mortgage broker. It shows what you choose and nothing else.
        </Empty>
      ) : (
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {links.map((l) => <LinkRow key={l.id} l={l} />)}
        </ul>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------- page

export default function Household() {
  const [adding, setAdding] = useState(false)
  const q = useQuery({ queryKey: ['people'], queryFn: api.people })
  const auth = useQuery({ queryKey: ['auth'], queryFn: api.authState })
  const people = q.data?.people ?? []
  const me = q.data?.me ?? null
  const myRole = people.find((p) => p.id === me)?.role
  // Nobody signed in means a one-person install or an authenticating proxy in
  // front; there is no one to refuse, and the backend agrees.
  const canAdmin = me == null || myRole === 'owner'
  const needsPassword = auth.data?.required ?? false

  return (
    <>
      <PageHeader title="Household" sub="Who is here, whose money is whose, and who else you have shown it to." />
      <ErrorNote error={q.error} />
      {adding && <AddPerson needsPassword={needsPassword} onClose={() => setAdding(false)} />}

      <div className="mb-4 flex items-start gap-2.5 rounded-2xl border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">
        <LockKey size={16} weight="fill" className="mt-0.5 shrink-0 text-ink-3" />
        <span>
          <b className="text-ink">An account with an owner is visible to that person alone.</b>{' '}
          Not to anyone else here, and not to a household owner either — that role administers people
          and bank connections, it does not read anybody&rsquo;s private accounts. Anything left as the
          household&rsquo;s is visible to everyone.
        </span>
      </div>

      {auth.data?.mode === 'proxy' && (
        <div className="mb-4 flex items-start gap-2.5 rounded-2xl border border-line bg-warn-soft px-4 py-3 text-[13px] text-ink">
          <ShieldWarning size={16} weight="fill" className="mt-0.5 shrink-0 text-warn" />
          <span>
            Something in front of Tally is doing the authenticating, so switching person here changes
            what is shown but is not a wall. For separate private accounts that actually hold, this
            install needs its own sign-in.
          </span>
        </div>
      )}

      <Panel>
        <PanelHeader
          title="People"
          sub={`${people.length} ${people.length === 1 ? 'person' : 'people'}`}
          action={canAdmin ? <Button onClick={() => setAdding(true)}><Plus size={14} weight="bold" /> Add</Button> : undefined}
        />
        {!q.data ? (
          <div className="p-5"><Skeleton className="h-28 rounded-xl" /></div>
        ) : people.length === 0 ? (
          <Empty title="Nobody yet" icon={<UsersThree size={20} />}>
            Add the people who share this money. Each gets their own sign-in.
          </Empty>
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {people.map((p) => (
              <PersonRow key={p.id} p={p} me={me} canAdmin={canAdmin}
                         others={people.filter((o) => o.id !== p.id)} />
            ))}
          </ul>
        )}
        {!canAdmin && (
          <div className="flex items-center gap-1.5 px-5 pb-4 pt-2 text-[12px] text-ink-3">
            <Warning size={12} /> Only a household owner can add or remove people.
          </div>
        )}
      </Panel>

      <Ownership people={people} canAdmin={canAdmin} />
      {canAdmin && <ShareLinks />}
    </>
  )
}
