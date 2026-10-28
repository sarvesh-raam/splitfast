export type User = { id: string; name: string; email: string; upi_id: string | null }
export type GroupSummary = {
  id: string
  name: string
  invite_code: string
  member_count: number
  my_net_paise: number
  to_confirm: number
}
export type Member = { id: string; name: string; upi_id: string | null }
export type GroupDetail = { id: string; name: string; invite_code: string; members: Member[] }
export type Transfer = { from_user: string; to_user: string; amount_paise: number }
export type PendingSettlement = {
  id: string
  from_user: string
  to_user: string
  amount_paise: number
  method: 'cash' | 'upi'
  created_at: string
}
export type Snapshot = {
  members: { user_id: string; name: string; net_paise: number }[]
  transfers: Transfer[]
  naive_transfer_count: number
  pending: PendingSettlement[]
}
export type SplitType = 'equal' | 'exact' | 'percent' | 'shares'
export type Expense = {
  id: string
  description: string
  amount_paise: number
  split_type: SplitType
  paid_by: string
  created_by: string
  created_at: string
  shares: { user_id: string; share_paise: number }[]
}
export type Activity = { id: number; kind: string; summary: string; created_at: string }

const TOKEN_KEY = 'splitfast.token'
const USER_KEY = 'splitfast.user'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function getToken(): string | null {
  return read(TOKEN_KEY)
}

export function getStoredUser(): User | null {
  const raw = read(USER_KEY)
  return raw ? (JSON.parse(raw) as User) : null
}

export function saveSession(token: string, user: User) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    /* private mode: session lasts until reload */
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = getToken()
  let res: Response
  try {
    res = await fetch(path, {
      method: options.method ?? (options.body ? 'POST' : 'GET'),
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'You seem to be offline. Check your connection and try again.')
  }

  if (res.status === 401 && token) {
    clearSession()
    window.dispatchEvent(new Event('splitfast:logout'))
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) message = data.detail[0].msg.replace(/^Value error, /, '')
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}
