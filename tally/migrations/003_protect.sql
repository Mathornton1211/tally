-- Fees, alerts, per-account facts Plaid does not provide, and merchant rules.

-- Things only the owner knows about an account. Plaid has no APY, no foreign
-- transaction fee, no waiver rule. Every field is optional; insights that need
-- a missing one say so instead of guessing.
CREATE TABLE account_settings (
    account_id          text PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    apy                 numeric(6,3),   -- percent, e.g. 4.300
    apr                 numeric(6,3),   -- percent
    annual_fee          numeric(10,2),
    foreign_fee_pct     numeric(5,2),   -- percent, 0 means no FTF
    min_balance_waiver  numeric(12,2),  -- monthly fee waived at or above this balance
    reward_rate         numeric(5,2),   -- percent back, flat
    note                text,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- "Always call Vons groceries." Keyed on the lowercased merchant, which is
-- what the owner sees. A user edit on a single transaction still wins over a rule.
CREATE TABLE category_rules (
    merchant_key text PRIMARY KEY,
    category     text NOT NULL REFERENCES categories(key),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE alerts (
    id           bigserial PRIMARY KEY,
    -- Stable identity so a rescan never duplicates an alert the owner already handled.
    fingerprint  text NOT NULL UNIQUE,
    rule         text NOT NULL,
    severity     text NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    title        text NOT NULL,
    detail       text NOT NULL,
    inputs       jsonb NOT NULL,          -- what the rule saw, and its threshold
    txn_ids      text[] NOT NULL DEFAULT '{}',
    account_id   text REFERENCES accounts(id) ON DELETE CASCADE,
    merchant_key text,
    amount       numeric(14,2),
    occurred_on  date NOT NULL,
    status       text NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'expected', 'dismissed', 'fraud')),
    resolved_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX alerts_status_idx ON alerts (status, occurred_on DESC);

-- Marking an alert "expected" can teach a rule to stop firing for a merchant.
CREATE TABLE alert_trust (
    rule         text NOT NULL,
    merchant_key text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule, merchant_key)
);

-- Rebuild the view: category rules slot between a per-transaction edit and
-- Plaid's default, and every row carries its merchant_key.
DROP VIEW v_txn;
CREATE VIEW v_txn AS
WITH base AS (
  SELECT t.*, lower(COALESCE(t.merchant_name,
           regexp_replace(t.name, '\s+(#?\d[\d\-]*.*|PPD ID.*|X{3,}\d*)$', ''))) AS merchant_key
  FROM transactions t
)
SELECT t.id, t.date, t.amount, t.pending, t.name, t.merchant_name, t.merchant_entity_id,
       t.logo_url, t.website, t.payment_channel, t.note, t.pfc_primary, t.pfc_detailed,
       t.location, t.merchant_key,
       t.account_id, a.name AS account_name, a.mask AS account_mask, a.type AS account_type,
       inst.name AS institution, i.id AS item_id,
       c.key AS category,
       (t.category IS NOT NULL) AS category_overridden,
       (t.category IS NULL AND r.category IS NOT NULL) AS category_from_rule,
       c.label AS category_label, c.kind, c.icon AS category_icon,
       COALESCE(t.merchant_name,
                initcap(regexp_replace(t.name, '\s+(#?\d[\d\-]*.*|PPD ID.*|X{3,}\d*)$', ''))) AS display_name,
       CASE WHEN c.kind = 'expense' THEN t.amount ELSE 0 END AS spend,
       CASE WHEN c.kind = 'income'  THEN -t.amount ELSE 0 END AS income
FROM base t
JOIN accounts a ON a.id = t.account_id
JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, r.category,
                                      tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden;
