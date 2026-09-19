-- Funds: saving up for a specific thing.
--
-- A 3D printer, truck tires, a set of lights. Different from a savings goal in
-- one way that matters: a $50 gift card and $200 of store credit are real money
-- toward THIS purchase and worthless toward anything else, so they belong to
-- the fund rather than to net worth.

CREATE TABLE funds (
    id            serial PRIMARY KEY,
    name          text NOT NULL,
    target_amount numeric(14,2) NOT NULL CHECK (target_amount > 0),
    target_date   date,
    note          text,
    icon          text NOT NULL DEFAULT 'ShoppingBag',
    priority      integer NOT NULL DEFAULT 0,       -- higher first
    bought_on     date,                             -- set when it is actually bought
    archived      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Money already in hand for this fund that is not cash in an account.
-- A gift card can expire, which is a deadline worth a warning.
CREATE TABLE fund_credits (
    id          serial PRIMARY KEY,
    fund_id     integer NOT NULL REFERENCES funds(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('gift_card', 'store_credit', 'rebate', 'trade_in', 'other')),
    label       text NOT NULL,                      -- "Home Depot gift card", "Amazon credit"
    amount      numeric(14,2) NOT NULL CHECK (amount > 0),
    used        numeric(14,2) NOT NULL DEFAULT 0,
    merchant    text,
    expires_on  date,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX fund_credits_expiry_idx ON fund_credits (expires_on) WHERE expires_on IS NOT NULL;

-- Cash put aside for it, by hand or by pointing at a transaction.
CREATE TABLE fund_contributions (
    id             serial PRIMARY KEY,
    fund_id        integer NOT NULL REFERENCES funds(id) ON DELETE CASCADE,
    date           date NOT NULL DEFAULT current_date,
    amount         numeric(14,2) NOT NULL,          -- negative to correct a mistake
    source         text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'transaction')),
    transaction_id text REFERENCES transactions(id) ON DELETE SET NULL,
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Purchases charged against the fund, so "spent so far" is real transactions
-- rather than a number someone remembered to update.
CREATE TABLE fund_spends (
    fund_id        integer NOT NULL REFERENCES funds(id) ON DELETE CASCADE,
    transaction_id text NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fund_id, transaction_id)
);
