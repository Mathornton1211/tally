export type Category = { key: string; label: string; kind: 'expense' | 'income' | 'transfer'; icon: string }
export type AccountRef = { id: string; item_id?: number; source?: 'plaid' | 'manual'; name: string; mask: string | null; type: string; subtype: string | null; institution: string | null }

export type Meta = {
  plaid_env: string
  categories: Category[]
  accounts: AccountRef[]
  last_synced_at: string | null
  needs_attention: number
  first_date: string | null
  last_date: string | null
}

export type Account = AccountRef & {
  owner_id?: number | null
  owner_name?: string | null
  owner_color?: string | null
  currency?: string
  current_balance: number | null
  available_balance: number | null
  credit_limit: number | null
  change?: number
}

export type Txn = {
  id: string
  date: string
  amount: number
  pending: boolean
  name: string
  display_name: string
  logo_url: string | null
  website?: string | null
  note?: string | null
  category: string
  category_label: string
  category_icon: string
  category_overridden?: boolean
  category_from_rule?: boolean
  merchant_key?: string
  bank_text?: string
  category_source?: 'user' | 'rule' | 'tally' | 'ai' | 'plaid' | 'split'
  source?: 'plaid' | 'manual' | 'split'
  tags?: string[]
  currency?: string
  original_amount?: number
  foreign_currency?: boolean
  owner_name?: string | null
  owner_color?: string | null
  rule_id?: number | null
  rule_name?: string | null
  name_source?: 'user' | 'plaid' | 'llm' | 'bank'
  kind: 'expense' | 'income' | 'transfer'
  pfc_detailed?: string | null
  payment_channel?: string | null
  account_id?: string
  account_name: string
  account_mask: string | null
  account_type?: string
  institution?: string | null
}

export type Stream = {
  key: string
  name: string
  logo_url: string | null
  account_id: string
  account_name: string
  category: string
  category_label: string
  kind: 'expense' | 'income'
  cadence: 'weekly' | 'biweekly' | 'monthly' | 'quarterly' | 'yearly'
  count: number
  first_date: string
  last_date: string
  next_date: string
  last_amount: number
  typical_amount: number
  previous_amount: number | null
  price_changed_on: string | null
  active: boolean
  monthly_cost: number
  duplicate?: boolean
  days_until?: number
}

export type CategoryAmount = { key: string; label: string; icon: string; amount: number; previous?: number | null; last_month_same_point?: number | null; count?: number }

export type Dashboard = {
  today: string
  spending: { month_to_date: number; last_month_same_point: number; last_month_total: number; this_month: number[]; last_month: number[]; income_month_to_date: number }
  categories: CategoryAmount[]
  net_worth: { current: number; thirty_days_ago: number | null; series: { date: string; value: number }[] }
  accounts: Account[]
  fees: { last_30: number; count_30: number; ytd: number }
  alerts: { open: number; urgent: number; top: string | null }
  upcoming: Stream[]
  recent: Txn[]
}

export type Spending = {
  start: string; end: string; previous_start: string; previous_end: string
  bucket: 'day' | 'month'
  total: number; previous: number; count: number
  essential: number; flexible: number
  categories: CategoryAmount[]
  series: { bucket: string; amount: number }[]
  merchants: { name: string; logo_url: string | null; icon: string; amount: number; count: number }[]
}

export type CashFlow = {
  start: string; end: string
  months: { month: string; income: number; spending: number; net: number; savings_rate: number | null }[]
  income: number; spending: number; net: number; savings_rate: number | null
}

export type NetWorth = {
  start: string; end: string; estimated: boolean
  series: { date: string; assets: number; liabilities: number; net_worth: number }[]
  accounts: Account[]
}

export type Recurring = {
  streams: Stream[]
  monthly_expense: number; monthly_income: number; next_30_days: number
  price_changes: number; duplicates: number
}

export type FeePlay = {
  type: string; label: string; avoidable: boolean | null; total: number; count: number; last_date: string
  accounts: string[]; facts: string[]; steps: string[]; script: string | null
  needs: { account_id?: string; field: string; ask: string }[]
}
export type FeeRow = Txn & { fee_type: string; fee_label: string; avoidable: boolean | null }
export type Fees = {
  start: string; end: string; total: number; avoidable: number; count: number
  by_month: { month: string; amount: number }[]
  playbook: FeePlay[]; fees: FeeRow[]
}

export type AlertTxn = { id: string; date: string; amount: number; display_name: string; name: string; logo_url: string | null; category_icon: string; account_name: string; account_mask: string | null }
export type Alert = {
  id: number; rule: string; severity: 'low' | 'medium' | 'high'; title: string; detail: string
  inputs: Record<string, unknown>; txn_ids: string[]; account_id: string | null; merchant_key: string | null
  amount: number | null; occurred_on: string; status: 'open' | 'expected' | 'dismissed' | 'fraud'
  resolved_at: string | null; created_at: string; account_name: string | null; account_mask: string | null
  transactions: AlertTxn[]
}
export type Alerts = { counts: { open: number; urgent: number; fraud: number; resolved: number }; alerts: Alert[] }

