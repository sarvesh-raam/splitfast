export function formatINR(paise: number): string {
  const abs = Math.abs(paise)
  const hasPaise = abs % 100 !== 0
  return (
    '₹' +
    (abs / 100).toLocaleString('en-IN', {
      minimumFractionDigits: hasPaise ? 2 : 0,
      maximumFractionDigits: 2,
    })
  )
}

/** "1,250.5" -> 125050 paise. Returns null for anything that isn't a valid amount. */
export function parseRupees(input: string): number | null {
  const clean = input.replace(/[,\s₹]/g, '')
  if (!/^\d+(\.\d{0,2})?$/.test(clean)) return null
  const [whole, frac = ''] = clean.split('.')
  return Number(whole) * 100 + Number(frac.padEnd(2, '0'))
}

/** "33.33" -> 3333 basis points. */
export function parsePercent(input: string): number | null {
  const clean = input.trim()
  if (!/^\d+(\.\d{0,2})?$/.test(clean)) return null
  const [whole, frac = ''] = clean.split('.')
  return Number(whole) * 100 + Number(frac.padEnd(2, '0'))
}

/**
 * Same largest-remainder apportionment as the server (app/money.py), so the
 * preview matches what gets saved to the paisa.
 */
export function apportion(amount: number, weights: { id: string; weight: number }[]): Map<string, number> {
  const total = weights.reduce((s, w) => s + w.weight, 0)
  const out = new Map<string, number>()
  if (total <= 0 || amount <= 0) return out
  const big = BigInt(amount)
  const T = BigInt(total)
  let given = 0n
  for (const w of weights) {
    const v = (big * BigInt(w.weight)) / T
    out.set(w.id, Number(v))
    given += v
  }
  const leftover = Number(big - given)
  const order = [...weights].sort((a, b) => {
    const ra = (big * BigInt(a.weight)) % T
    const rb = (big * BigInt(b.weight)) % T
    if (ra !== rb) return ra > rb ? -1 : 1
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
  })
  for (const w of order.slice(0, leftover)) out.set(w.id, (out.get(w.id) ?? 0) + 1)
  return out
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
