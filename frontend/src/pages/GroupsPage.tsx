import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type GroupSummary } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useInstallPrompt } from '../lib/hooks'
import { formatINR } from '../lib/money'
import { Avatar, Empty, Sheet, Spinner, useToast } from '../components/ui'
import ProfileSheet from '../components/ProfileSheet'

function NetLabel({ paise }: { paise: number }) {
  if (paise === 0) return <span className="text-sm text-slate-500">settled up</span>
  return (
    <span className="text-right">
      <span className="block text-xs text-slate-500">{paise > 0 ? 'you are owed' : 'you owe'}</span>
      <span className={`font-semibold ${paise > 0 ? 'pos' : 'neg'}`}>{formatINR(paise)}</span>
    </span>
  )
}

export default function GroupsPage() {
  const { user } = useAuth()
  const install = useInstallPrompt()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [sheet, setSheet] = useState<'create' | 'join' | 'profile' | null>(null)
  const [value, setValue] = useState('')

  const groups = useQuery({ queryKey: ['groups'], queryFn: () => api<GroupSummary[]>('/api/groups') })

  const submit = useMutation({
    mutationFn: async () => {
      if (sheet === 'create') return api<{ id: string }>('/api/groups', { body: { name: value.trim() } })
      // Accept a full invite link or just the code.
      const code = value.trim().split('/join/').pop() ?? ''
      return api<{ id: string }>('/api/groups/join', { body: { invite_code: code } })
    },
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ['groups'] })
      setSheet(null)
      setValue('')
      navigate(`/g/${g.id}`)
    },
    onError: (e: Error) => toast(e.message, 'err'),
  })

  const total = (groups.data ?? []).reduce(
    (acc, g) => (g.my_net_paise > 0 ? { ...acc, owed: acc.owed + g.my_net_paise } : { ...acc, owe: acc.owe - g.my_net_paise }),
    { owed: 0, owe: 0 },
  )

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (value.trim()) submit.mutate()
  }

  return (
    <main className="mx-auto min-h-dvh max-w-md px-4 pb-28 pt-[max(1rem,env(safe-area-inset-top))]">
      <header className="flex items-center justify-between py-3">
        <div className="flex items-center gap-2">
          <img src="/logo.svg" alt="" className="h-8 w-8 rounded-lg" />
          <span className="text-xl font-bold tracking-tight">SplitFast</span>
        </div>
        <div className="flex items-center gap-2">
          {install && (
            <button onClick={install} className="btn-ghost px-3 py-1.5 text-sm">Install app</button>
          )}
          <button onClick={() => setSheet('profile')} aria-label="Your profile" className="rounded-full">
            {user && <Avatar id={user.id} name={user.name} size="sm" />}
          </button>
        </div>
      </header>

      <section className="mt-2 grid grid-cols-2 gap-3">
        <div className="card p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">You are owed</p>
          <p className="pos mt-1 text-2xl font-bold">{formatINR(total.owed)}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">You owe</p>
          <p className="neg mt-1 text-2xl font-bold">{formatINR(total.owe)}</p>
        </div>
      </section>

      <h2 className="mb-2 mt-6 px-1 text-sm font-semibold text-slate-500">Your groups</h2>
      <section className="card divide-y divide-slate-100 dark:divide-slate-800">
        {groups.isPending && <div className="flex justify-center p-8 text-slate-400"><Spinner /></div>}
        {groups.isError && <Empty title="Couldn't load your groups">{groups.error.message}</Empty>}
        {groups.data?.length === 0 && (
          <Empty title="No groups yet">Create one for your flat, a trip or a dinner, then share the invite link.</Empty>
        )}
        {groups.data?.map((g) => (
          <Link key={g.id} to={`/g/${g.id}`} className="flex items-center gap-3 p-4 transition hover:bg-slate-50 dark:hover:bg-slate-800/50">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-100 text-lg font-bold text-brand-700 dark:bg-brand-700/30 dark:text-brand-100">
              {g.name[0]?.toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{g.name}</span>
              <span className="text-sm text-slate-500">{g.member_count} {g.member_count === 1 ? 'member' : 'members'}</span>
              {g.to_confirm > 0 && (
                <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
                  {g.to_confirm} to confirm
                </span>
              )}
            </span>
            <NetLabel paise={g.my_net_paise} />
          </Link>
        ))}
      </section>

      <div className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-slate-50 via-slate-50 to-transparent pb-[max(1rem,env(safe-area-inset-bottom))] pt-6 dark:from-slate-950 dark:via-slate-950">
        <div className="mx-auto grid max-w-md grid-cols-2 gap-3 px-4">
          <button className="btn-ghost" onClick={() => setSheet('join')}>Join with link</button>
          <button className="btn-primary" onClick={() => setSheet('create')}>New group</button>
        </div>
      </div>

      {sheet === 'profile' && <ProfileSheet onClose={() => setSheet(null)} />}
      {(sheet === 'create' || sheet === 'join') && (
        <Sheet title={sheet === 'create' ? 'New group' : 'Join a group'} onClose={() => setSheet(null)}>
          <form onSubmit={onSubmit} className="space-y-4">
            <input
              className="input"
              placeholder={sheet === 'create' ? 'e.g. Goa trip, Flat 4B' : 'Paste invite link or code'}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              maxLength={sheet === 'create' ? 80 : 200}
              required
            />
            <button className="btn-primary w-full" disabled={submit.isPending}>
              {submit.isPending && <Spinner />}
              {sheet === 'create' ? 'Create group' : 'Join group'}
            </button>
          </form>
        </Sheet>
      )}
    </main>
  )
}