export type Recommendation = {
  kind: string; priority: 'high' | 'medium' | 'low'; title: string; impact: number; detail: string
  accounts: string[]; assumptions: string[]; link?: string
}
export type Insights = {
  total_impact: number; subscriptions_monthly: number; recommendations: Recommendation[]
  accounts: (Account & { apy: number | null; apr: number | null; annual_fee: number | null; reward_rate: number | null; estimated_apy: number | null; estimated_apr: number | null })[]
}

export type AccountSettings = {
  id: string; name: string; mask: string | null; type: string; subtype: string | null; hidden: boolean
  apy: number | null; apr: number | null; annual_fee: number | null; foreign_fee_pct: number | null
  min_balance_waiver: number | null; reward_rate: number | null; note: string | null
}

export type Debt = {
  account_id: string; name: string; mask: string | null; kind: 'credit' | 'loan'
  balance: number; apr: number | null; apr_source: 'issuer' | 'entered' | 'estimated' | 'unknown'
  minimum: number; minimum_source: 'issuer' | 'assumed'; due_date: string | null; is_overdue: boolean
  credit_limit: number | null; monthly_interest: number; utilization: number | null
}
export type PayoffPlan = {
  strategy: string; months: number | null; payoff_date: string | null
  total_interest: number; total_paid: number; monthly_payment: number
  order: { account_id: string; name: string; mask: string | null; balance: number; apr: number | null
           apr_source: string; minimum: number; minimum_source: string; interest_paid: number
           paid_off_month: number | null; rank: number }[]
  stalled: string[]
  balances: { month: number; balance: number }[]
}
export type PlanEvent = { date: string; name: string; amount: number; kind: 'bill' | 'minimum' | 'overdue' | 'subscription' | 'income' | 'spending'; account: string | null }
export type Runway = {
  today: string; cash: number; cash_accounts: { id: string; name: string; mask: string | null; balance: number }[]
  daily_spending: number; days_until_zero: number | null; zero_date: string | null
  low_point: { date: string; balance: number }
  series: { date: string; balance: number }[]
  events: PlanEvent[]
  shortfalls: { date: string; name: string; amount: number; projected_balance: number; kind: string }[]
  next_income: { date: string; name: string; amount: number } | null
  committed_before_income: number; committed_through: string; income_expected: boolean
  safe_to_spend: number; buffer: number; days_of_cover_at_current_spending: number
}
/** The Plan page's savings goals: progress against one account's balance.
 *  `Goal` below is the same table read the other way -- against a trajectory. */
export type SavingsGoal = {
  id: number; name: string; kind: string; target_amount: number; account_id: string | null
  account_name: string | null; account_mask: string | null; monthly_contribution: number | null
  target_date: string | null; current: number; remaining: number; percent: number | null
  months_to_go: number | null; eta: string | null
}
export type Plan = {
  settings: { monthly_extra: string; cash_buffer: string; strategy: string }
  mode: { mode: 'survival' | 'payoff' | 'growth'; reasons: string[]; revolving_debt: number }
  runway: Runway
  essentials_per_month: number
  debts: Debt[]
  debt_total: number; monthly_interest_total: number; minimums_total: number
  utilization: { used: number; limit: number; percent: number | null
                 cards: { account_id: string; name: string; mask: string | null; balance: number; limit: number; percent: number | null }[] } | null
  payoff: { strategy: string; chosen: PayoffPlan; minimums: PayoffPlan; avalanche: PayoffPlan; snowball: PayoffPlan
            interest_saved: number; months_saved: number | null } | null
  goals: SavingsGoal[]
  suggested_goals: { kind: string; name: string; target_amount: number; account_id?: string; why: string }[]
}

export type Bill = {
  name: string; logo_url: string | null; category: string; category_label: string; account_name: string
  monthly: number; annual: number; last_amount: number; cadence: string; since: string; months_paid: number
  paid_so_far: number; charges: number; increased_from: number | null; price_changed_on: string | null
  why: string; kind: string; script: string
}
export type Bills = { bills: Bill[]; total_monthly: number; total_annual: number; with_increases: number }

export type Holding = {
  account_id: string; account_name: string; account_mask: string | null; subtype: string | null
  security_id: string; ticker: string | null; security_name: string | null; security_type: string | null
  is_cash_equivalent: boolean | null; quantity: number; price: number | null; value: number
  cost_basis: number | null; gain: number | null; weight: number | null
}
export type Portfolio = {
  has_data: boolean
  accounts: { id: string; name: string; mask: string | null; subtype: string | null; institution: string | null
              value: number; holdings: number; retirement: boolean; contributions_ytd: number }[]
  total_value: number; retirement_value: number; taxable_value: number
  cost_basis: number; gain: number; gain_percent: number | null; basis_coverage: number | null
  holdings: Holding[]
  allocation: { type: string; value: number; percent: number | null }[]
  contributions_ytd: number
  recent: { date: string; name: string; type: string; subtype: string | null; quantity: number | null
            amount: number; ticker: string | null; security_name: string | null; account_name: string }[]
}

