-- More than one currency.
--
-- Plaid already reports an account's currency; Tally has been ignoring it and
-- adding everything up as though it were dollars. That is fine until one
-- account is in EUR, at which point every total in the app is quietly wrong.
--
-- The rule: a transaction is stored in the currency it happened in, forever.
-- Converted amounts are computed for display against the household's home
-- currency and are never written back over the original. A rate that changes
-- next week must not retroactively change what last month's coffee cost.
--
-- Rates are whatever the household puts in. There is no call home to a rate
-- API: this app does not phone out, and a self-hosted finance tool that
-- silently depended on a third-party endpoint would be a worse trade than
-- typing in a number that changes a few times a year.

CREATE TABLE settings (
    key   text PRIMARY KEY,
    value text NOT NULL
);
INSERT INTO settings (key, value) VALUES ('home_currency', 'USD');

CREATE TABLE fx_rates (
    currency   text NOT NULL,          -- what you hold
    as_of      date NOT NULL,          -- the rate applies from this date on
    -- Units of the home currency that one unit of `currency` buys.
    -- 1 EUR = 1.08 USD -> rate 1.08 with home USD.
    rate       numeric(18,8) NOT NULL CHECK (rate > 0),
    source     text NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (currency, as_of)
);

-- SECURITY DEFINER because v_txn is also read by the tally_reader role that
-- the AI assistant queries under, and that role deliberately cannot read
-- tables. It can see the home currency -- a three-letter code -- without being
-- handed the settings table.
CREATE FUNCTION tally_home_currency() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT value FROM settings WHERE key = 'home_currency'
$$;

-- The rate in force for a currency on a date: the most recent one at or before
-- it. An unknown currency converts at 1, which leaves the number visibly
-- unconverted rather than inventing a total -- the UI flags it.
CREATE FUNCTION tally_rate(cur text, on_date date) RETURNS numeric LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT CASE
    WHEN cur IS NULL OR cur = tally_home_currency() THEN 1
    ELSE COALESCE((SELECT r.rate FROM fx_rates r
                   WHERE r.currency = cur AND r.as_of <= on_date
                   ORDER BY r.as_of DESC LIMIT 1), 1)
  END
$$;

-- transactions.iso_currency already exists (migration 001) but has never been
-- read. Backfill the rows where sync left it null, from the payload or the
-- account, so a transaction always knows the currency it happened in.
UPDATE transactions t
   SET iso_currency = COALESCE(NULLIF(t.raw->>'iso_currency_code', ''),
                               (SELECT a.iso_currency FROM accounts a WHERE a.id = t.account_id))
 WHERE t.iso_currency IS NULL;

DROP VIEW chat_transactions;
DROP VIEW v_category_months;
DROP VIEW v_txn;

CREATE VIEW v_txn AS
WITH base AS (
  SELECT t.*,
         COALESCE(NULLIF(t.raw->>'original_description', ''), t.name) AS bank_text,
         ma.clean_name AS alias_name, ma.source AS alias_source
  FROM transactions t
  LEFT JOIN merchant_aliases ma
       ON ma.raw_key = tally_raw_key(COALESCE(NULLIF(t.raw->>'original_description', ''), t.name))
      AND (ma.source = 'user' OR t.merchant_name IS NULL)
  WHERE NOT t.is_split_parent
), named AS (
  SELECT b.*,
         COALESCE(CASE WHEN b.alias_source = 'user' THEN b.alias_name END, b.merchant_name, b.alias_name,
                  initcap(regexp_replace(b.name, '\s+(#?\d[\d\-]*.*|PPD ID.*|X{3,}\d*)$', ''))) AS display_name
  FROM base b
), keyed AS (
  SELECT n.*, lower(n.display_name) AS merchant_key, a.type AS account_type,
         COALESCE(n.iso_currency, a.iso_currency, tally_home_currency()) AS currency,
         CASE WHEN a.type IN ('credit', 'loan') AND n.amount < 0
                   AND n.bank_text ~* 'PAYMENT|THANK YOU|AUTOPAY'
              THEN 'card_payment' END AS category_fixed
  FROM named n JOIN accounts a ON a.id = n.account_id
), converted AS (
  SELECT k.*,
         tally_rate(k.currency, k.date) AS fx,
         -- What every total in the app adds up. `original_amount` keeps the
         -- number the bank actually showed.
         round(k.amount * tally_rate(k.currency, k.date), 2) AS home_amount
  FROM keyed k
)
SELECT t.id, t.date, t.pending, t.name, t.merchant_name, t.merchant_entity_id,
       t.logo_url, t.website, t.payment_channel, t.note, t.pfc_primary, t.pfc_detailed, t.pfc_confidence,
       t.location, t.merchant_key, t.bank_text, t.parent_id, t.source,
       t.home_amount AS amount, t.amount AS original_amount, t.currency, t.fx,
       (t.currency <> tally_home_currency()) AS foreign_currency,
       t.account_id, a.name AS account_name, a.mask AS account_mask, t.account_type,
       a.owner_id, p.name AS owner_name, p.color AS owner_color,
       COALESCE(inst.name, a.institution_name) AS institution, i.id AS item_id,
       c.key AS category,
       (t.category IS NOT NULL) AS category_overridden,
       (t.category IS NULL AND r.category IS NOT NULL) AS category_from_rule,
       CASE WHEN t.parent_id IS NOT NULL THEN 'split'
            WHEN t.category IS NOT NULL THEN 'user'
            WHEN r.category IS NOT NULL THEN 'rule'
            WHEN t.category_fixed IS NOT NULL THEN 'tally'
            WHEN t.category_ai IS NOT NULL THEN 'ai'
            ELSE 'plaid' END AS category_source,
       c.label AS category_label, c.kind, c.icon AS category_icon, c.essential,
       t.display_name,
       CASE WHEN t.alias_source = 'user' THEN 'user' WHEN t.merchant_name IS NOT NULL THEN 'plaid'
            ELSE COALESCE(t.alias_source, 'bank') END AS name_source,
       CASE WHEN c.kind = 'expense' THEN t.home_amount ELSE 0 END AS spend,
       CASE WHEN c.kind = 'income'  THEN -t.home_amount ELSE 0 END AS income
FROM converted t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN people p ON p.id = a.owner_id
LEFT JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, r.category, t.category_fixed, t.category_ai,
                                      tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden AND tally_can_see(a.owner_id);

CREATE VIEW v_category_months AS
SELECT date_trunc('month', date)::date AS month,
       category,
       sum(spend)  AS spent,
       count(*)    AS transactions
FROM v_txn
WHERE kind = 'expense'
GROUP BY 1, 2;

CREATE VIEW chat_transactions AS
SELECT date, amount AS plaid_amount, spend, income, pending, display_name AS merchant, bank_text AS description,
       category, category_label, kind, essential, account_name, account_mask, account_type, institution,
       currency
FROM v_txn;

GRANT SELECT ON chat_transactions TO tally_reader;

-- Balances convert on read too, at today's rate, since a balance is a
-- right-now number rather than a historical one.
CREATE VIEW v_account AS
SELECT a.*,
       COALESCE(a.iso_currency, tally_home_currency()) AS currency,
       tally_rate(COALESCE(a.iso_currency, tally_home_currency()), current_date) AS fx,
       round(a.current_balance * tally_rate(COALESCE(a.iso_currency, tally_home_currency()), current_date), 2)
         AS home_balance,
       (COALESCE(a.iso_currency, tally_home_currency()) <> tally_home_currency()) AS foreign_currency
FROM accounts a;
