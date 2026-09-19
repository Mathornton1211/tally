-- An alert the rules would no longer raise should stop being raised.
--
-- `findings` already works this way (migration 019): a rule that stops holding
-- retires its finding instead of leaving it on the list forever. Alerts never
-- had that, so every alert ever generated stayed open until somebody clicked
-- it -- including the ones produced by a rule that has since been fixed.
--
-- That matters more here than it does for findings, because these are the
-- alerts. A list that is 84% noise is one people stop opening, and then the
-- reversible fee sitting in it never gets called about.
--
-- `expired` is deliberately not `dismissed`. Dismissed means a person decided;
-- expired means the app did, and the two should never be confused when
-- somebody is later asking why they were not told about something.

ALTER TABLE alerts DROP CONSTRAINT alerts_status_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_status_check
  CHECK (status IN ('open', 'expected', 'dismissed', 'fraud', 'expired'));

-- Why it expired, so "the app stopped showing me this" has an answer.
ALTER TABLE alerts ADD COLUMN expired_reason text;
