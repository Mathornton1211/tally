-- Debt terms from the issuer, goals, and plan settings.
--
-- Plaid's Liabilities product gives the three numbers that decide everything
-- when money is tight: the APR, the minimum payment, and the due date. They
-- come from the card issuer, so nothing here has to be typed in by hand.

CREATE TABLE liabilities (
    account_id             text PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    kind                   text NOT NULL,              -- credit | student | mortgage
    apr                    numeric(6,3),               -- the rate that applies to a carried balance
    aprs                   jsonb,                      -- every APR Plaid reported, for display
    last_statement_balance numeric(14,2),
    last_statement_date    date,
    minimum_payment        numeric(14,2),
    next_due_date          date,
    is_overdue             boolean,
    last_payment_amount    numeric(14,2),
    last_payment_date      date,
    -- plaid: from the issuer. user: entered in Accounts. demo: seeded sandbox data.
    source                 text NOT NULL DEFAULT 'plaid',
    raw                    jsonb,
    updated_at             timestamptz NOT NULL DEFAULT now()
);

-- Small key/value store for things with exactly one value: how much extra Mat
-- can put toward debt, the cash floor he wants to keep, which payoff order he
-- picked. No migration needed to add the next one.
CREATE TABLE app_settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Goals matter in both directions: paying a card off, and later building the
-- cushion that stops the cards coming back.
CREATE TABLE goals (
    id                   serial PRIMARY KEY,
    name                 text NOT NULL,
    kind                 text NOT NULL CHECK (kind IN ('emergency', 'savings', 'payoff', 'custom')),
    target_amount        numeric(14,2),
    -- Progress is read live from this account when set, so a goal is never a
    -- number the owner has to keep updated by hand.
    account_id           text REFERENCES accounts(id) ON DELETE SET NULL,
    monthly_contribution numeric(14,2),
    target_date          date,
    archived             boolean NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now()
);
