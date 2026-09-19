-- Three things Plaid cannot give us: accounts it cannot see, one charge that
-- was really two purchases, and which categories are essentials.

-- 1. Manual accounts: cash, a card that will not link, a loan from a friend,
--    a car. They belong to no Plaid Item, so item_id becomes optional.
ALTER TABLE accounts ALTER COLUMN item_id DROP NOT NULL;
ALTER TABLE accounts ADD COLUMN source text NOT NULL DEFAULT 'plaid';
ALTER TABLE accounts ADD COLUMN institution_name text;   -- manual accounts only
ALTER TABLE accounts ADD CONSTRAINT accounts_source_ck
    CHECK (source IN ('plaid', 'manual'));
-- A Plaid account must have its Item; a manual one must not pretend to.
ALTER TABLE accounts ADD CONSTRAINT accounts_item_ck
    CHECK ((source = 'plaid' AND item_id IS NOT NULL) OR (source = 'manual' AND item_id IS NULL));

-- 2. Splits. A split becomes child rows that carry the categories, and the
--    parent is hidden from v_txn. Every total, chart and rule keeps working
--    without knowing splits exist, and un-splitting is deleting the children.
ALTER TABLE transactions ADD COLUMN parent_id text REFERENCES transactions(id) ON DELETE CASCADE;
ALTER TABLE transactions ADD COLUMN is_split_parent boolean NOT NULL DEFAULT false;
ALTER TABLE transactions ADD COLUMN source text NOT NULL DEFAULT 'plaid';
CREATE INDEX transactions_parent_idx ON transactions (parent_id) WHERE parent_id IS NOT NULL;

-- 3. Essentials. What can actually be cut this month is the question when
--    money is tight, and it is a property of the category.
ALTER TABLE categories ADD COLUMN essential boolean NOT NULL DEFAULT false;
UPDATE categories SET essential = true
 WHERE key IN ('rent', 'bills', 'groceries', 'insurance', 'health', 'loans', 'auto', 'fees');

DROP VIEW chat_transactions;
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
LEFT JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, r.category, t.category_fixed, t.category_ai,
                                      tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden;

-- Same rows plus split parents, for anything that needs to resolve a
-- transaction id that a receipt or an alert was attached to before it was split.
CREATE VIEW v_txn_any AS
SELECT t.id, t.date, t.amount, t.name, t.merchant_name, t.logo_url, t.account_id,
       a.name AS account_name, a.mask AS account_mask, t.is_split_parent,
       COALESCE(t.merchant_name, initcap(regexp_replace(t.name, '\s+(#?\d[\d\-]*.*|PPD ID.*)$', ''))) AS display_name,
       COALESCE(NULLIF(t.raw->>'original_description', ''), t.name) AS bank_text
FROM transactions t JOIN accounts a ON a.id = t.account_id
WHERE NOT a.hidden;

CREATE VIEW chat_transactions AS
SELECT date, amount AS plaid_amount, spend, income, pending, display_name AS merchant, bank_text AS description,
       category, category_label, kind, essential, account_name, account_mask, account_type, institution
FROM v_txn;

GRANT SELECT ON chat_transactions TO tally_reader;
