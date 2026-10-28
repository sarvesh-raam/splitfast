import { api } from './api'

type CheckoutResponse = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }

type RazorpayInstance = { open: () => void; on: (event: string, cb: (resp: { error: { description: string } }) => void) => void }

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance
  }
}

let loading: Promise<void> | null = null

function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve()
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://checkout.razorpay.com/v1/checkout.js'
    s.onload = () => resolve()
    s.onerror = () => {
      loading = null
      reject(new Error('Could not load Razorpay. Check your connection.'))
    }
    document.head.appendChild(s)
  })
  return loading
}

type Order = { order_id: string; amount_paise: number; currency: string; key_id: string; payee_name: string }

/**
 * Opens Razorpay Checkout for an order and resolves once the server has
 * verified the signature. The webhook confirms the same payment independently;
 * the server makes sure only one of them creates the settlement.
 */
export async function payWithRazorpay(order: Order, prefill: { name: string; email: string }): Promise<'paid' | 'dismissed'> {
  await loadCheckout()
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay!({
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount_paise,
      currency: order.currency,
      name: 'SplitFast',
      description: `Settle up with ${order.payee_name}`,
      prefill,
      theme: { color: '#059669' },
      handler: (resp: CheckoutResponse) => {
        api('/api/payments/verify', { body: resp }).then(() => resolve('paid'), reject)
      },
      modal: { ondismiss: () => resolve('dismissed') },
    })
    rzp.on('payment.failed', (resp) => reject(new Error(resp.error.description || 'Payment failed')))
    rzp.open()
  })
}
