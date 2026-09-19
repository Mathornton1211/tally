"""Rules: rename, recategorise, tag, annotate, and split -- automatically.

Renaming, categorising, tagging and noting are computed in the v_txn view, so a
rule applies to history the instant it is saved and un-applies the instant it is
deleted. There is no backfill job and nothing to get out of step.

Splitting cannot work that way. A split is real child rows, and a view cannot
invent rows, so splits are applied after a sync. A split that somebody has
edited by hand is left alone (`split_locked`), because having the computer undo
your correction every six hours is worse than not automating it at all.
"""
import json
from decimal import ROUND_HALF_UP, Decimal

from psycopg.types.json import Jsonb

ZERO = Decimal(0)
FIELDS = ("display_name", "bank_text", "merchant_key")
TYPES = ("contains", "equals", "regex")


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def listing(conn) -> list[dict]:
    """Every rule the viewer can see, with how many transactions it is
    currently touching. The count is the whole point of the page: a rule you
    cannot see the effect of is a rule you will not trust."""
    return conn.execute(
        """SELECT r.*, c.label AS category_label, c.icon AS category_icon,
                  (SELECT count(*) FROM v_txn v WHERE v.rule_id = r.id) AS matches
           FROM rules r LEFT JOIN categories c ON c.key = r.set_category
           WHERE tally_can_see(r.owner_id)
           ORDER BY r.priority DESC, r.id""").fetchall()


def preview(conn, rule: dict, limit: int = 12) -> dict:
    """What a rule would do, before it is saved.

    Runs the same matching function the view uses rather than a reimplementation
    in Python, so the preview cannot disagree with the result.
    """
    rows = conn.execute(
        """SELECT v.id, v.date, v.display_name, v.bank_text, v.amount, v.currency,
                  v.category_label, v.account_name
           FROM v_txn v
           WHERE tally_rule_match(%s, %s, CASE %s WHEN 'bank_text' THEN v.bank_text
                                                  WHEN 'merchant_key' THEN v.merchant_key
                                                  ELSE v.display_name END)
             AND (%s::numeric IS NULL OR abs(v.amount) >= %s)
             AND (%s::numeric IS NULL OR abs(v.amount) <= %s)
             AND (%s::text IS NULL OR v.account_id = %s)
           ORDER BY v.date DESC LIMIT %s""",
        (rule["pattern"], rule["match_type"], rule["match_field"],
         rule.get("min_amount"), rule.get("min_amount"),
         rule.get("max_amount"), rule.get("max_amount"),
         rule.get("account_id"), rule.get("account_id"), limit)).fetchall()
    total = conn.execute(
        """SELECT count(*) AS n, coalesce(sum(abs(v.amount)), 0) AS total
           FROM v_txn v
           WHERE tally_rule_match(%s, %s, CASE %s WHEN 'bank_text' THEN v.bank_text
                                                  WHEN 'merchant_key' THEN v.merchant_key
                                                  ELSE v.display_name END)
             AND (%s::numeric IS NULL OR abs(v.amount) >= %s)
             AND (%s::numeric IS NULL OR abs(v.amount) <= %s)
             AND (%s::text IS NULL OR v.account_id = %s)""",
        (rule["pattern"], rule["match_type"], rule["match_field"],
         rule.get("min_amount"), rule.get("min_amount"),
         rule.get("max_amount"), rule.get("max_amount"),
         rule.get("account_id"), rule.get("account_id"))).fetchone()
    return {"matches": total["n"], "total_amount": _q(total["total"]), "sample": rows}


def validate_split(parts: list[dict]) -> list[dict]:
    """A split is either all percentages or all amounts, and percentages add to
    100. Mixing them produces a total nobody can predict."""
    if not parts:
        return []
    by_percent = all("percent" in p and p.get("percent") is not None for p in parts)
    by_amount = all("amount" in p and p.get("amount") is not None for p in parts)
    if not (by_percent or by_amount):
        raise ValueError("every part needs a percent, or every part needs an amount")
    if by_percent:
        total = sum(Decimal(str(p["percent"])) for p in parts)
        if abs(total - 100) > Decimal("0.01"):
            raise ValueError(f"the percentages add up to {total}, not 100")
    return parts


