import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Spinner } from '../components/ui'

export default function JoinPage() {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    api<{ id: string }>('/api/groups/join', { body: { invite_code: code } })
      .then((g) => {
        qc.invalidateQueries({ queryKey: ['groups'] })
        navigate(`/g/${g.id}`, { replace: true })
      })
      .catch((e: Error) => setError(e.message))
  }, [code, navigate, qc])

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
      {error ? (
        <>
          <p className="font-medium">{error}</p>
          <Link to="/" className="btn-ghost">Go to my groups</Link>
        </>
      ) : (
        <p className="flex items-center gap-2 text-slate-500"><Spinner /> Joining group…</p>
      )}
    </main>
  )
}
