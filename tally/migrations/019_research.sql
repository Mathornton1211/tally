-- Findings that survive the session that found them.
--
-- Everything else in this app answers a question you just asked. This is the
-- part that keeps working while nobody is looking: the same rules run after
-- every sync, and what they find accumulates rather than being recomputed and
-- forgotten.
--
-- That persistence is the whole point. "Your Netflix went up $3" is worth
-- nothing on its own; "your Netflix has gone up three times since 2024, $84 a
-- year more than when you signed up" is worth a phone call, and only a table
-- can say the second one.
--
-- Three states and they mean different things:
--   open        still true, still worth doing something about
--   acted       you did something. It stops being raised even if it recurs,
--               until the underlying fact changes enough to earn a new one
--   dismissed   you decided it is not worth it. Never raised again
--   expired     it stopped being true on its own -- the price came back down,
--               the card was paid off. Kept as history rather than deleted,
--               because "this used to be a problem" is worth being able to see

CREATE TABLE findings (
    id            serial PRIMARY KEY,
    kind          text NOT NULL,
    -- Stable identity, so a rule that runs every six hours updates one row
    -- rather than making a new one forever.
    fingerprint   text NOT NULL UNIQUE,
    title         text NOT NULL,
    detail        text NOT NULL,
    -- What acting on it is worth over a year. The sort order, and the only
    -- number that makes a list of findings prioritisable.
    annual_saving numeric(14,2),
    -- certain        arithmetic on facts the bank reported
    -- likely         arithmetic plus a reasonable assumption, stated
    -- worth_checking a question Tally cannot answer from the data alone
    confidence    text NOT NULL DEFAULT 'likely'
                  CHECK (confidence IN ('certain', 'likely', 'worth_checking')),
    -- What the rule saw. Shown, so a wrong finding is arguable rather than
    -- mysterious, and so nothing has to be taken on faith.
    evidence      jsonb NOT NULL DEFAULT '{}',
    -- A script to actually do something with it, when there is one.
    action        text,
    account_id    text REFERENCES accounts(id) ON DELETE CASCADE,
    merchant_key  text,
    status        text NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'acted', 'dismissed', 'expired')),
    first_seen    date NOT NULL DEFAULT current_date,
    last_seen     date NOT NULL DEFAULT current_date,
    -- How many runs have agreed. A finding seen once might be noise; one seen
    -- every day for a month is a standing fact.
    times_seen    integer NOT NULL DEFAULT 1,
    resolved_on   date,
    owner_id      integer REFERENCES people(id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX findings_open_idx ON findings (status, annual_saving DESC NULLS LAST);
CREATE INDEX findings_kind_idx ON findings (kind);

-- How much a finding was actually worth, once acted on. Without this the app
-- can claim it saves money and never has to prove it.
CREATE TABLE finding_outcomes (
    id          serial PRIMARY KEY,
    finding_id  integer NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    note        text,
    saved       numeric(14,2),
    recorded_on date NOT NULL DEFAULT current_date
);
