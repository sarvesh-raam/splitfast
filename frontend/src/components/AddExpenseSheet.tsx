import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type GroupDetail, type SplitType } from '../lib/api'
import { apportion, formatINR, parsePercent, parseRupees } from '../lib/money'
import { newId } from '../lib/id'
import { Sheet, Spinner, useToast } from './ui'

const SPLIT_LABELS: Record<SplitType, string> = { equal: 'Equally', exact: 'Exact ₹', percent: '%', shares: 'Shares' }

type Plan = { shares: Map<string, number>; splits: { user_id: string; value: number }[]; error: string }

export default function AddExpenseSheet({ group, userId, onClose }: { group: GroupDetail; userId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  // Generated once per sheet, so a retry after a network drop can't double-add.
  const [expenseId] = useState(newId)
  const [description, setDescription] = useState('')
  const [amountText, setAmountText] = useState('')
  const [paidBy, setPaidBy] = useState(userId)
  const [splitType, setSplitType] = useState<SplitType>('equal')
  const [included, setIncluded] = useState(() => new Set(group.members.map((m) => m.id)))
  const [inputs, setInputs] = useState<Record<string, string>>({})

  const amount = parseRupees(amountText) ?? 0

  const plan = useMemo<Plan>(() => {
    const members = group.members
    if (splitType === 'equal') {
      const ids = members.filter((m) => included.has(m.id)).map((m) => m.id)
      return {
        shares: apportion(amount, ids.map((id) => ({ id, weight: 1 }))),
        splits: ids.map((id) => ({ user_id: id, value: 0 })),
        error: ids.length === 0 ? 'Pick at least one person' : '',
      }
    }
    if (splitType === 'exact') {
      const splits = members
        .map((m) => ({ user_id: m.id, value: parseRupees(inputs[m.id] ?? '') ?? 0 }))
        .filter((s) => s.value > 0)
      const total = splits.reduce((s, x) => s + x.value, 0)
      const diff = amount - total
      return {
        shares: new Map(splits.map((s) => [s.user_id, s.value])),
        splits,
        error: diff === 0 ? '' : diff > 0 ? `${formatINR(diff)} left to assign` : `${formatINR(-diff)} too much`,
      }
    }
    if (splitType === 'percent') {
      const splits = members
        .map((m) => ({ user_id: m.id, value: parsePercent(inputs[m.id] ?? '') ?? 0 }))
        .filter((s) => s.value > 0)
      const total = splits.reduce((s, x) => s + x.value, 0)
      return {
        shares: apportion(amount, splits.map((s) => ({ id: s.user_id, weight: s.value }))),
        splits,
        error: total === 10000 ? '' : `${((10000 - total) / 100).toFixed(2).replace(/\.00$/, '')}% left to assign`,
      }
    }
    const splits = members
      .map((m) => ({ user_id: m.id, value: Number.parseInt(inputs[m.id] ?? '1', 10) || 0 }))
      .filter((s) => s.value > 0)
    return {
      shares: apportion(amount, splits.map((s) => ({ id: s.user_id, weight: s.value }))),
      splits,
      error: splits.length === 0 ? 'Give at least one person a share' : '',
    }
  }, [group.members, splitType, included, inputs, amount])

  const save = useMutation({
    mutationFn: () =>
      api(`/api/groups/${group.id}/expenses`, {
        body: {
          id: expenseId,
          description: description.trim(),
          amount_paise: amount,
          paid_by: paidBy,
          split_type: splitType,
          splits: plan.splits,
        },
      }),
    onSuccess: () => {
      for (const key of ['expenses', 'balances', 'activity']) qc.invalidateQueries({ queryKey: [key, group.id] })
      qc.invalidateQueries({ queryKey: ['groups'] })
      toast('Expense added')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'err'),
  })

  const canSave = description.trim() && amount > 0 && !plan.error && !save.isPending

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (canSave) save.mutate()
  }

  return (
    <Sheet title="Add expense" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <input className="input" placeholder="What was it for?" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={120} required />
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xl font-semibold text-slate-400">₹</span>
          <input
            className="input pl-8 text-2xl font-semibold"
            inputMode="decimal"
            placeholder="0"
            value={amountText}
            onChange={(e) => setAmountText(e.target.value)}
            aria-label="Amount in rupees"
            required
          />
        </div>

        <label className="flex items-center gap-3 text-sm">
          <span className="shrink-0 font-medium">Paid by</span>
          <select className="input py-2" value={paidBy} onChange={(e) => setPaidBy(e.target.value)}>
            {group.members.map((m) => (
              <option key={m.id} value={m.id}>{m.id === userId ? 'You' : m.name}</option>
            ))}
          </select>
        </label>

        <div>
          <p className="mb-2 text-sm font-medium">Split</p>
          <div className="grid grid-cols-4 rounded-xl bg-slate-100 p-1 text-sm font-medium dark:bg-slate-800">
            {(Object.keys(SPLIT_LABELS) as SplitType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  setSplitType(t)
                  setInputs({})
                }}
                className={`rounded-lg py-1.5 transition ${splitType === t ? 'bg-white shadow-sm dark:bg-slate-900' : 'text-slate-500'}`}
              >
                {SPLIT_LABELS[t]}
              </button>
            ))}
          </div>
        </div>

        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {group.members.map((m) => {
            const share = plan.shares.get(m.id) ?? 0
            return (
              <li key={m.id} className="flex items-center gap-3 px-3 py-2.5">
                {splitType === 'equal' ? (
                  <label className="flex flex-1 items-center gap-3">
                    <input
                      type="checkbox"
                      className="h-5 w-5 accent-brand-600"
                      checked={included.has(m.id)}
                      onChange={(e) => {
                        const next = new Set(included)
                        if (e.target.checked) next.add(m.id)
                        else next.delete(m.id)
                        setIncluded(next)
                      }}
                    />
                    <span>{m.id === userId ? 'You' : m.name}</span>
                  </label>
                ) : (
                  <>
                    <span className="flex-1">{m.id === userId ? 'You' : m.name}</span>
                    <input
                      className="input w-24 py-1.5 text-right"
                      inputMode={splitType === 'shares' ? 'numeric' : 'decimal'}
                      placeholder={splitType === 'shares' ? '1' : '0'}
                      value={inputs[m.id] ?? ''}
                      onChange={(e) => setInputs({ ...inputs, [m.id]: e.target.value })}
                      aria-label={`${m.name} ${splitType}`}
                    />
                    {splitType === 'percent' && <span className="text-slate-400">%</span>}
                  </>
                )}
                <span className="w-20 text-right text-sm tabular-nums text-slate-500">{share ? formatINR(share) : '–'}</span>
              </li>
            )
          })}
        </ul>

        {amount > 0 && plan.error && <p className="text-sm text-amber-600 dark:text-amber-400">{plan.error}</p>}

        <button className="btn-primary w-full" disabled={!canSave}>
          {save.isPending && <Spinner />}
          Save expense
        </button>
      </form>
    </Sheet>
  )
}
