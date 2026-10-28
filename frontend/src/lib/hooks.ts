import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getToken, type Snapshot } from './api'

/**
 * Subscribes to a group's live updates. The server pushes a fresh balance
 * snapshot after every committed change; we drop it straight into the query
 * cache and refetch the lists that changed. Reconnects with backoff.
 */
export function useGroupSocket(groupId: string): boolean {
  const qc = useQueryClient()
  const [live, setLive] = useState(false)

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let stopped = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/groups/${groupId}?token=${encodeURIComponent(getToken() ?? '')}`)
      ws.onopen = () => {
        attempt = 0
        setLive(true)
      }
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as { type: string; kind: string; balances: Snapshot }
        if (msg.type !== 'group.updated') return
        qc.setQueryData(['balances', groupId], msg.balances)
        if (msg.kind === 'connected') return
        qc.invalidateQueries({ queryKey: ['expenses', groupId] })
        qc.invalidateQueries({ queryKey: ['activity', groupId] })
        qc.invalidateQueries({ queryKey: ['groups'] })
        if (msg.kind === 'member.joined') qc.invalidateQueries({ queryKey: ['group', groupId] })
      }
      ws.onclose = (e) => {
        setLive(false)
        if (stopped || e.code === 4401 || e.code === 4404) return
        timer = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 15000))
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      ws?.close()
    }
  }, [groupId, qc])

  return live
}

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }

/** Chrome/Edge/Android fire beforeinstallprompt; iOS needs Share -> Add to Home Screen. */
export function useInstallPrompt() {
  const [event, setEvent] = useState<InstallEvent | null>(null)
  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault()
      setEvent(e as InstallEvent)
    }
    const onInstalled = () => setEvent(null)
    window.addEventListener('beforeinstallprompt', onPrompt)
    window.addEventListener('appinstalled', onInstalled)
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [])
  if (!event) return null
  return async () => {
    await event.prompt()
    await event.userChoice
    setEvent(null)
  }
}
