/**
 * UPI deep link (NPCI "upi://pay" intent). Opening it hands the payment to
 * GPay / PhonePe / Paytm with the payee and amount filled in; the money moves
 * bank to bank and nothing reports back to us, hence receiver confirmation.
 */
export function upiLink({ upiId, name, amountPaise, note }: { upiId: string; name: string; amountPaise: number; note: string }) {
  // Encoded by hand: URLSearchParams turns spaces into "+", which some UPI apps show
  // literally, and a few apps fail to decode "%40" back into the "@" of a UPI ID.
  const params: [string, string][] = [
    ['pa', upiId],
    ['pn', name],
    ['am', (amountPaise / 100).toFixed(2)],
    ['cu', 'INR'],
    ['tn', note.slice(0, 50)],
  ]
  return 'upi://pay?' + params.map(([k, v]) => `${k}=${encodeURIComponent(v).replace(/%40/g, '@')}`).join('&')
}

export const UPI_ID_PATTERN = /^[A-Za-z0-9._-]{2,255}@[A-Za-z][A-Za-z0-9]{1,63}$/

/** Phones and tablets can open UPI apps; desktops get a QR code to scan instead. */
export function canOpenUpiApps(): boolean {
  return window.matchMedia('(pointer: coarse)').matches
}
