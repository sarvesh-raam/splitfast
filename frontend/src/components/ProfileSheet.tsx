import { useState, type FormEvent } from 'react'
import { useAuth } from '../lib/auth'
import { UPI_ID_PATTERN } from '../lib/upi'
import { Avatar, Sheet, Spinner, useToast } from './ui'

export default function ProfileSheet({ onClose }: { onClose: () => void }) {
  const { user, setUpiId, logout } = useAuth()
  const toast = useToast()
  const [upi, setUpi] = useState(user?.upi_id ?? '')
  const [busy, setBusy] = useState(false)
  if (!user) return null

  const trimmed = upi.trim()
  const valid = trimmed === '' || UPI_ID_PATTERN.test(trimmed)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    setBusy(true)
    try {
      await setUpiId(trimmed)
      toast(trimmed ? 'UPI ID saved' : 'UPI ID removed')
      onClose()
    } catch (err) {
      toast((err as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet title="Your profile" onClose={onClose}>
      <div className="mb-5 flex items-center gap-3">
        <Avatar id={user.id} name={user.name} />
        <div className="min-w-0">
          <p className="font-medium">{user.name}</p>
          <p className="truncate text-sm text-slate-500">{user.email}</p>
        </div>
      </div>
      <form onSubmit={save} className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Your UPI ID</span>
          <input
            className="input"
            placeholder="yourname@okaxis"
            value={upi}
            onChange={(e) => setUpi(e.target.value)}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
          <span className={`mt-1 block text-xs ${valid ? 'text-slate-500' : 'text-rose-600'}`}>
            {valid
              ? 'Friends in your groups use this to pay you directly from GPay, PhonePe or Paytm.'
              : 'That doesn’t look like a UPI ID. It should look like name@bank.'}
          </span>
        </label>
        <button className="btn-primary w-full" disabled={!valid || busy || trimmed === (user.upi_id ?? '')}>
          {busy && <Spinner />}
          Save
        </button>
      </form>
      <button className="mt-6 w-full text-sm font-medium text-rose-600" onClick={logout}>
        Sign out
      </button>
    </Sheet>
  )
}
