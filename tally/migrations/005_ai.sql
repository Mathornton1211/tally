-- Local AI: merchant names, low-confidence categories, digests, chat.
-- HANDOFF section 10. All inference is the lab's own ollama; invariant 2.

-- Bank text reduced to what identifies the payee: no digits, store numbers,
-- or reference codes. "VENMO PAYMENT 1043997712" and "VENMO PAYMENT 88812"
-- share one key, so one cleaned name covers both.
CREATE FUNCTION tally_raw_key(bank_text text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT btrim(regexp_replace(regexp_replace(lower(coalesce(bank_text, '')), '[0-9#*:]+', ' ', 'g'), '\s+', ' ', 'g'))
$$;

CREATE TABLE merchant_aliases (
    raw_key     text PRIMARY KEY,
    clean_name  text NOT NULL,
    source      text NOT NULL CHECK (source IN ('llm', 'user')),
    model       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- The model's category, kept apart from the user's own edit (`category`) so a
-- correction always wins and the UI can say who decided.
ALTER TABLE transactions ADD COLUMN category_ai text REFERENCES categories(key);
ALTER TABLE transactions ADD COLUMN category_ai_model text;

CREATE TABLE ai_calls (
    id             bigserial PRIMARY KEY,
    task           text NOT NULL,
    model          text NOT NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    ms             integer,
    load_ms        integer,
    prompt_tokens  integer,
    eval_tokens    integer,
    ok             boolean NOT NULL,
    error          text
);
CREATE INDEX ai_calls_started_idx ON ai_calls (started_at DESC);

CREATE TABLE digests (
    month       date PRIMARY KEY,           -- first day of the month summarised
    facts       jsonb NOT NULL,
    headline    text NOT NULL,
    body        text NOT NULL,
    verified    boolean NOT NULL,           -- every dollar figure traced back to facts
    model       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chat_log (
    id          bigserial PRIMARY KEY,
    question    text NOT NULL,
    sql         text,
    row_count   integer,
    answer      text,
    verified    boolean,
    ms          integer,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

DROP VIEW v_txn;
CREATE VIEW v_txn AS
WITH base AS (
  SELECT t.*,
         COALESCE(NULLIF(t.raw->>'original_description', ''), t.name) AS bank_text,
         ma.clean_name AS alias_name, ma.source AS alias_source
  FROM transactions t
  LEFT JOIN merchant_aliases ma
       ON ma.raw_key = tally_raw_key(COALESCE(NULLIF(t.raw->>'original_description', ''), t.name))
      -- the user's own rename beats Plaid; the model's guess only fills gaps Plaid left.
      AND (ma.source = 'user' OR t.merchant_name IS NULL)
), named AS (
  SELECT b.*,
         COALESCE(CASE WHEN b.alias_source = 'user' THEN b.alias_name END, b.merchant_name, b.alias_name,
                  initcap(regexp_replace(b.name, '\s+(#?\d[\d\-]*.*|PPD ID.*|X{3,}\d*)$', ''))) AS display_name
  FROM base b
), keyed AS (
  SELECT n.*, lower(n.display_name) AS merchant_key, a.type AS account_type,
         -- A credit landing on a card that says PAYMENT is the card being paid,
         -- whatever Plaid guessed. Left unfixed it shows up as income.
         CASE WHEN a.type IN ('credit', 'loan') AND n.amount < 0
                   AND n.bank_text ~* 'PAYMENT|THANK YOU|AUTOPAY'
              THEN 'card_payment' END AS category_fixed
  FROM named n JOIN accounts a ON a.id = n.account_id
)
SELECT t.id, t.date, t.amount, t.pending, t.name, t.merchant_name, t.merchant_entity_id,
       t.logo_url, t.website, t.payment_channel, t.note, t.pfc_primary, t.pfc_detailed, t.pfc_confidence,
       t.location, t.merchant_key, t.bank_text,
       t.account_id, a.name AS account_name, a.mask AS account_mask, t.account_type,
       inst.name AS institution, i.id AS item_id,
       c.key AS category,
       (t.category IS NOT NULL) AS category_overridden,
       (t.category IS NULL AND r.category IS NOT NULL) AS category_from_rule,
       CASE WHEN t.category IS NOT NULL THEN 'user'
            WHEN r.category IS NOT NULL THEN 'rule'
            WHEN t.category_fixed IS NOT NULL THEN 'tally'
            WHEN t.category_ai IS NOT NULL THEN 'ai'
            ELSE 'plaid' END AS category_source,
       c.label AS category_label, c.kind, c.icon AS category_icon,
       t.display_name,
       CASE WHEN t.alias_source = 'user' THEN 'user' WHEN t.merchant_name IS NOT NULL THEN 'plaid'
            ELSE COALESCE(t.alias_source, 'bank') END AS name_source,
       CASE WHEN c.kind = 'expense' THEN t.amount ELSE 0 END AS spend,
       CASE WHEN c.kind = 'income'  THEN -t.amount ELSE 0 END AS income
FROM keyed t
JOIN accounts a ON a.id = t.account_id
JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, r.category, t.category_fixed, t.category_ai,
                                      tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden;

-- Chat runs its generated SQL as this role, inside a read-only transaction
-- with a statement timeout (invariant 4). It can see two views and nothing else:
-- no tokens, no settings, no ability to write.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tally_reader') THEN
    CREATE ROLE tally_reader NOLOGIN;
  END IF;
END $$;

CREATE VIEW chat_transactions AS
SELECT date, amount AS plaid_amount, spend, income, pending, display_name AS merchant, bank_text AS description,
       category, category_label, kind, account_name, account_mask, account_type, institution
FROM v_txn;

CREATE VIEW chat_accounts AS
SELECT a.name AS account_name, a.mask AS account_mask, a.type AS account_type, a.subtype,
       a.current_balance, a.available_balance, a.credit_limit, inst.name AS institution
FROM accounts a JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
WHERE NOT a.hidden;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM tally_reader;
GRANT USAGE ON SCHEMA public TO tally_reader;
GRANT SELECT ON chat_transactions, chat_accounts, categories TO tally_reader;
