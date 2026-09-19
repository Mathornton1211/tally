-- Three things that all needed a table.

-- 1. GOALS. Migration 006 already had savings goals tied to an account. What
--    was missing is the one people actually ask for -- "am I on track for $X
--    net worth by 2032" -- which is not about an account balance at all but
--    about the whole picture and its trajectory. Extending the existing table
--    rather than adding a second one: two tables both called goals, differing
--    only in which page made them, is how an app ends up with two answers to
--    the same question.
ALTER TABLE goals DROP CONSTRAINT goals_kind_check;
ALTER TABLE goals ADD CONSTRAINT goals_kind_check
  CHECK (kind IN ('emergency', 'emergency_fund', 'savings', 'payoff', 'custom',
                  'net_worth', 'debt_free'));

-- An emergency fund is naturally expressed in months of spending, not a number:
-- the number it implies moves when your spending does, and a target that goes
-- stale the moment rent rises is worse than no target.
ALTER TABLE goals ADD COLUMN target_months numeric(5,2);
ALTER TABLE goals ADD COLUMN owner_id      integer REFERENCES people(id) ON DELETE CASCADE;
ALTER TABLE goals ADD COLUMN achieved_on   date;
ALTER TABLE goals ADD COLUMN note          text;

-- 2. SINKING FUNDS. A fund that only fills when somebody remembers to move
--    money is a fund that does not fill. These columns let it fill itself when
--    income lands, which is the entire difference between a savings plan that
--    works and a list of wishes.
ALTER TABLE funds ADD COLUMN auto_kind text
    CHECK (auto_kind IN ('per_paycheck', 'monthly', 'percent_of_income'));
ALTER TABLE funds ADD COLUMN auto_amount  numeric(14,2) CHECK (auto_amount > 0);
ALTER TABLE funds ADD COLUMN auto_percent numeric(6,3)  CHECK (auto_percent > 0 AND auto_percent <= 100);
-- The last income transaction (or month) this fund has already taken its cut
-- from. Without it, a second run on the same paycheck would fill twice.
ALTER TABLE funds ADD COLUMN auto_through date;

-- Contributions made automatically are marked so they can be told apart from,
-- and undone separately to, money somebody moved on purpose.
ALTER TABLE fund_contributions ADD COLUMN automatic boolean NOT NULL DEFAULT false;
ALTER TABLE fund_contributions DROP CONSTRAINT fund_contributions_source_check;
ALTER TABLE fund_contributions ADD CONSTRAINT fund_contributions_source_check
  CHECK (source IN ('manual', 'transaction', 'auto'));

-- 3. SHARE LINKS. An accountant needs last year's numbers, not a login.
--
--    A link is a bearer token: whoever holds it can read what it covers. So it
--    is deliberately narrow -- one date range, read-only, revocable, and with
--    an expiry that defaults to set rather than never. The token is stored
--    hashed, so a database dump does not hand over working links.
CREATE TABLE share_links (
    id            serial PRIMARY KEY,
    token_hash    text NOT NULL UNIQUE,
    label         text NOT NULL,
    start_date    date NOT NULL,
    end_date      date NOT NULL,
    -- What the holder may see. `summary` is totals and categories only;
    -- `transactions` adds the list itself.
    detail        text NOT NULL DEFAULT 'summary' CHECK (detail IN ('summary', 'transactions')),
    expires_on    date,
    revoked       boolean NOT NULL DEFAULT false,
    created_by    integer REFERENCES people(id) ON DELETE SET NULL,
    -- A share link sees exactly what its creator could see when they made it.
    -- Storing that rather than resolving it live means adding a private account
    -- later does not silently widen a link somebody already handed out.
    as_person     integer REFERENCES people(id) ON DELETE CASCADE,
    views         integer NOT NULL DEFAULT 0,
    last_viewed_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX share_links_live_idx ON share_links (token_hash) WHERE NOT revoked;
