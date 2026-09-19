-- Budgets: a monthly target per category.
--
-- Two decisions worth writing down, because they are what separate a budget
-- that survives contact with a real month from Mint's red bar.
--
-- 1. A budget row is the amount that starts applying in that month and keeps
--    applying until another row replaces it. "Set groceries to $600" writes one
--    row; "but $900 in December" writes a second. A year of budgets is a
--    handful of rows, not 12 x 16, and history stays truthful: changing next
--    month's number never rewrites what last month was judged against.
--
-- 2. Rollover is per category. Off, every month starts at the full amount --
--    the way Mint worked, and the way most people think about "I spend $400 on
--    groceries." On, what is left over (or overspent) carries into the next
--    month -- the envelope method. Neither is correct for everybody, and the
--    same person wants both: fixed for groceries, rolling for car repairs.

CREATE TABLE budgets (
    category   text NOT NULL REFERENCES categories(key) ON DELETE CASCADE,
    -- Always the 1st. The month this amount starts applying from.
    month      date NOT NULL CHECK (month = date_trunc('month', month)::date),
    amount     numeric(14,2) NOT NULL CHECK (amount >= 0),
    rollover   boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (category, month)
);

CREATE INDEX budgets_month_idx ON budgets (month);

-- Spending per category per month, which both the budget page and the rollover
-- arithmetic read. Transfers and income are already excluded by v_txn's kind.
CREATE VIEW v_category_months AS
SELECT date_trunc('month', date)::date AS month,
       category,
       sum(spend)  AS spent,
       count(*)    AS transactions
FROM v_txn
WHERE kind = 'expense'
GROUP BY 1, 2;