export type Receipt = {
  id: number; filename: string; content_type: string; bytes: number; amount: number | null
  receipt_date: string | null; merchant: string | null; ocr_source: string | null
  transaction_id: string | null; matched_by: string | null; created_at: string
  display_name: string | null; txn_date: string | null; txn_amount: number | null
  account_name: string | null; account_mask: string | null
  candidates?: ReceiptCandidate[]
}
export type ReceiptCandidate = {
  id: string; date: string; amount: number; display_name: string; account_name: string
  account_mask: string | null; category_label: string; logo_url: string | null; category_icon: string
  score: number; exact_amount: boolean; days_apart: number
}

export type WhatIf = {
  inputs: { monthly_income: number; extra_to_debt: number; cut_flexible_percent: number }
  essentials: number; flexible: number; cut: number; spending: number; minimums: number
  left_over: number; covers_the_month: boolean; shortfall: number
  debt_free: { months: number | null; date: string | null; interest: number } | null
  cushion: { target: number; cash: number; monthly: number; months: number | null; date: string | null }
}
export type Freelance = {
  year: number; rate_percent: number; freelance_income: number; other_income: number
  should_set_aside: number; set_aside: number; short_by: number
  tax_account: { id: string; name: string; mask: string | null; current_balance: number } | null
  clients: { name: string; income: number; share: number | null }[]
  by_month: { month: string; income: number }[]
  quarters: { quarter: string; start: string; end: string; due_date: string; income: number
              estimated_payment: number; past: boolean; next: boolean }[]
  next_due: { quarter: string; due_date: string; income: number; estimated_payment: number } | null
  deposits: { date: string; name: string; amount: number; account: string }[]
  note: string
}

export type FundCredit = {
  id: number; kind: 'gift_card' | 'store_credit' | 'rebate' | 'trade_in' | 'other'
  label: string; amount: number; used: number; remaining: number
  merchant: string | null; expires_on: string | null; note: string | null; expiring: boolean
}
export type Fund = {
  id: number; name: string; target_amount: number; target_date: string | null; note: string | null
  icon: string; priority: number; bought_on: string | null; archived: boolean
  owner_id: number | null
  auto_kind: 'per_paycheck' | 'monthly' | 'percent_of_income' | null
  auto_amount: number | null; auto_percent: number | null; auto_through: string | null
  credits_total: number; saved: number; spent: number; funded: number
  still_needed: number; cash_needed_at_till: number; percent: number | null
  complete: boolean; bought: boolean
  pace_per_month: number | null; months_left_at_pace: number | null
  needed_per_month_for_target_date: number | null
  credits: FundCredit[]
  spends: { id: string; date: string; display_name: string; amount: number; account_name: string }[]
  contributions: { id: number; date: string; amount: number; source: string; note: string | null }[]
  expiring_credits: FundCredit[]
  affordability: { cash_needed: number; spare_after_bills: number; affordable_now: boolean
                   days_of_cash_now: number | null; days_of_cash_after: number | null; note: string } | null
}
export type Funds = {
  funds: Fund[]; total_target: number; total_credits: number; total_saved: number; total_still_needed: number
}

export type BudgetRow = {
  category: string; label: string; icon: string; essential: boolean
  amount: number; rollover: boolean; carry_in: number; set_on: string
  available: number; spent: number; committed: number; transactions: number
  remaining: number; left_after_commitments: number
  percent: number | null; projected: number | null
  state: 'under' | 'watch' | 'over'
  per_day: number | null
  upcoming: { name: string; logo_url: string | null; date: string; amount: number }[]
}
export type BudgetMonth = {
  month: string; days: number; elapsed: number; days_left: number; current: boolean; pace: number
  categories: BudgetRow[]
  unbudgeted: { category: string; label: string; icon: string; spent: number }[]
  budgeted: number; spent: number; committed: number; remaining: number; left_after_commitments: number
  projected: number | null; unbudgeted_spent: number; total_spent: number; income: number; any: boolean
}
export type BudgetSuggestion = {
  category: string; label: string; icon: string; essential: boolean
  amount: number; median: number; worst: number; months: number
  already_budgeted: boolean; rollover: boolean
}

export type Person = {
  id: number; name: string; username: string; role: 'owner' | 'member' | 'viewer'
  color: string
  // Owners only. A member sees who is here, not when they last signed in or
  // how many accounts they keep to themselves.
  last_seen_at?: string | null; created_at?: string
  can_sign_in?: boolean; accounts?: number
}
export type AuthState = {
  mode: 'password' | 'proxy'; required: boolean
  me: { id: number; name: string; username: string; role: string; color: string } | null
  household: number
}

