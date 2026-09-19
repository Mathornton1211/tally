-- One filtered way to read an account.
--
-- Migration 014 put the privacy rule in v_txn, which covers every transaction,
-- total and chart. It did not cover the dozen places that read the `accounts`
-- table directly for balances -- net worth, the debt list, fees, investments,
-- the assistant's account summary. Those would have shown a partner's private
-- balance while correctly hiding every transaction in it.
--
-- The fix is not to remember the filter in twenty queries. It is to make the
-- filtered read the easy one and give it the obvious name, so the next query
-- somebody writes is right by default.
--
--   v_acct      what a person may see. Every read path uses this.
--   accounts    the raw table. Sync writes it; the household admin screen reads
--               it to assign ownership, which has to see accounts before the
--               rule applies to them.

DROP VIEW v_account;

CREATE VIEW v_acct AS
SELECT a.*,
       COALESCE(a.iso_currency, tally_home_currency()) AS currency,
       tally_rate(COALESCE(a.iso_currency, tally_home_currency()), current_date) AS fx,
       round(a.current_balance * tally_rate(COALESCE(a.iso_currency, tally_home_currency()), current_date), 2)
         AS home_balance,
       (COALESCE(a.iso_currency, tally_home_currency()) <> tally_home_currency()) AS foreign_currency,
       p.name  AS owner_name,
       p.color AS owner_color
FROM accounts a
LEFT JOIN people p ON p.id = a.owner_id
WHERE tally_can_see(a.owner_id);
