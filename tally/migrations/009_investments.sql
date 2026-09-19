-- Holdings and investment activity (brokerage, 401k, IRA).
--
-- Balances for these accounts already arrive with every sync; this is what is
-- inside them: which positions, what they cost, and what goes in each year.

CREATE TABLE securities (
    id              text PRIMARY KEY,          -- Plaid security_id
    ticker          text,
    name            text,
    type            text,                      -- equity | etf | mutual fund | cash | ...
    close_price     numeric(18,6),
    close_price_as_of date,
    iso_currency    text,
    is_cash_equivalent boolean,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE holdings (
    account_id      text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    security_id     text NOT NULL REFERENCES securities(id),
    quantity        numeric(20,8) NOT NULL,
    price           numeric(18,6),              -- institution_price
    price_as_of     date,
    value           numeric(16,2),              -- institution_value
    cost_basis      numeric(16,2),
    iso_currency    text,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, security_id)
);

CREATE TABLE investment_transactions (
    id            text PRIMARY KEY,
    account_id    text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    security_id   text REFERENCES securities(id),
    date          date NOT NULL,
    name          text,
    quantity      numeric(20,8),
    amount        numeric(16,2) NOT NULL,       -- positive = money into the account's holdings
    fees          numeric(16,2),
    type          text NOT NULL,                -- buy | sell | cash | fee | transfer
    subtype       text,                         -- contribution | dividend | ...
    iso_currency  text,
    raw           jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX invest_txn_date_idx ON investment_transactions (date DESC);
CREATE INDEX invest_txn_account_idx ON investment_transactions (account_id, date DESC);