export type Rule = {
  id: number; name: string; enabled: boolean; priority: number
  match_field: 'display_name' | 'bank_text' | 'merchant_key'
  match_type: 'contains' | 'equals' | 'regex'
  pattern: string; min_amount: number | null; max_amount: number | null; account_id: string | null
  set_category: string | null; set_name: string | null; add_tags: string[]; set_note: string | null
  split: { category?: string; name?: string; percent?: number; amount?: number }[] | null
  owner_id: number | null; matches: number
  category_label: string | null; category_icon: string | null
}
export type RulePreview = {
  matches: number; total_amount: number
  sample: { id: string; date: string; display_name: string; bank_text: string; amount: number
            currency: string; category_label: string; account_name: string }[]
}
export type Tag = { tag: string; count: number; total: number }

export type CurrencyStatus = {
  home: string; symbol: string; in_use: string[]; missing: string[]; multi: boolean
  rates: { currency: string; as_of: string; rate: number; source: string }[]
  common: { code: string; name: string; symbol: string }[]
}

export type Goal = {
  id: number; kind: 'net_worth' | 'debt_free' | 'emergency_fund' | 'savings'
  name: string; note: string | null; target_amount: number | null; target_months: number | null
  target_date: string | null; owner_id: number | null; achieved_on: string | null
  target: number; current: number; remaining: number; percent: number | null
  required_per_month: number | null; pace_per_month: number | null
  months_at_pace: number | null; eta: string | null
  state: 'done' | 'on_track' | 'behind' | 'no_deadline' | 'too_early'; done: boolean
  shortfall_per_month: number | null
}
export type GoalsPayload = {
  goals: Goal[]; net_worth: number; pace_per_month: number | null; monthly_spend: number
  measured_over_days: number
  series: { date: string; assets: number; liabilities: number }[]
  suggestions: { kind: string; name: string; why: string; target_amount?: number; target_months?: number }[]
}

/**
 * The getting-started checklist. A step earns its place only if skipping it
 * leaves a page visibly empty or a number quietly wrong — see tally/setup.py.
 */
export type SetupStep = {
  key: 'connect' | 'budget' | 'goal' | 'review' | 'household' | 'fund'
  title: string; why: string; detail: string
  done: boolean
  action: string; action_label: string
  /** Absent means the step is always available. False means it is waiting on data. */
  ready?: boolean
  optional?: boolean
  blocking?: boolean
  suggestion?: {
    categories?: number
    total?: number | string
    top?: { label: string; amount: number | string }[]
    ideas?: { name: string; why: string }[]
  } | null
}
export type SetupState = {
  steps: SetupStep[]
  done: number; total: number; complete: boolean
  show_welcome: boolean
  history_days: number
  counts: {
    items: number; accounts: number; transactions: number; budgets: number
    goals: number; funds: number; people: number; alerts: number
  }
  summary: {
    since: string; transactions: number
    spent: number | string; earned: number | string
    top_categories: { label: string; amount: number | string }[]
    fees: { amount: number | string; count: number }
  }
}

/** Why a charge earned a place in the queue. The API also sends the plain
 *  English for each in `reasons`, so the page never has to write its own. */
export type ReviewReason = 'new_merchant' | 'uncategorised' | 'low_confidence' | 'guessed' | 'large'

export type ReviewItem = {
  id: string; date: string; display_name: string; merchant_key: string
  amount: number | string; currency: string; foreign_currency: boolean
  category: string; category_label: string; category_icon: string
  category_source: string; kind: string; logo_url: string | null
  account_name: string; account_mask: string | null
  bank_text: string | null; name_source: string
  tags: string[]; note: string | null; pfc_confidence: string | null
  owner_name: string | null; owner_color: string | null
  new_merchant: boolean; merchant_seen: number
  reasons: ReviewReason[]
  /** The one to show when several apply. */
  reason: ReviewReason
  why: string
}

/** Same merchant, same decision, applied once. */
export type ReviewGroup = {
  merchant_key: string; display_name: string; logo_url: string | null
  category: string; category_label: string; category_icon: string
  ids: string[]; total: number | string
  reason: ReviewReason; why: string
}

export type ReviewQueue = {
  items: ReviewItem[]
  groups: ReviewGroup[]
  total: number
  window_days: number
  /** Unreviewed charges older than the window — the thing a first run needs a
   *  way past, rather than two thousand decisions. */
  backlog: number
  backlog_oldest: string | null
  reasons: Record<ReviewReason, string>
  shown: number
  progress: { reviewed: number; total_ever: number; today: number }
}

export type ShareLink = {
  id: number; label: string; start_date: string; end_date: string
  detail: 'summary' | 'transactions'; expires_on: string | null; revoked: boolean; dead: boolean
  views: number; last_viewed_at: string | null; created_at: string; created_by_name: string | null
}
export type SharedView = {
  label: string; start: string; end: string; detail: 'summary' | 'transactions'
  spent: number; earned: number; net: number; transactions: number; expires_on: string | null
  categories: { category: string; label: string; icon: string; kind: string
                spent: number; earned: number; count: number }[]
  months: { month: string; spent: number; earned: number }[]
  tags: Tag[]
  rows?: { id: string; date: string; display_name: string; amount: number; currency: string
           category_label: string; kind: string; account_name: string; tags: string[]; note: string | null }[]
}

