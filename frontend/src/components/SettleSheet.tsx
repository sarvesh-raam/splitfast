import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import QRCode from 'qrcode'
import { api, type Member, type Transfer } from '../lib/api'
import { useAuth } from '../lib/auth'
import { newId } from '../lib/id'
import { formatINR, parseRupees } from '../lib/money'
import { payWithRazorpay } from '../lib/razorpay'
import { canOpenUpiApps, upiLink } from '../lib/upi'
import { Avatar, Sheet, Spinner, useToast } from './ui'

type Order = { order_id: string; amount_paise: number; currency: string; key_id: string; payee_name: string }

export default function SettleSheet({
  groupId,
  groupName,
  transfer,
  members,
  onClose,
}: {
  groupId: string
  groupName: string
  transfer: Transfer
  members: Member[]
  onClose: () => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  // One id per sheet: retrying after a network drop can't record the payment twice.
  const [settlementId] = useState(newId)
  const [amountText, setAmountText] = useState((transfer.amount_paise / 100).toFixed(2).replace(/\.00$/, ''))
  // After the UPI app opens we can't see the result, so we ask the payer.
  const [askedDidPay, setAskedDidPay] = useState(false)
  const [qr, setQr] = useState({ link: '', url: '' })
  const config = useQuery({ queryKey: ['config'], queryFn: () => api<{ razorpay_key_id: string | null }>('/api/config'), staleTime: Infinity })

  const payer = members.find((m) => m.id === transfer.from_user)
  const payee = members.find((m) => m.id === transfer.to_user)
  const amount = parseRupees(amountText) ?? 0
  const valid = amount > 0 && amount <= 10_00_000_00
  const iPay = transfer.from_user === user?.id
  const mobile = canOpenUpiApps()
  const link =
    iPay && payee?.upi_id && valid
      ? upiLink({ upiId: payee.upi_id, name: payee.name, amountPaise: amount, note: `SplitFast ${groupName}` })
      : ''

  useEffect(() => {
    if (!link || mobile) return
    let cancelled = false
    QRCode.toDataURL(link, { margin: 1, width: 440 }).then((url) => !cancelled && setQr({ link, url }))
    return () => {
      cancelled = true
    }
  }, [link, mobile])
  // A QR drawn for an older amount is never shown.
  const qrUrl = qr.link === link ? qr.url : ''

  const refresh = () => {
    for (const key of ['balances', 'activity']) qc.invalidateQueries({ queryKey: [key, groupId] })
    qc.invalidateQueries({ queryKey: ['groups'] })
  }

  const record = useMutation({
    mutationFn: (method: 'cash' | 'upi') =>
      api<{ status: 'pending' | 'confirmed' }>(`/api/groups/${groupId}/settlements`, {
        body: { id: settlementId, from_user: transfer.from_user, to_user: transfer.to_user, amount_paise: amount, method },
      }),
    onSuccess: (r) => {
      refresh()
      toast(r.status === 'pending' ? `Marked as paid. ${payee?.name} will confirm it.` : 'Payment recorded')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'err'),
  })

  const online = useMutation({
    mutationFn: async () => {
      const order = await api<Order>(`/api/groups/${groupId}/payments`, { body: { to_user: transfer.to_user, amount_paise: amount } })
      return payWithRazorpay(order, { name: user!.name, email: user!.email })
    },
    onSuccess: (result) => {
      if (result !== 'paid') return
      refresh()
      toast('Payment successful')
      onClose()
    },
    onError: (e: Error) => toast(e.message, 'err'),
  })

  const busy = record.isPending || online.isPending

  if (iPay && askedDidPay) {
    return (
      <Sheet title="Did the payment go through?" onClose={onClose}>
        <p className="mb-5 text-sm text-slate-600 dark:text-slate-400">
          UPI apps don't tell SplitFast whether a payment worked. If {formatINR(amount)} left your account, mark it as paid and{' '}
          {payee?.name} will be asked to confirm they received it. Balances update once they do.
        </p>
        <div className="space-y-2">
          <button className="btn-primary w-full" disabled={busy} onClick={() => record.mutate('upi')}>
            {record.isPending && <Spinner />}
            Yes, I paid {formatINR(amount)}
          </button>
          <button className="btn-ghost w-full" disabled={busy} onClick={() => setAskedDidPay(false)}>
            No, go back
          </button>
        </div>
      </Sheet>
    )
  }

  return (
    <Sheet title="Settle up" onClose={onClose}>
      <div className="mb-4 flex items-center justify-center gap-3">
        <Avatar id={transfer.from_user} name={payer?.name ?? '?'} />
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14m-5-5 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" /></svg>
        <Avatar id={transfer.to_user} name={payee?.name ?? '?'} />
      </div>
      <p className="mb-3 text-center text-sm text-slate-500">
        {iPay ? `You pay ${payee?.name}` : `${payer?.name} pays you`}
      </p>
      <div className="relative mb-4">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xl font-semibold text-slate-400">₹</span>
        <input className="input pl-8 text-center text-2xl font-semibold" inputMode="decimal" value={amountText} onChange={(e) => setAmountText(e.target.value)} aria-label="Amount" />
      </div>
      {amount > transfer.amount_paise && (
        <p className="-mt-2 mb-4 text-center text-xs text-amber-600">That's more than the {formatINR(transfer.amount_paise)} suggested.</p>
      )}

      {iPay ? (
        <div className="space-y-2">
          {payee?.upi_id ? (
            mobile ? (
              <a
                href={link || undefined}
                className={`btn-primary w-full ${link ? '' : 'pointer-events-none opacity-50'}`}
                onClick={() => setTimeout(() => setAskedDidPay(true), 600)}
              >
                Pay {valid ? formatINR(amount) : ''} in GPay / PhonePe / Paytm
              </a>
            ) : (
              <div className="rounded-2xl border border-slate-200 p-4 text-center dark:border-slate-800">
                {qrUrl ? <img src={qrUrl} alt={`UPI QR code to pay ${payee.name}`} className="mx-auto h-48 w-48 rounded-lg bg-white p-1" /> : <div className="mx-auto h-48 w-48" />}
                <p className="mt-2 text-sm font-medium">Scan with any UPI app</p>
                <p className="text-xs text-slate-500">Pays {payee.upi_id} directly</p>
                <button className="btn-primary mt-3 w-full" disabled={!valid || busy} onClick={() => setAskedDidPay(true)}>
                  I've paid
                </button>
              </div>
            )
          ) : (
            <p className="rounded-xl bg-slate-100 px-3 py-2.5 text-center text-sm text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {payee?.name} hasn't added a UPI ID yet, so you can't pay them by UPI from here.
            </p>
          )}

          {config.data?.razorpay_key_id && (
            <button className="btn-ghost w-full" disabled={!valid || amount < 100 || busy} onClick={() => online.mutate()}>
              {online.isPending && <Spinner />}
              Pay by card / UPI via Razorpay (instant)
            </button>
          )}
          <button className="btn-ghost w-full" disabled={!valid || busy} onClick={() => record.mutate('cash')}>
            {record.isPending && <Spinner />}
            I paid in cash
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="mb-2 text-center text-xs text-slate-500">Only record this once the money is in your account.</p>
          <button className="btn-primary w-full" disabled={!valid || busy} onClick={() => record.mutate('upi')}>
            {record.isPending && <Spinner />}
            I received it by UPI
          </button>
          <button className="btn-ghost w-full" disabled={!valid || busy} onClick={() => record.mutate('cash')}>
            I received it in cash
          </button>
        </div>
      )}
    </Sheet>
  )
}
