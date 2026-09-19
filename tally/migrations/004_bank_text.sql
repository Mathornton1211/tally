-- The bank's own wording, which Plaid's cleaned `name` loses. Fee and fraud
-- rules match on `bank_text`; it falls back to `name` for rows synced before
-- original descriptions were requested.
CREATE OR REPLACE VIEW v_txn AS
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
       CASE WHEN c.kind = 'income'  THEN -t.amount ELSE 0 END AS income,
       COALESCE(NULLIF(t.raw->>'original_description', ''), t.name) AS bank_text
FROM base t
JOIN accounts a ON a.id = t.account_id
JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
LEFT JOIN category_rules r ON r.merchant_key = t.merchant_key
JOIN categories c ON c.key = COALESCE(t.category, r.category,
                                      tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden;