export type SearchResult = {
  question: string
  filters: { merchant: string | null; category: string | null; tag: string | null
             start: string | null; end: string | null; when: string | null
             min_amount: number | null; max_amount: number | null; kind: string | null
             by: 'text' | 'model' }
  count: number; spent: number; earned: number; average: number
  first: string | null; last: string | null
  rows: Txn[]
  merchants: { name: string; count: number; total: number }[]
  months: { month: string; spent: number; earned: number }[]
}

// Money arrives from Postgres as a string; counts arrive as numbers. Both are
// read through Number() at the point of use rather than coerced here, so the
// raw shape stays honest about what the API actually sent.
type Cash = number | string

export type Finding = {
  id: number
  kind: string
  fingerprint: string
  title: string
  detail: string
  annual_saving: Cash | null
  confidence: 'certain' | 'likely' | 'worth_checking'
  evidence: Record<string, unknown>
  action: string | null
  account_id: string | null
  account_name: string | null
  account_mask: string | null
  merchant_key: string | null
  status: 'open' | 'acted' | 'dismissed' | 'expired'
  first_seen: string
  last_seen: string
  times_seen: number
  resolved_on: string | null
}
export type FindingsPayload = {
  findings: Finding[]
  open: number
  acted: number
  on_the_table: Cash
  actually_saved: Cash
}

export type YoYCategory = {
  category: string; label: string; icon: string; essential: boolean
  now: Cash; before: Cash; change: Cash; percent: number | null; material: boolean
}
export type TrendsPayload = {
  years: {
    year: string; year_number: number; spent: Cash; earned: Cash; net: Cash
    transactions: number; first: string; last: string; partial: boolean; days_covered: number
  }[]
  year_over_year: {
    this_year: { from: string; to: string }
    last_year: { from: string; to: string }
    comparable: boolean
    history_starts: string | null
    spent: Cash; spent_before: Cash; earned: Cash; earned_before: Cash
    spent_change: Cash; spent_percent: number | null
    categories: YoYCategory[]
    risen: YoYCategory[]
    fallen: YoYCategory[]
  }
  months: { month: string; spent: Cash; earned: Cash; net: Cash }[]
  merchants: {
    name: string; logo_url: string | null; icon: string; times: number
    total: Cash; average: Cash; first: string; last: string
  }[]
  available_years: number[]
}

export type AnnualReview = {
  year: number; from: string; to: string; complete: boolean; days: number
  spent: Cash; earned: Cash; net: Cash
  transactions: number; merchants: number
  per_day: Cash; per_month: Cash
  categories: { label: string; icon: string; total: Cash; times: number; share: number | null }[]
  top_merchants: { name: string; logo_url: string | null; total: Cash; times: number }[]
  most_expensive_month: { month: string; spent: Cash } | null
  cheapest_month: { month: string; spent: Cash } | null
  cost_of_carrying: { fees: Cash; count: number; interest: Cash }
  biggest_single: { date: string; name: string; amount: Cash; category: string } | null
}

export type Subscription = {
  name: string; logo_url: string | null; category: string; category_label: string
  account_name: string
  amount: Cash; cadence: string; monthly: Cash; annual: Cash
  paid_so_far: Cash; charges: number
  since: string; next_date: string; months: number
  increased_from: Cash | null
  negotiable: boolean
  cancellable: boolean
  note: string | null
  cancel_script: string | null
  cancel_email: string | null
  lower_email: string | null
}
export type SubscriptionsPayload = {
  subscriptions: Subscription[]
  monthly_total: Cash; annual_total: Cash; paid_so_far_total: Cash
  tips: string[]
  ladder: string[]
}

export type Item = {
  id: number
  institution: string | null
  primary_color: string | null
  oauth: boolean | null
  status: 'ok' | 'login_required' | 'error' | 'disconnected'
  error_code: string | null
  error_message: string | null
  update_status: string | null
  last_synced_at: string | null
  accounts: number
  last_run: { ok: boolean | null; error: string | null; added: number; modified: number; removed: number; finished_at: string | null } | null
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!r.ok) {
    let detail = `${r.status}`
    try {
      const body = await r.json()
      detail = typeof body.detail === 'string' ? body.detail : body.detail?.message || JSON.stringify(body)
    } catch { /* non-JSON error body */ }
    throw new Error(detail)
  }
  return r.json()
}

export type Query = Record<string, string | string[] | undefined>

export function qs(params: Query) {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x))
    else u.set(k, v)
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}

