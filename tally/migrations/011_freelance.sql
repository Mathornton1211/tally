-- Self-employment income, kept apart from a paycheck.
--
-- The difference matters: nobody withholds tax on it, so a share of every
-- deposit is not really yours. Tally tracks that share; it does not file
-- anything and it is not tax advice.

INSERT INTO categories (key, label, kind, icon, sort, essential) VALUES
  ('freelance', 'Freelance & self-employed', 'income', 'Briefcase', 205, false)
ON CONFLICT (key) DO NOTHING;

-- Deposits from the usual platforms are self-employment income by default.
-- A rule the owner sets, or an edit on one transaction, still wins over this.
CREATE FUNCTION tally_freelance_default(bank_text text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(bank_text, '') ~* '(upwork|fiverr|stripe|paypal|gusto pay.*1099|toptal|contra|deel|wise|venmo.*business)'
$$;
