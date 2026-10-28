import { useState, type FormEvent } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { Spinner } from '../components/ui'

export default function AuthPage() {
  const { user, login, register } = useAuth()
  const [params] = useSearchParams()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const next = params.get('next')
  if (user) return <Navigate to={next?.startsWith('/') ? next : '/'} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'login') await login(email, password)
      else await register(name, email, password)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center px-5 py-10">
      <div className="mb-8 text-center">
        <img src="/logo.svg" alt="" className="mx-auto mb-4 h-16 w-16 rounded-2xl shadow-lg shadow-brand-600/20" />
        <h1 className="text-3xl font-bold tracking-tight">SplitFast</h1>
        <p className="mt-2 text-slate-500">Share expenses. Settle up in the fewest payments.</p>
      </div>

      <form onSubmit={submit} className="card space-y-4 p-5">
        <div className="grid grid-cols-2 rounded-xl bg-slate-100 p-1 text-sm font-medium dark:bg-slate-800">
          {(['login', 'register'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-lg py-2 transition ${mode === m ? 'bg-white shadow-sm dark:bg-slate-900' : 'text-slate-500'}`}
            >
              {m === 'login' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>

        {mode === 'register' && (
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Your name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} autoComplete="name" />
          </label>
        )}
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Email</span>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Password</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === 'register' ? 8 : undefined}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />
          {mode === 'register' && <span className="mt-1 block text-xs text-slate-500">At least 8 characters</span>}
        </label>

        {error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-300">{error}</p>}

        <button className="btn-primary w-full" disabled={busy}>
          {busy && <Spinner />}
          {mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
      </form>
    </main>
  )
}