export const api = {
  meta: () => req<Meta>('/api/meta'),
  dashboard: () => req<Dashboard>('/api/dashboard'),
  spending: (q: Query) => req<Spending>('/api/spending' + qs(q)),
  cashflow: (q: Query) => req<CashFlow>('/api/cashflow' + qs(q)),
  networth: (q: Query) => req<NetWorth>('/api/networth' + qs(q)),
  recurring: () => req<Recurring>('/api/recurring'),
  transactions: (q: Query) =>
    req<{ total: number; spending: number; income: number; rows: Txn[] }>('/api/transactions' + qs(q)),
  patchTransaction: (id: string, body: { category?: string; note?: string; reset_category?: boolean }) =>
    req<Partial<Txn>>(`/api/transactions/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  fees: (q: Query) => req<Fees>('/api/fees' + qs(q)),
  alerts: (status = 'open') => req<Alerts>('/api/alerts' + qs({ status })),
  updateAlert: (id: number, status: Alert['status'], trust_merchant = false) =>
    req<{ ok: boolean }>(`/api/alerts/${id}`, { method: 'POST', body: JSON.stringify({ status, trust_merchant }) }),
  insights: () => req<Insights>('/api/insights'),
  accountSettings: (id: string) => req<AccountSettings>(`/api/accounts/${encodeURIComponent(id)}/settings`),
  saveAccountSettings: (id: string, body: Partial<AccountSettings>) =>
    req<AccountSettings>(`/api/accounts/${encodeURIComponent(id)}/settings`, { method: 'PUT', body: JSON.stringify(body) }),
  rulePreview: (merchant_key: string) => req<{ count: number; overridden: number }>('/api/rules/preview' + qs({ merchant_key })),
  createCategoryRule: (merchant_key: string, category: string) =>
    req<{ applied_to: number }>('/api/rules', { method: 'POST', body: JSON.stringify({ merchant_key, category }) }),
  renameMerchant: (txn_id: string, name: string) =>
    req<{ name: string; applied_to: number }>('/api/merchants/name', { method: 'PUT', body: JSON.stringify({ txn_id, name }) }),
  plan: () => req<Plan>('/api/plan'),
  payoff: (extra: number, strategy: string) =>
    req<{ result: PayoffPlan; minimums: PayoffPlan; interest_saved: number; months_saved: number | null }>(
      '/api/payoff' + qs({ extra: String(extra), strategy })),
  savePlanSettings: (body: { monthly_extra?: number; cash_buffer?: number; strategy?: string }) =>
    req<Record<string, string>>('/api/plan/settings', { method: 'PUT', body: JSON.stringify(body) }),
  bills: () => req<Bills>('/api/bills'),
  investments: () => req<Portfolio>('/api/investments'),
  syncInvestments: () => req<Record<string, unknown>>('/api/investments/sync', { method: 'POST' }),
  receipts: (q: Query = {}) =>
    req<{ receipts: Receipt[]; total: number; unmatched: number; total_amount: number; ocr: boolean }>('/api/receipts' + qs(q)),
  uploadReceipt: async (file: File, transactionId?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (transactionId) form.append('transaction_id', transactionId)
    const r = await fetch('/api/receipts', { method: 'POST', body: form })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? `${r.status}`)
    }
    return r.json() as Promise<Receipt>
  },
  receiptCandidates: (id: number) => req<ReceiptCandidate[]>(`/api/receipts/${id}/candidates`),
  patchReceipt: (id: number, body: Record<string, unknown>) =>
    req<Receipt>(`/api/receipts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteReceipt: (id: number) => req<{ ok: boolean }>(`/api/receipts/${id}`, { method: 'DELETE' }),
  notifyStatus: () => req<{ enabled: boolean; reachable?: boolean; reason?: string; url?: string; topic?: string
                            recent: { kind: string; title: string; ok: boolean; created_at: string }[] }>('/api/notify/status'),
  notifyTest: () => req<{ sent: boolean }>('/api/notify/test', { method: 'POST' }),
  briefPreview: () => req<{ title: string; body: string }>('/api/brief/preview'),
  briefSend: () => req<{ sent: boolean }>('/api/brief/send', { method: 'POST' }),
  createManualAccount: (body: Record<string, unknown>) =>
    req<{ id: string; name: string; current_balance: number }>('/api/accounts/manual', { method: 'POST', body: JSON.stringify(body) }),
  setManualBalance: (id: string, current_balance: number) =>
    req<{ ok: boolean }>(`/api/accounts/manual/${id}/balance`, { method: 'PUT', body: JSON.stringify({ current_balance }) }),
  deleteManualAccount: (id: string) => req<{ ok: boolean }>(`/api/accounts/manual/${id}`, { method: 'DELETE' }),
  createManualTransaction: (body: Record<string, unknown>) =>
    req<Txn>('/api/transactions/manual', { method: 'POST', body: JSON.stringify(body) }),
  deleteManualTransaction: (id: string) => req<{ ok: boolean }>(`/api/transactions/manual/${id}`, { method: 'DELETE' }),
  splitTransaction: (id: string, parts: { amount: number; category: string }[]) =>
    req<Txn[]>(`/api/transactions/${encodeURIComponent(id)}/split`, { method: 'POST', body: JSON.stringify({ parts }) }),
  unsplitTransaction: (id: string) => req<Txn>(`/api/transactions/${encodeURIComponent(id)}/split`, { method: 'DELETE' }),
  getSplit: (id: string) => req<{ parent: { id: string; amount: number; is_split_parent: boolean }
                                  parts: { id: string; amount: number; category: string; category_label: string }[] }>(
    `/api/transactions/${encodeURIComponent(id)}/split`),
  whatIf: (monthly_income: number, extra_to_debt: number, cut_flexible_percent: number) =>
    req<WhatIf>('/api/whatif' + qs({ monthly_income: String(monthly_income), extra_to_debt: String(extra_to_debt), cut_flexible_percent: String(cut_flexible_percent) })),
  freelance: (year?: number) => req<Freelance>('/api/income/freelance' + qs(year ? { year: String(year) } : {})),
  config: () => req<{ version: string; plaid_env: string; oauth_ready: boolean
                      timezone: string; ai_enabled: boolean; demo: boolean }>('/api/config'),
  authState: () => req<AuthState>('/api/auth/state'),
  // household
  people: () => req<{ people: Person[]; me: number | null; auth_mode: string }>('/api/people'),
  addPerson: (body: Record<string, unknown>) =>
    req<Person>('/api/people', { method: 'POST', body: JSON.stringify(body) }),
  editPerson: (id: number, body: Record<string, unknown>) =>
    req<Person>(`/api/people/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  removePerson: (id: number, reassignTo?: number) =>
    req<{ ok: boolean }>(`/api/people/${id}${reassignTo === undefined ? '' : `?reassign_to=${reassignTo}`}`, { method: 'DELETE' }),
  setAccountOwner: (accountId: string, owner_id: number | null) =>
    req<{ ok: boolean }>(`/api/people/accounts/${encodeURIComponent(accountId)}/owner`,
      { method: 'PUT', body: JSON.stringify({ owner_id }) }),
  viewAs: (personId: number) => req<{ ok: boolean }>(`/api/people/view-as/${personId}`, { method: 'POST' }),

  // rules and tags
  rules2: () => req<{ rules: Rule[]; tags: Tag[] }>('/api/rules-v2'),
  previewRule: (body: Record<string, unknown>) =>
    req<RulePreview>('/api/rules-v2/preview', { method: 'POST', body: JSON.stringify(body) }),
  createRule: (body: Record<string, unknown>) =>
    req<{ id: number; rules: Rule[] }>('/api/rules-v2', { method: 'POST', body: JSON.stringify(body) }),
  editRule: (id: number, body: Record<string, unknown>) =>
    req<{ rules: Rule[] }>(`/api/rules-v2/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteRule: (id: number) => req<{ rules: Rule[] }>(`/api/rules-v2/${id}`, { method: 'DELETE' }),
  setTxnTags: (id: string, tags: string[]) =>
    req<{ tags: string[] }>(`/api/transactions/${encodeURIComponent(id)}/tags`,
      { method: 'PUT', body: JSON.stringify({ tags }) }),
  tags: () => req<{ tags: Tag[] }>('/api/tags'),

  // currency
  currency: () => req<CurrencyStatus>('/api/currency'),
  setHomeCurrency: (currency: string) =>
    req<CurrencyStatus>('/api/currency/home', { method: 'PUT', body: JSON.stringify({ currency }) }),
  setRate: (body: Record<string, unknown>) =>
    req<CurrencyStatus>('/api/currency/rate', { method: 'PUT', body: JSON.stringify(body) }),
  clearRate: (currency: string) =>
    req<CurrencyStatus>(`/api/currency/rate/${currency}`, { method: 'DELETE' }),

  // goals
  goals2: () => req<GoalsPayload>('/api/goals'),
  createGoal: (body: Record<string, unknown>) =>
    req<GoalsPayload>('/api/goals', { method: 'POST', body: JSON.stringify(body) }),
  editGoal: (id: number, body: Record<string, unknown>) =>
    req<GoalsPayload>(`/api/goals/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteGoal: (id: number) => req<GoalsPayload>(`/api/goals/${id}`, { method: 'DELETE' }),

  // sinking funds
  setFundAuto: (id: number, body: Record<string, unknown>) =>
    req<Fund>(`/api/funds/${id}/auto`, { method: 'PUT', body: JSON.stringify(body) }),
  fundAutoPreview: (params: string) =>
    req<{ over_months: number; deposits: number; contributions: number; total: number; per_month: number }>(
      `/api/funds/auto/preview?${params}`),

  // sharing
  shareLinks: () => req<{ links: ShareLink[] }>('/api/share-links'),
  createShareLink: (body: Record<string, unknown>) =>
    req<{ token: string; url: string; links: ShareLink[] }>('/api/share-links',
      { method: 'POST', body: JSON.stringify(body) }),
  revokeShareLink: (id: number) => req<{ links: ShareLink[] }>(`/api/share-links/${id}`, { method: 'DELETE' }),
  readShared: (token: string) => req<SharedView>(`/api/shared/${encodeURIComponent(token)}`),

  // search
  search: (q: string) => req<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),

  // getting started
  findings: (status?: string) => req<FindingsPayload>(`/api/findings${status ? `?status=${status}` : ''}`),
  scanFindings: () => req<Record<string, number>>('/api/findings/scan', { method: 'POST' }),
  updateFinding: (id: number, body: Record<string, unknown>) =>
    req<FindingsPayload>(`/api/findings/${id}`, { method: 'POST', body: JSON.stringify(body) }),
  trends: () => req<TrendsPayload>('/api/trends'),
  annualReview: (year?: number) => req<AnnualReview>(`/api/trends/review${year ? `?year=${year}` : ''}`),
  subscriptions: () => req<SubscriptionsPayload>('/api/subscriptions'),
  reviewQueue: (days?: number) => req<ReviewQueue>(`/api/review${days ? `?days=${days}` : ''}`),
  reviewApply: (body: Record<string, unknown>) =>
    req<ReviewQueue & { changed: number; reviewed: number }>('/api/review/apply',
      { method: 'POST', body: JSON.stringify(body) }),
  reviewClearBacklog: (before: string) =>
    req<ReviewQueue & { cleared: number }>('/api/review/clear-backlog',
      { method: 'POST', body: JSON.stringify({ before }) }),

  setupState: () => req<SetupState>('/api/setup'),
  applySetupBudgets: () => req<SetupState & { applied: string[] }>('/api/setup/budgets', { method: 'POST' }),
  applySetupGoals: () => req<SetupState & { added: string[] }>('/api/setup/goals', { method: 'POST' }),

  budgets: (month?: string) => req<BudgetMonth>(`/api/budgets${month ? `?month=${month}` : ''}`),
  budgetSuggestions: () => req<{ suggestions: BudgetSuggestion[] }>('/api/budgets/suggestions'),
  setBudget: (category: string, body: Record<string, unknown>) =>
    req<{ reverts_to: number | null; status: BudgetMonth }>(`/api/budgets/${category}`, { method: 'PUT', body: JSON.stringify(body) }),
  clearBudget: (category: string) => req<{ ok: boolean }>(`/api/budgets/${category}`, { method: 'DELETE' }),
  applyBudgetSuggestions: (body: Record<string, unknown>) =>
    req<{ applied: string[]; status: BudgetMonth }>('/api/budgets/apply-suggestions', { method: 'POST', body: JSON.stringify(body) }),
  funds: () => req<Funds>('/api/funds'),
  createFund: (body: Record<string, unknown>) => req<Fund>('/api/funds', { method: 'POST', body: JSON.stringify(body) }),
  patchFund: (id: number, body: Record<string, unknown>) => req<Fund>(`/api/funds/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteFund: (id: number) => req<{ ok: boolean }>(`/api/funds/${id}`, { method: 'DELETE' }),
  addFundCredit: (id: number, body: Record<string, unknown>) =>
    req<Fund>(`/api/funds/${id}/credits`, { method: 'POST', body: JSON.stringify(body) }),
  deleteFundCredit: (id: number, creditId: number) =>
    req<Fund>(`/api/funds/${id}/credits/${creditId}`, { method: 'DELETE' }),
  contributeToFund: (id: number, amount: number, note?: string) =>
    req<Fund>(`/api/funds/${id}/contributions`, { method: 'POST', body: JSON.stringify({ amount, note }) }),
  addFundSpend: (id: number, transaction_id: string) =>
    req<Fund>(`/api/funds/${id}/spends`, { method: 'POST', body: JSON.stringify({ transaction_id }) }),
  removeFundSpend: (id: number, transaction_id: string) =>
    req<Fund>(`/api/funds/${id}/spends/${encodeURIComponent(transaction_id)}`, { method: 'DELETE' }),
  fundsForTransaction: (txnId: string) =>
    req<{ id: number; name: string; icon: string }[]>(`/api/funds/for-transaction/${encodeURIComponent(txnId)}`),
  items: () => req<Item[]>('/api/items'),
  allAccounts: () => req<(Account & { hidden: boolean })[]>('/api/accounts'),
  linkToken: (item_id?: number) =>
    req<{ link_token: string }>('/api/link/token', { method: 'POST', body: JSON.stringify({ item_id: item_id ?? null }) }),
  exchange: (public_token: string) =>
    req<{ item_id: number }>('/api/link/exchange', { method: 'POST', body: JSON.stringify({ public_token }) }),
  syncAll: () => req<{ queued: boolean }>('/api/sync', { method: 'POST' }),
  syncItem: (id: number) => req<Record<string, unknown>>(`/api/items/${id}/sync`, { method: 'POST' }),
}

export const LINK_TOKEN_KEY = 'tally.link_token'
export const LINK_ITEM_KEY = 'tally.link_item'