def _amounts(parts: list[dict], total: Decimal) -> list[Decimal]:
    """Split `total` the way the rule says, with the rounding remainder going to
    the last part so the children always add back to the parent exactly."""
    if parts and parts[0].get("percent") is not None:
        out = [_q(total * Decimal(str(p["percent"])) / 100) for p in parts]
    else:
        out = [_q(Decimal(str(p["amount"]))) for p in parts]
    drift = total - sum(out)
    if out and drift:
        out[-1] = _q(out[-1] + drift)
    return out


def apply_splits(conn, limit_days: int = 400) -> dict:
    """Split what the split rules say to split.

    Idempotent: a row that is already a split parent is skipped, and a split
    somebody has edited by hand is never touched. That makes a wide window
    cheap on the second run, so the default covers roughly the history a person
    can actually see -- adding a split rule and having it ignore everything
    older than a few months looks broken.
    """
    rules = conn.execute(
        """SELECT id, pattern, match_type, match_field, min_amount, max_amount, account_id, split
           FROM rules WHERE enabled AND split IS NOT NULL
           ORDER BY priority DESC, id""").fetchall()
    made = skipped = 0
    for r in rules:
        parts = r["split"] if isinstance(r["split"], list) else json.loads(r["split"])
        if not parts:
            continue
        targets = conn.execute(
            """SELECT t.id, t.amount, t.account_id, t.date, t.name, t.iso_currency,
                      t.pfc_primary, t.pfc_detailed, t.pfc_confidence, t.raw,
                      COALESCE(NULLIF(t.raw->>'original_description', ''), t.name) AS bank_text,
                      lower(COALESCE(t.merchant_name, t.name)) AS merchant_key
               FROM transactions t
               WHERE NOT t.is_split_parent AND t.parent_id IS NULL AND NOT t.split_locked
                 AND t.date >= current_date - %s
                 AND tally_rule_match(%s, %s,
                       CASE %s WHEN 'bank_text' THEN COALESCE(NULLIF(t.raw->>'original_description',''), t.name)
                               WHEN 'merchant_key' THEN lower(COALESCE(t.merchant_name, t.name))
                               ELSE COALESCE(t.merchant_name, t.name) END)
                 AND (%s::numeric IS NULL OR abs(t.amount) >= %s)
                 AND (%s::numeric IS NULL OR abs(t.amount) <= %s)
                 AND (%s::text IS NULL OR t.account_id = %s)""",
            (limit_days, r["pattern"], r["match_type"], r["match_field"],
             r["min_amount"], r["min_amount"], r["max_amount"], r["max_amount"],
             r["account_id"], r["account_id"])).fetchall()

        for t in targets:
            amounts = _amounts(parts, Decimal(t["amount"]))
            for i, (part, amount) in enumerate(zip(parts, amounts)):
                conn.execute(
                    """INSERT INTO transactions
                          (id, account_id, amount, date, iso_currency, name, merchant_name, category,
                           pfc_primary, pfc_detailed, pfc_confidence, is_split_parent, parent_id,
                           source, raw)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,'split',%s)
                       ON CONFLICT (id) DO NOTHING""",
                    (f"{t['id']}-rule{r['id']}-{i}", t["account_id"], amount, t["date"],
                     t["iso_currency"], part.get("name") or t["name"], part.get("name"),
                     part.get("category"), t["pfc_primary"], t["pfc_detailed"], t["pfc_confidence"],
                     t["id"], Jsonb(t["raw"])))
            conn.execute(
                "UPDATE transactions SET is_split_parent = true, split_by_rule = %s WHERE id = %s",
                (r["id"], t["id"]))
            made += 1
    conn.commit()
    return {"split": made, "skipped": skipped}


def unsplit_rule(conn, rule_id: int) -> int:
    """Undo what a rule split, when the rule is turned off or deleted. Children
    go via ON DELETE CASCADE; the parent just stops being a parent."""
    parents = conn.execute(
        "SELECT id FROM transactions WHERE split_by_rule = %s AND NOT split_locked", (rule_id,)).fetchall()
    for p in parents:
        conn.execute("DELETE FROM transactions WHERE parent_id = %s", (p["id"],))
        conn.execute(
            "UPDATE transactions SET is_split_parent = false, split_by_rule = NULL WHERE id = %s", (p["id"],))
    return len(parents)


def all_tags(conn) -> list[dict]:
    return conn.execute(
        """SELECT tag, count(*) AS count, coalesce(sum(abs(amount)), 0) AS total
           FROM v_txn, unnest(tags) AS tag GROUP BY tag ORDER BY count DESC""").fetchall()
