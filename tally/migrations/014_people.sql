-- Households: more than one person, and money that is not all shared.
--
-- The model is deliberately small. An account is either the household's or one
-- person's, and that is the only ownership fact in the system -- transactions,
-- balances and every chart inherit it from the account they belong to. There is
-- no per-transaction ownership, because nobody wants to tag groceries.
--
-- The privacy rule: an account with an owner is visible to that person ALONE.
-- Not to the household's admin either. A "private, except from whoever set up
-- the server" account is not private, and offering it would be a lie that a
-- couple only discovers after they have relied on it.
--
-- Everything filters through tally_can_see(), which reads a per-request
-- setting. Queries that were written before any of this existed keep working
-- unchanged, and a request with no viewer set -- the sync worker, a
-- single-person install -- sees everything, which is what both need.

CREATE TABLE people (
    id            serial PRIMARY KEY,
    name          text NOT NULL,
    username      text NOT NULL UNIQUE,
    password_hash text,
    -- owner manages people and connections; member uses the app; viewer cannot
    -- change anything. Note that owner does NOT mean "sees everything".
    role          text NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member', 'viewer')),
    color         text NOT NULL DEFAULT 'series-1',
    last_seen_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- NULL owner = the household's. Restrict rather than cascade: removing a person
-- must be an explicit decision about their accounts, not a silent deletion of
-- somebody's bank history or a silent promotion of it to shared.
ALTER TABLE accounts ADD COLUMN owner_id integer REFERENCES people(id) ON DELETE RESTRICT;
CREATE INDEX accounts_owner_idx ON accounts (owner_id);

CREATE FUNCTION tally_viewer() RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('tally.viewer', true), '')::integer
$$;

CREATE FUNCTION tally_can_see(owner integer) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT owner IS NULL              -- the household's
      OR tally_viewer() IS NULL     -- nobody is asking: worker, or a one-person install
      OR owner = tally_viewer()
$$;

-- Funds and budgets can belong to one person too: a shared holiday fund and
-- somebody's own guitar fund are both normal, and so is "our groceries budget,
-- my spending money".
ALTER TABLE funds ADD COLUMN owner_id integer REFERENCES people(id) ON DELETE CASCADE;

ALTER TABLE budgets DROP CONSTRAINT budgets_pkey;
ALTER TABLE budgets ADD COLUMN owner_id integer REFERENCES people(id) ON DELETE CASCADE;
ALTER TABLE budgets ADD COLUMN id bigserial PRIMARY KEY;
-- COALESCE because a NULL owner has to collide with other NULL owners, and a
-- plain unique index would let one category be budgeted twice for the household.
CREATE UNIQUE INDEX budgets_one_per_month ON budgets (category, month, COALESCE(owner_id, 0));

-- v_txn gains the visibility filter. Every page, chart, export and alert reads
-- through it, so this one line is the whole enforcement surface.
DROP VIEW chat_transactions;
DROP VIEW v_category_months;
DROP VIEW v_txn_any;
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
         CASE WHEN a.type IN ('credit', 'loan') AND n.amount < 0
                   AND n.bank_text ~* 'PAYMENT|THANK YOU|AUTOPAY'
              THEN 'card_payment' END AS category_fixed
  FROM named n JOIN accounts a ON a.id = n.account_id
)
SELECT t.id, t.date, t.amount, t.pending, t.name, t.merchant_name, t.merchant_entity_id,
       t.logo_url, t.website, t.payment_channel, t.note, t.pfc_primary, t.pfc_detailed, t.pfc_confidence,
       t.location, t.merchant_key, t.bank_text, t.parent_id, t.source,
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
       CASE WHEN c.kind = 'expense' THEN t.amount ELSE 0 END AS spend,
       CASE WHEN c.kind = 'income'  THEN -t.amount ELSE 0 END AS income
FROM keyed t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN people p ON p.id = a.owner_id
LEFT JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, r.category, t.category_fixed, t.category_ai,
                                      tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden AND tally_can_see(a.owner_id);

CREATE VIEW v_txn_any AS
SELECT t.id, t.date, t.amount, t.name, t.merchant_name, t.logo_url, t.account_id,
       a.name AS account_name, a.mask AS account_mask, t.is_split_parent,
       COALESCE(t.merchant_name, initcap(regexp_replace(t.name, '\s+(#?\d[\d\-]*.*|PPD ID.*)$', ''))) AS display_name,
       COALESCE(NULLIF(t.raw->>'original_description', ''), t.name) AS bank_text
FROM transactions t JOIN accounts a ON a.id = t.account_id
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
       category, category_label, kind, essential, account_name, account_mask, account_type, institution
FROM v_txn;

GRANT SELECT ON chat_transactions TO tally_reader;
