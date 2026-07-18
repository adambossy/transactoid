# Penny Agent Core

The agent and the finance domain: syncing bank transactions, resolving who
they were with, categorizing them, and answering questions about them — for
households of one or more users.

## Language

### Tenancy

**Household**:
The tenancy unit — an isolated group of one or more users whose finances are
managed together. Every financial row belongs to exactly one household, and
one individual belongs to exactly one household.

**User**:
A member of a household. Every financial row has exactly one owning user.
_Avoid_: account (that's a bank account), member (as an entity name)

**Pending user**:
An invited person who has not yet signed up; they exist in the inviter's
household and are claimed atomically at first login.

**Invite**:
An offer to a new, accountless person to join the inviter's household. An
email with an active account can never be invited.

**Principal**:
The identity a request acts as — a (household, user) pair resolved from
authentication.

**Joint session**:
A session acting for the household as a whole rather than one member; it sees
shared data only and can own nothing.

**Visibility**:
Which household members may see a financial row: `private` (owner only) or
`shared` (the whole household).

### Money movement

**Transaction**:
Unqualified, the derived record — the mutable, enriched, categorized
transaction that queries, reports, and chat operate on.
_Avoid_: bare "transaction" for the immutable Plaid source row

**Plaid transaction**:
The immutable source record of a bank/card transaction as synced from Plaid
(or imported from CSV). Never edited; all enrichment happens on the
transaction derived from it.

**Plaid item**:
A bank connection — one login at one institution, holding one or more
accounts. _Avoid_: bare "item"

**Plaid account**:
A single bank or card account within a Plaid item.

**Sync**:
The idempotent, re-runnable pull of transactions from every connected Plaid
item into the finance database. One broken connection never aborts the rest.

**Descriptor**:
The raw string a bank statement shows for a transaction's counterparty
(e.g. "AplPay MY FAVORITE CBROOKLYN").

**Wrapper descriptor**:
A descriptor naming a payment rail (Venmo, Zelle, ATM, bill-pay) rather than
the real counterparty behind it.

**Merchant**:
The resolved, stable identity of who a transaction was with — the umbrella
term, even when that identity is a person. Produced by normalization.

**Counterparty**:
The human or entity behind a wrapper descriptor (e.g. the friend behind a
Venmo payment).

**Normalization**:
Resolving a raw descriptor to its merchant.

**Sign convention**:
The per-account mapping of amount sign to money-in vs money-out.

**Refund match**:
The link from a refund transaction back to the original transaction it
reverses, made by the user or automatically.

### Categorization

**Taxonomy**:
A household's two-level tree of categories used to classify spending; seeded
at provisioning and independently editable per household.

**Category**:
A top-level node of the taxonomy. Unqualified "category" implies the top
level.

**Subcategory**:
A child node of a category. _Avoid_: child category

**Categorization**:
Assigning a category (or subcategory) to each transaction with an LLM against
the taxonomy; split transactions are categorized per line item.

**Merchant rule**:
A household-authored rule that pins how a merchant's transactions are
categorized, overriding the LLM.

**Deprecated category**:
A category retired from the taxonomy without erasing the history that used it.

### Itemization

**Line item**:
A single line within a transaction — description, amount, quantity — sourced
from Amazon scraping, an email receipt, or manual entry. _Avoid_: bare "item"

**Itemization**:
Enriching a lump charge into its per-item lines so spending is attributed per
item rather than per charge.

**Amazon item**:
A line of a scraped Amazon order, the raw material for itemizing the matching
transaction. _Avoid_: bare "item"

**Email receipt**:
A parsed receipt email used to itemize the transaction it matches.

**Split**:
Dividing one transaction into several so each part carries its own category
(e.g. an itemized Amazon order).

### Agent

**Workspace**:
The persistent store of agent state (memory notes, reports) that carries
across chat and scheduled runs — one shared arm per household, one private
arm per user.

**Memory**:
Durable notes the agent writes to the workspace to carry user context (e.g.
budget notes) across runs.

**Report**:
A recurring spending report — daily (rolled up to monthly on the 1st) or
weekly — produced by the agent and delivered by email.

**Nudge**:
An agent-initiated onboarding prompt toward a setup step, appearing only in
individual conversations, at most once per turn, until the step is accepted
or dismissed.

### Billing

**Subsidy runway**:
The small per-user grant of platform-funded model usage, started at first
Plaid link; once spent, the user must connect their own credentials.

**BYO credential**:
A user-supplied provider API key or OAuth subscription that bills the user's
own provider account instead of the platform.
