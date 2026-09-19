-- Phase 1: connections, accounts, transactions, sync bookkeeping.
--
-- Amount sign follows Plaid and is never flipped on the way in:
--   amount > 0  money LEAVING the account (purchase, fee, payment out)
--   amount < 0  money ENTERING the account (deposit, refund, credit)
-- Flipping for display happens in views and the UI, once, not scattered.

CREATE TABLE institutions (
    id            text PRIMARY KEY,          -- Plaid institution_id
    name          text NOT NULL,
    url           text,
    primary_color text,
    oauth         boolean
);

CREATE TABLE items (
    id                 serial PRIMARY KEY,
    plaid_item_id      text NOT NULL UNIQUE,
    institution_id     text REFERENCES institutions(id),
    access_token_enc   bytea NOT NULL,       -- Fernet, key is NOT in this database
    cursor             text,
    -- ok | login_required | error | disconnected
    status             text NOT NULL DEFAULT 'ok',
    error_code         text,
    error_message      text,
    -- Plaid transactions_update_status: NOT_READY | INITIAL_UPDATE_COMPLETE | HISTORICAL_UPDATE_COMPLETE
    update_status      text,
    products           text[] NOT NULL DEFAULT '{}',
    last_synced_at     timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE accounts (
    id                text PRIMARY KEY,      -- Plaid account_id
    item_id           integer NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    name              text NOT NULL,
    official_name     text,
    mask              text,
    type              text NOT NULL,         -- depository | credit | loan | investment | other
    subtype           text,
    current_balance   numeric(14,2),
    available_balance numeric(14,2),
    credit_limit      numeric(14,2),
    iso_currency      text,
    hidden            boolean NOT NULL DEFAULT false,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- One row per account per day, the last sync of the day wins. Net worth over
-- time is built from this, so it only has history from the day it was linked.
CREATE TABLE balances_daily (
    account_id        text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    day               date NOT NULL,
    current_balance   numeric(14,2),
    available_balance numeric(14,2),
    credit_limit      numeric(14,2),
    PRIMARY KEY (account_id, day)
);

CREATE TABLE transactions (
    id                     text PRIMARY KEY, -- Plaid transaction_id
    account_id             text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    amount                 numeric(14,2) NOT NULL,
    iso_currency           text,
    date                   date NOT NULL,
    authorized_date        date,
    authorized_datetime    timestamptz,
    name                   text NOT NULL,
    merchant_name          text,
    merchant_entity_id     text,
    logo_url               text,
    website                text,
    payment_channel        text,
    pending                boolean NOT NULL DEFAULT false,
    pending_transaction_id text,
    pfc_primary            text,
    pfc_detailed           text,
    pfc_confidence         text,
    location               jsonb,
    counterparties         jsonb,
    raw                    jsonb NOT NULL,
    -- Filled by categorization (phase 4). Source: plaid | rule | llm | user.
    category_id            integer,
    category_source        text,
    note                   text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX transactions_date_idx     ON transactions (date DESC);
CREATE INDEX transactions_account_idx  ON transactions (account_id, date DESC);
CREATE INDEX transactions_merchant_idx ON transactions (merchant_name);
CREATE INDEX transactions_pfc_idx      ON transactions (pfc_primary, pfc_detailed);

CREATE TABLE sync_runs (
    id          bigserial PRIMARY KEY,
    item_id     integer NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    added       integer NOT NULL DEFAULT 0,
    modified    integer NOT NULL DEFAULT 0,
    removed     integer NOT NULL DEFAULT 0,
    pages       integer NOT NULL DEFAULT 0,
    ok          boolean,
    error       text
);
