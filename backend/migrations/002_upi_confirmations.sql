-- Direct UPI payments go bank-to-bank between friends, so the app never sees
-- them. Settlements recorded by the payer therefore start as 'pending' and only
-- count towards balances once the receiver confirms the money arrived.

ALTER TABLE users
    ADD COLUMN upi_id text CHECK (upi_id ~ '^[A-Za-z0-9._-]{2,255}@[A-Za-z][A-Za-z0-9]{1,63}$');

ALTER TABLE settlements DROP CONSTRAINT settlements_method_check;
ALTER TABLE settlements
    ADD CONSTRAINT settlements_method_check CHECK (method IN ('cash', 'upi', 'razorpay'));

-- Existing rows were all immediate settlements, so they backfill as confirmed.
ALTER TABLE settlements
    ADD COLUMN status text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('pending', 'confirmed', 'rejected')),
    ADD COLUMN responded_at timestamptz,
    -- A Razorpay settlement is proven by a signed webhook; it is never pending.
    ADD CONSTRAINT settlements_razorpay_confirmed CHECK (method <> 'razorpay' OR status = 'confirmed');

CREATE INDEX settlements_pending_idx ON settlements (group_id) WHERE status = 'pending';
