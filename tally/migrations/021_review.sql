-- A reason to open this on a Tuesday.
--
-- Everything built so far is somewhere you GO and LOOK AT. Nothing asks
-- anything of you, and three things rot quietly as a result: categories drift
-- wrong and nobody corrects them, new merchants stay as AMZN MKTP US*2K4XY
-- forever, and the features that need a human -- a split, a tag, counting a
-- purchase toward a fund -- only happen if somebody goes hunting for the
-- transaction.
--
-- The fix is a queue with an end. Not "here is everything", which is the
-- transactions page and nobody reviews it; a short list of the charges that
-- actually need a decision, which empties.
--
-- Reviewing is explicit, and ANY edit counts as one. Correcting a category and
-- then having to also click "reviewed" is the kind of double work that makes
-- people stop.

ALTER TABLE transactions ADD COLUMN reviewed_at timestamptz;
ALTER TABLE transactions ADD COLUMN reviewed_by integer REFERENCES people(id) ON DELETE SET NULL;

-- The queue reads this constantly and it is almost always a small slice of a
-- large table.
CREATE INDEX transactions_unreviewed_idx ON transactions (date DESC)
  WHERE reviewed_at IS NULL AND NOT is_split_parent;

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
         round(k.amount * tally_rate(k.currency, k.date), 2) AS home_amount
  FROM keyed k
), ruled AS (
  SELECT t.*, rule.id AS rule_id, rule.name AS rule_name, rule.set_category AS rule_category,
         rule.set_name AS rule_name_override, rule.add_tags AS rule_tags, rule.set_note AS rule_note
  FROM converted t
  LEFT JOIN LATERAL (
      SELECT r.id, r.name, r.set_category, r.set_name, r.add_tags, r.set_note
      FROM rules r
      WHERE r.enabled
        AND tally_can_see(r.owner_id)
        AND tally_rule_match(r.pattern, r.match_type,
              CASE r.match_field WHEN 'bank_text'    THEN t.bank_text
                                 WHEN 'merchant_key' THEN t.merchant_key
                                 ELSE t.display_name END)
        AND (r.min_amount  IS NULL OR abs(t.home_amount) >= r.min_amount)
        AND (r.max_amount  IS NULL OR abs(t.home_amount) <= r.max_amount)
        AND (r.account_id  IS NULL OR r.account_id = t.account_id)
      ORDER BY r.priority DESC, r.id
      LIMIT 1
  ) rule ON true
)
SELECT t.id, t.date, t.pending, t.name, t.merchant_name, t.merchant_entity_id,
       t.logo_url, t.website, t.payment_channel, t.pfc_primary, t.pfc_detailed, t.pfc_confidence,
       t.location, t.bank_text, t.parent_id, t.source,
       t.reviewed_at, (t.reviewed_at IS NOT NULL) AS reviewed,
       t.home_amount AS amount, t.amount AS original_amount, t.currency, t.fx,
       (t.currency <> tally_home_currency()) AS foreign_currency,
       t.account_id, a.name AS account_name, a.mask AS account_mask, t.account_type,
       a.owner_id, p.name AS owner_name, p.color AS owner_color,
       COALESCE(inst.name, a.institution_name) AS institution, i.id AS item_id,
       -- A rule can rename, but a name the person typed themselves still wins.
       CASE WHEN t.alias_source = 'user' THEN t.display_name
            ELSE COALESCE(t.rule_name_override, t.display_name) END AS display_name,
       lower(CASE WHEN t.alias_source = 'user' THEN t.display_name
                  ELSE COALESCE(t.rule_name_override, t.display_name) END) AS merchant_key,
       COALESCE(t.note, t.rule_note) AS note,
       -- Hand-applied tags and rule tags, deduplicated, order stable.
       ARRAY(SELECT DISTINCT unnest(t.tags || t.rule_tags) ORDER BY 1) AS tags,
       t.rule_id, t.rule_name,
       c.key AS category,
       (t.category IS NOT NULL) AS category_overridden,
       (t.category IS NULL AND COALESCE(t.rule_category, r.category) IS NOT NULL) AS category_from_rule,
       CASE WHEN t.parent_id IS NOT NULL THEN 'split'
            WHEN t.category IS NOT NULL THEN 'user'
            WHEN t.rule_category IS NOT NULL THEN 'rule'
            WHEN r.category IS NOT NULL THEN 'rule'
            WHEN t.category_fixed IS NOT NULL THEN 'tally'
            WHEN t.category_ai IS NOT NULL THEN 'ai'
            ELSE 'plaid' END AS category_source,
       c.label AS category_label, c.kind, c.icon AS category_icon, c.essential,
       CASE WHEN t.alias_source = 'user' THEN 'user'
            WHEN t.rule_name_override IS NOT NULL THEN 'rule'
            WHEN t.merchant_name IS NOT NULL THEN 'plaid'
            ELSE COALESCE(t.alias_source, 'bank') END AS name_source,
       CASE WHEN c.kind = 'expense' THEN t.home_amount ELSE 0 END AS spend,
       CASE WHEN c.kind = 'income'  THEN -t.home_amount ELSE 0 END AS income
FROM ruled t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN people p ON p.id = a.owner_id
LEFT JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, t.rule_category, r.category, t.category_fixed,
                                      t.category_ai,
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
       currency, tags
FROM v_txn;

GRANT SELECT ON chat_transactions TO tally_reader;
