-- Deleting a transaction is the one irreversible thing sync does.
--
-- Plaid's /transactions/sync returns a `removed` list, and until now Tally
-- obeyed it without question: DELETE FROM transactions WHERE id = ANY(...).
-- For a charge reversed last week that is exactly right -- it did not happen
-- and should not be in any total.
--
-- For something old it is a different proposition. Plaid serves roughly 24
-- months; past that, Tally is the ONLY copy. A removal instruction for a
-- transaction from twenty months ago would destroy history that cannot be
-- re-fetched from anywhere, and the app would do it silently, on one line of
-- JSON, with nobody watching.
--
-- So: every removal is archived before anything happens, and a removal for
-- something old is recorded rather than obeyed. The bias is deliberate. A
-- wrongly-kept transaction is a visible discrepancy somebody can fix; a
-- wrongly-deleted one is gone.

CREATE TABLE removed_transactions (
    id           text PRIMARY KEY,
    account_id   text,
    occurred_on  date,
    amount       numeric(14,2),
    name         text,
    -- The whole row as it was, so putting it back is possible rather than
    -- theoretical.
    row          jsonb NOT NULL,
    removed_at   timestamptz NOT NULL DEFAULT now(),
    -- How old the transaction was when Plaid asked. The number the decision
    -- was made on, kept so the decision can be argued with later.
    age_days     integer,
    -- true  = deleted, and this is the copy
    -- false = kept, because it was too old to delete on a single instruction
    obeyed       boolean NOT NULL
);

CREATE INDEX removed_transactions_recent_idx ON removed_transactions (removed_at DESC);

-- Set when a removal was refused. The transaction stays in every total, and
-- this is the flag that says Plaid disagrees -- so a discrepancy against a
-- bank statement has an explanation rather than being a mystery.
ALTER TABLE transactions ADD COLUMN removal_withheld_at timestamptz;
