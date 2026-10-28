import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Activity, type Expense, type GroupDetail, type PendingSettlement, type Snapshot, type Transfer } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useGroupSocket } from '../lib/hooks'
import { formatINR, timeAgo } from '../lib/money'
import { Avatar, Empty, Spinner, useToast } from '../components/ui'
import AddExpenseSheet from '../components/AddExpenseSheet'
import SettleSheet from '../components/SettleSheet'
import ProfileSheet from '../components/ProfileSheet'

type Tab = 'expenses' | 'balances' | 'activity'

export default function GroupPage() {
  const { groupId = '' } = useParams()
  const { user } = useAuth()
  const toast = useToast()
  const live = useGroupSocket(groupId)
  const [tab, setTab] = useState<Tab>('expenses')
  const [adding, setAdding] = useState(false)
  const [settling, setSettling] = useState<Transfer | null>(null)
  const [editingProfile, setEditingProfile] = useState(false)

  const group = useQuery({ queryKey: ['group', groupId], queryFn: () => api<GroupDetail>(`/api/groups/${groupId}`) })
  const balances = useQuery({ queryKey: ['balances', groupId], queryFn: () => api<Snapshot>(`/api/groups/${groupId}/balances`) })

  if (group.isError) {
    return (
      <main className="mx-auto max-w-md px-4 py-16 text-center">
        <p className="font-medium">{group.error.message}</p>
        <Link to="/" className="btn-ghost mt-4">Back to groups</Link>
      </main>
    )
  }
  if (!group.data || !user) {
    return <div className="flex min-h-dvh items-center justify-center text-slate-400"><Spinner /></div>
  }

  const g = group.data
  const names = new Map(g.members.map((m) => [m.id, m.name]))
  const me = balances.data?.members.find((m) => m.user_id === user.id)?.net_paise ?? 0

  const invite = async () => {
    const url = `${location.origin}/join/${g.invite_code}`
    try {
      if (navigator.share) await navigator.share({ title: `Join ${g.name} on SplitFast`, url })
      else {
        await navigator.clipboard.writeText(url)
        toast('Invite link copied')
      }
    } catch {
      /* share sheet dismissed */
    }
  }

  return (
    <main className="mx-auto min-h-dvh max-w-md px-4 pb-28 pt-[max(1rem,env(safe-area-inset-top))]">
      <header className="flex items-center gap-2 py-3">
        <Link to="/" className="-ml-2 rounded-full p-2 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Back">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="m15 18-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-bold">{g.name}</h1>
          <p className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className={`h-1.5 w-1.5 rounded-full ${live ? 'bg-emerald-500' : 'bg-slate-300'}`} />
            {live ? 'Live' : 'Connecting…'} · {g.members.length} {g.members.length === 1 ? 'member' : 'members'}
          </p>
        </div>
        <button onClick={invite} className="btn-ghost px-3 py-1.5 text-sm">Invite</button>
      </header>

      <section className="card mt-1 p-5 text-center">
        {me === 0 ? (
          <p className="text-lg font-semibold">You're all settled up</p>
        ) : (
          <>
            <p className="text-sm text-slate-500">{me > 0 ? 'Overall, you are owed' : 'Overall, you owe'}</p>
            <p className={`mt-1 text-3xl font-bold ${me > 0 ? 'pos' : 'neg'}`}>{formatINR(me)}</p>
          </>
        )}
      </section>

      {me > 0 && !user.upi_id && (
        <button
          onClick={() => setEditingProfile(true)}
          className="mt-3 w-full rounded-xl bg-amber-50 px-4 py-3 text-left text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200"
        >
          <b>Add your UPI ID</b> so friends can pay you straight from GPay or PhonePe →
        </button>
      )}

      <nav className="mt-5 grid grid-cols-3 rounded-xl bg-slate-200/60 p-1 text-sm font-medium dark:bg-slate-800">
        {(['expenses', 'balances', 'activity'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-lg py-2 capitalize transition ${tab === t ? 'bg-white shadow-sm dark:bg-slate-900' : 'text-slate-500'}`}
          >
            {t}
          </button>
        ))}
      </nav>

      <div className="mt-4">
        {tab === 'expenses' && <ExpenseList groupId={groupId} userId={user.id} names={names} />}
        {tab === 'balances' && (
          <Balances
            groupId={groupId}
            snapshot={balances.data}
            userId={user.id}
            names={names}
            onSettle={setSettling}
            memberCount={g.members.length}
          />
        )}
        {tab === 'activity' && <ActivityList groupId={groupId} />}
      </div>

      <div className="fixed inset-x-0 bottom-0 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <div className="mx-auto flex max-w-md justify-end px-4">
          <button className="btn-primary rounded-full px-5 py-3.5 shadow-lg shadow-brand-600/30" onClick={() => setAdding(true)}>
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Add expense
          </button>
        </div>
      </div>

      {adding && <AddExpenseSheet group={g} userId={user.id} onClose={() => setAdding(false)} />}
      {settling && (
        <SettleSheet groupId={groupId} groupName={g.name} transfer={settling} members={g.members} onClose={() => setSettling(null)} />
      )}
      {editingProfile && <ProfileSheet onClose={() => setEditingProfile(false)} />}
    </main>
  )
}

function ExpenseList({ groupId, userId, names }: { groupId: string; userId: string; names: Map<string, string> }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [open, setOpen] = useState<string | null>(null)
  const expenses = useQuery({ queryKey: ['expenses', groupId], queryFn: () => api<Expense[]>(`/api/groups/${groupId}/expenses`) })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/groups/${groupId}/expenses/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      for (const key of ['expenses', 'balances', 'activity']) qc.invalidateQueries({ queryKey: [key, groupId] })
      qc.invalidateQueries({ queryKey: ['groups'] })
      toast('Expense deleted')
    },
    onError: (e: Error) => toast(e.message, 'err'),
  })

  if (expenses.isPending) return <div className="flex justify-center p-8 text-slate-400"><Spinner /></div>
  if (expenses.isError) return <Empty title="Couldn't load expenses">{expenses.error.message}</Empty>
  if (expenses.data.length === 0) return <div className="card"><Empty title="No expenses yet">Tap “Add expense” to log the first one.</Empty></div>

  return (
    <ul className="card divide-y divide-slate-100 dark:divide-slate-800">
      {expenses.data.map((e) => {
        const mine = e.shares.find((s) => s.user_id === userId)?.share_paise ?? 0
        const iPaid = e.paid_by === userId
        const delta = iPaid ? e.amount_paise - mine : -mine
        const date = new Date(e.created_at)
        return (
          <li key={e.id}>
            <button className="flex w-full items-center gap-3 p-4 text-left" onClick={() => setOpen(open === e.id ? null : e.id)}>
              <span className="w-10 shrink-0 text-center text-xs leading-tight text-slate-500">
                {date.toLocaleDateString('en-IN', { month: 'short' })}
                <span className="block text-lg font-semibold text-slate-700 dark:text-slate-300">{date.getDate()}</span>
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{e.description}</span>
                <span className="text-sm text-slate-500">
                  {iPaid ? 'You' : names.get(e.paid_by) ?? 'Someone'} paid {formatINR(e.amount_paise)}
                </span>
              </span>
              <span className="text-right text-sm">
                {delta === 0 ? (
                  <span className="text-slate-400">not involved</span>
                ) : (
                  <>
                    <span className="block text-xs text-slate-500">{delta > 0 ? 'you lent' : 'you borrowed'}</span>
                    <span className={`font-semibold ${delta > 0 ? 'pos' : 'neg'}`}>{formatINR(delta)}</span>
                  </>
                )}
              </span>
            </button>
            {open === e.id && (
              <div className="space-y-1.5 bg-slate-50 px-4 py-3 text-sm dark:bg-slate-800/40">
                {e.shares.map((s) => (
                  <div key={s.user_id} className="flex justify-between">
                    <span>{s.user_id === userId ? 'You' : names.get(s.user_id)}</span>
                    <span className="tabular-nums">{formatINR(s.share_paise)}</span>
                  </div>
                ))}
                {(e.created_by === userId || iPaid) && (
                  <button
                    className="mt-2 text-sm font-medium text-rose-600"
                    disabled={remove.isPending}
                    onClick={() => confirm(`Delete “${e.description}”?`) && remove.mutate(e.id)}
                  >
                    Delete expense
                  </button>
                )}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function PendingPayments({
  groupId,
  pending,
  userId,
  names,
}: {
  groupId: string
  pending: PendingSettlement[]
  userId: string
  names: Map<string, string>
}) {
  const qc = useQueryClient()
  const toast = useToast()
  const respond = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'confirm' | 'reject' }) =>
      api<{ status: string }>(`/api/groups/${groupId}/settlements/${id}/${action}`, { method: 'POST' }),
    onSuccess: (r) => {
      for (const key of ['balances', 'activity']) qc.invalidateQueries({ queryKey: [key, groupId] })
      qc.invalidateQueries({ queryKey: ['groups'] })
      toast(r.status === 'confirmed' ? 'Payment confirmed' : 'Marked as not received')
    },
    onError: (e: Error) => toast(e.message, 'err'),
  })
  if (pending.length === 0) return null
  const name = (id: string) => names.get(id) ?? 'Someone'

  return (
    <section className="card border-amber-300 p-4 dark:border-amber-800">
      <h3 className="mb-3 font-semibold">Waiting for confirmation</h3>
      <ul className="space-y-2">
        {pending.map((p) => {
          const via = p.method === 'upi' ? 'UPI' : 'cash'
          return (
            <li key={p.id} className="rounded-xl bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
              {p.to_user === userId ? (
                <>
                  <p>
                    <b>{name(p.from_user)}</b> says they paid you <b>{formatINR(p.amount_paise)}</b> by {via}.
                    <span className="text-slate-500"> {timeAgo(p.created_at)}</span>
                  </p>
                  <p className="mt-1 text-xs text-slate-500">Check your bank or UPI app before confirming.</p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <button
                      className="btn-ghost py-2 text-sm"
                      disabled={respond.isPending}
                      onClick={() => respond.mutate({ id: p.id, action: 'reject' })}
                    >
                      Didn&apos;t get it
                    </button>
                    <button
                      className="btn-primary py-2 text-sm"
                      disabled={respond.isPending}
                      onClick={() => respond.mutate({ id: p.id, action: 'confirm' })}
                    >
                      Confirm
                    </button>
                  </div>
                </>
              ) : p.from_user === userId ? (
                <p>
                  You marked <b>{formatINR(p.amount_paise)}</b> ({via}) as paid to <b>{name(p.to_user)}</b>. Waiting for them to confirm.
                </p>
              ) : (
                <p className="text-slate-600 dark:text-slate-400">
                  {name(p.from_user)} → {name(p.to_user)} {formatINR(p.amount_paise)} ({via}), awaiting confirmation
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Balances({
  groupId,
  snapshot,
  userId,
  names,
  onSettle,
  memberCount,
}: {
  groupId: string
  snapshot: Snapshot | undefined
  userId: string
  names: Map<string, string>
  onSettle: (t: Transfer) => void
  memberCount: number
}) {
  if (!snapshot) return <div className="flex justify-center p-8 text-slate-400"><Spinner /></div>
  const who = (id: string) => (id === userId ? 'You' : names.get(id) ?? 'Someone')
  const saved = snapshot.naive_transfer_count - snapshot.transfers.length

  return (
    <div className="space-y-4">
      <PendingPayments groupId={groupId} pending={snapshot.pending} userId={userId} names={names} />
      <section className="card p-4">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="font-semibold">Suggested payments</h3>
          {snapshot.transfers.length > 0 && (
            <span className="text-xs text-slate-500">
              {snapshot.transfers.length} {snapshot.transfers.length === 1 ? 'payment' : 'payments'}
              {saved > 0 && ` instead of ${snapshot.naive_transfer_count}`}
            </span>
          )}
        </div>
        {snapshot.transfers.length === 0 ? (
          <p className="text-sm text-slate-500">{memberCount < 2 ? 'Invite people to start splitting.' : 'Everyone is settled up.'}</p>
        ) : (
          <ul className="space-y-2">
            {snapshot.transfers.map((t) => {
              const involved = t.from_user === userId || t.to_user === userId
              const awaiting = snapshot.pending.some((p) => p.from_user === t.from_user && p.to_user === t.to_user)
              return (
                <li key={`${t.from_user}-${t.to_user}`} className="flex items-center gap-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/50">
                  <Avatar id={t.from_user} name={names.get(t.from_user) ?? '?'} size="sm" />
                  <span className="min-w-0 flex-1 text-sm">
                    <b>{who(t.from_user)}</b> {t.from_user === userId ? 'pay' : 'pays'} <b>{who(t.to_user)}</b>
                    <span className="block font-semibold">{formatINR(t.amount_paise)}</span>
                  </span>
                  {awaiting ? (
                    <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
                      Confirming
                    </span>
                  ) : involved && (
                    <button className={t.from_user === userId ? 'btn-primary px-3 py-1.5 text-sm' : 'btn-ghost px-3 py-1.5 text-sm'} onClick={() => onSettle(t)}>
                      {t.from_user === userId ? 'Settle' : 'Record'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        {saved > 0 && (
          <p className="mt-3 text-xs text-slate-500">
            Debts are simplified across the group, so {saved} fewer {saved === 1 ? 'payment is' : 'payments are'} needed than paying everyone back one by one.
          </p>
        )}
      </section>

      <section className="card divide-y divide-slate-100 dark:divide-slate-800">
        {snapshot.members.map((m) => (
          <div key={m.user_id} className="flex items-center gap-3 p-4">
            <Avatar id={m.user_id} name={m.name} />
            <span className="flex-1 font-medium">{m.user_id === userId ? `${m.name} (you)` : m.name}</span>
            <span className={`font-semibold tabular-nums ${m.net_paise > 0 ? 'pos' : m.net_paise < 0 ? 'neg' : 'text-slate-400'}`}>
              {m.net_paise === 0 ? 'settled' : `${m.net_paise > 0 ? '+' : '−'}${formatINR(m.net_paise)}`}
            </span>
          </div>
        ))}
      </section>
    </div>
  )
}

function ActivityList({ groupId }: { groupId: string }) {
  const activity = useQuery({ queryKey: ['activity', groupId], queryFn: () => api<Activity[]>(`/api/groups/${groupId}/activity`) })
  if (activity.isPending) return <div className="flex justify-center p-8 text-slate-400"><Spinner /></div>
  if (activity.isError) return <Empty title="Couldn't load activity">{activity.error.message}</Empty>
  return (
    <ul className="card divide-y divide-slate-100 dark:divide-slate-800">
      {activity.data.map((a) => (
        <li key={a.id} className="flex gap-3 p-4 text-sm">
          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
          <span className="flex-1">{a.summary}</span>
          <span className="shrink-0 text-xs text-slate-400">{timeAgo(a.created_at)}</span>
        </li>
      ))}
    </ul>
  )
}
