-- Friendly categories on top of Plaid's personal_finance_category.
--
-- kind decides what a transaction counts toward, and gets exactly one answer:
--   expense   spending totals, budgets, category charts
--   income    income totals
--   transfer  neither. Card payments and savings moves are money changing
--             pockets; counting them as spending double-counts every card purchase.

CREATE TABLE categories (
    key    text PRIMARY KEY,
    label  text NOT NULL,
    kind   text NOT NULL CHECK (kind IN ('expense', 'income', 'transfer')),
    icon   text NOT NULL,          -- Phosphor icon name, rendered by the web app
    sort   integer NOT NULL
);

INSERT INTO categories (key, label, kind, icon, sort) VALUES
  ('rent',           'Rent & mortgage',     'expense',  'House',             10),
  ('bills',          'Bills & utilities',   'expense',  'Lightning',         20),
  ('groceries',      'Groceries',           'expense',  'ShoppingCart',      30),
  ('dining',         'Dining & drinks',     'expense',  'ForkKnife',         40),
  ('auto',           'Auto & transport',    'expense',  'Car',               50),
  ('shopping',       'Shopping',            'expense',  'ShoppingBag',       60),
  ('entertainment',  'Entertainment',       'expense',  'FilmSlate',         70),
  ('travel',         'Travel',              'expense',  'AirplaneTilt',      80),
  ('health',         'Health & fitness',    'expense',  'Heartbeat',         90),
  ('home',           'Home',                'expense',  'Wrench',           100),
  ('insurance',      'Insurance',           'expense',  'ShieldCheck',      110),
  ('services',       'Services',            'expense',  'Briefcase',        120),
  ('loans',          'Loan payments',       'expense',  'Bank',             130),
  ('fees',           'Fees & interest',     'expense',  'Warning',          140),
  ('giving',         'Taxes & giving',      'expense',  'HandHeart',        150),
  ('other',          'Other',               'expense',  'DotsThree',        160),
  ('income',         'Income',              'income',   'Money',            200),
  ('interest',       'Interest earned',     'income',   'TrendUp',          210),
  ('card_payment',   'Credit card payment', 'transfer', 'CreditCard',       300),
  ('transfer',       'Transfer',            'transfer', 'ArrowsLeftRight',  310);

CREATE FUNCTION tally_default_category(primary_cat text, detailed text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN detailed = 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT'        THEN 'card_payment'
    WHEN detailed = 'INCOME_INTEREST_EARNED'                   THEN 'interest'
    WHEN primary_cat = 'INCOME'                                THEN 'income'
    WHEN primary_cat IN ('TRANSFER_IN', 'TRANSFER_OUT')        THEN 'transfer'
    WHEN detailed IN ('RENT_AND_UTILITIES_RENT',
                      'LOAN_PAYMENTS_MORTGAGE_PAYMENT')        THEN 'rent'
    WHEN primary_cat = 'RENT_AND_UTILITIES'                    THEN 'bills'
    WHEN detailed = 'FOOD_AND_DRINK_GROCERIES'                 THEN 'groceries'
    WHEN primary_cat = 'FOOD_AND_DRINK'                        THEN 'dining'
    WHEN primary_cat = 'TRANSPORTATION'                        THEN 'auto'
    WHEN primary_cat = 'TRAVEL'                                THEN 'travel'
    WHEN primary_cat = 'GENERAL_MERCHANDISE'                   THEN 'shopping'
    WHEN primary_cat = 'ENTERTAINMENT'                         THEN 'entertainment'
    WHEN detailed = 'PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS'   THEN 'health'
    WHEN primary_cat IN ('MEDICAL', 'PERSONAL_CARE')           THEN 'health'
    WHEN primary_cat = 'HOME_IMPROVEMENT'                      THEN 'home'
    WHEN detailed = 'GENERAL_SERVICES_INSURANCE'               THEN 'insurance'
    WHEN primary_cat = 'GENERAL_SERVICES'                      THEN 'services'
    WHEN primary_cat = 'LOAN_PAYMENTS'                         THEN 'loans'
    WHEN primary_cat = 'BANK_FEES'                             THEN 'fees'
    WHEN primary_cat = 'GOVERNMENT_AND_NON_PROFIT'             THEN 'giving'
    ELSE 'other'
  END
$$;

-- Phase 1 reserved an integer category_id that nothing wrote. Replace it with
-- a key: the user's override, NULL meaning "use the default".
ALTER TABLE transactions DROP COLUMN category_id;
ALTER TABLE transactions ADD COLUMN category text REFERENCES categories(key);

-- Everything the UI and analytics read goes through this view.
-- spend: positive = money spent, negative = a refund. Only for expense rows.
CREATE VIEW v_txn AS
SELECT t.id, t.date, t.amount, t.pending, t.name, t.merchant_name, t.merchant_entity_id,
       t.logo_url, t.website, t.payment_channel, t.note, t.pfc_primary, t.pfc_detailed,
       t.account_id, a.name AS account_name, a.mask AS account_mask, a.type AS account_type,
       inst.name AS institution, i.id AS item_id,
       COALESCE(t.category, tally_default_category(t.pfc_primary, t.pfc_detailed)) AS category,
       (t.category IS NOT NULL) AS category_overridden,
       c.label AS category_label, c.kind, c.icon AS category_icon,
       COALESCE(t.merchant_name,
                initcap(regexp_replace(t.name, '\s+(#?\d[\d\-]*.*|PPD ID.*|X{3,}\d*)$', ''))) AS display_name,
       CASE WHEN c.kind = 'expense' THEN t.amount ELSE 0 END AS spend,
       CASE WHEN c.kind = 'income'  THEN -t.amount ELSE 0 END AS income
FROM transactions t
JOIN accounts a ON a.id = t.account_id
JOIN items i ON i.id = a.item_id
LEFT JOIN institutions inst ON inst.id = i.institution_id
JOIN categories c ON c.key = COALESCE(t.category, tally_default_category(t.pfc_primary, t.pfc_detailed))
WHERE NOT a.hidden;
