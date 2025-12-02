from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
from textwrap import dedent
from typing import Any, Dict, Optional, Tuple

import yaml
from openai import OpenAI
from promptorium import load_prompt
from promptorium.services import PromptService
from promptorium.storage.fs import FileSystemPromptStorage
from promptorium.util.repo_root import find_repo_root

# Merged prompt template with {input_yaml} placeholder.
# This is used as a fallback if Promptorium is not available.
DEFAULT_MERGED_TEMPLATE: str = dedent(
    """\
    You are an expert taxonomist and information architect. You will be given:
    A list of parent categories and child categories (in YAML form)
    Optionally, short rules or hints for each category
    Your goal is to write a comprehensive, human-readable taxonomy document that mirrors the quality, structure, and detail of the Personal Finance Transaction Taxonomy v0 shown below.

    ---

    You are an expert taxonomy architect and information designer.

    You will be given a YAML definition containing parent and child categories for a specific domain.
    Your job is to produce a comprehensive two-level taxonomy document, modeled after the “Proposed 2-level Transaction Category Taxonomy (v0)” example.

    ### Input YAML
    {input_yaml}

    ### Domain
    Personal Finance Transactions

    ---

    ### Your Objectives

    **1. Analyze and interpret**
    - Infer what each category means and how it fits conceptually into the overall system.
    - Identify natural relationships, exclusions, and likely overlap zones.
    - Determine which global classification principles will yield consistent labeling.

    **2. Write the taxonomy document**
    Produce a Markdown document with the following structure and style:

    ---

    ## Proposed 2-Level Personal Finance Transactions Taxonomy (v1)

    ### Overview
    - Define the scope, goals, and intended users of this taxonomy.
    - Explain its coverage (e.g., breadth vs. granularity).
    - Note its organizing logic (e.g., conceptual hierarchy, user-facing simplicity).

    ### Top-Level Categories
    List all top-level categories (those with `parent_key: null`) and briefly describe each one’s purpose and scope.

    ### Global Rules & Overlap Resolution
    Describe how classification should work across all categories:
    - **Hierarchy depth**: exactly two levels (parent → child), no deeper.
    - **Decision order**: specify an order of precedence when assigning categories.
    - **Overlap resolution**: when a case could fit multiple categories, explain which one wins and why.
    - **Edge disambiguation**: rules for ambiguous or hybrid items.
    - **Exclusions**: what does *not* belong in this taxonomy or under certain headings.

    ### Category Definitions
    For each top-level category:
    1. Provide a **definition** (one concise paragraph).
    2. Then enumerate all sub-categories in a nested section using this structure:
    - **Name — short definition**
    - **Examples:** several concrete examples illustrating inclusions.
    - **Excludes:** common mistakes or near-misses; redirect them to the right category if possible.

    Use Markdown `<details>` / `<summary>` blocks or similar formatting for collapsible sections.

    ### Edge Cases & Guidance
    - Document ambiguous or mixed situations and how to resolve them.
    - Include guidance on how to tag, split, or handle multi-label items.
    - Offer consistency rules for data input, labeling, or automated classification logic.

    ---

    ### Style Guide
    - Match the level of clarity and granularity in the *Personal Finance Taxonomy (v0)* example.
    - Use precise, non-redundant language.
    - Keep examples realistic and domain-specific.
    - Prefer definitions that focus on *user intent* and *functional use*, not abstract theory.
    - When helpful, mention what should be *excluded* or *handled elsewhere*.
    - Use hierarchical Markdown headings (`##`, `###`, `####`) consistently.

    ---

    ## Personal Finance Taxonomy (v0) Example

    > This is a two‑level, user‑facing taxonomy for a personal finance app. It balances breadth (covers typical inflows, outflows, and non‑spend banking items) with low cognitive load by using 15 top‑level categories. Each top‑level category has optional sub‑categories with short definitions, examples, and common exclusions to reduce overlap.
    > 
    > Top‑level categories (15)
    > - Income
    > - Housing & Utilities
    > - Food & Dining
    > - Transportation & Auto
    > - Health & Wellness
    > - Insurance
    > - Debt & Loans
    > - Savings & Investments
    > - Shopping & Personal Care
    > - Entertainment & Subscriptions
    > - Education & Childcare
    > - Travel
    > - Gifts & Donations
    > - Taxes & Government
    > - Banking Movements (Transfers, Refunds & Fees)
    > 
    > Global rules and overlap resolution
    > - Exactly two levels: top‑level category → optional sub‑category. No deeper nesting.
    > - Decision order (apply in this sequence when classifying):
    >   1) Banking Movements (non‑spend mechanics: internal transfers, refunds, cash, bank fees)
    >   2) Income (money earned/received: salary, benefits, interest/dividends)
    >   3) Debt & Loans (credit card and loan payments, card interest/fees)
    >   4) Insurance (all premiums), then Taxes & Government (taxes, fines, registrations)
    >   5) Savings & Investments (contributions, buys/sells, investment fees)
    >   6) Domain spend: Housing → Food → Transport → Health → Shopping → Entertainment → Education → Travel → Gifts
    > - Mortgage lives under Housing & Utilities (not under Debt) to match how users think about living costs.
    > - Credit card payments: Debt & Loans → Credit Card Payment. Do NOT double‑count the underlying purchases.
    > - P2P (Venmo, Zelle, PayPal): if it clearly pays for goods/services (memo/merchant hints), re‑classify to that spend category; otherwise keep under Banking Movements → Transfer: External (P2P).
    > - Sales tax: keep embedded in the purchase category. Only use Taxes & Government → Sales/Use Tax if it posts as a separate transaction.
    > - Investment income: Income → Interest & Dividends. Investment trading fees: Savings & Investments → Investment Fees.
    > - Insurance claims paid out to you: Income → Other Income (or categorize based on the expense it offsets if split). Merchant refunds go to Banking Movements → Refund/Chargeback.
    > - Splits encouraged for mixed purchases (e.g., Target run: Groceries + Household Supplies).
    > - Cash withdrawals are not spend. You may tag later cash spend separately if the app supports it.
    > 
    > Below are the categories with definitions, examples, and exclusions. Click to expand any section.
    > 
    > <details>
    > <summary><strong>1) Income</strong></summary>
    > 
    > Definition: Money you receive that increases your balance (earned or unearned).
    > 
    > Sub‑categories
    > - Salary & Wages — Paychecks, direct deposits from employer. Examples: biweekly payroll deposit; W‑2 wages. Excludes: bonuses → Bonus & Commission.
    > - Bonus & Commission — Variable compensation. Examples: annual bonus; sales commission. Excludes: tips → Tips.
    > - Tips — Gratuities received. Examples: cash tips; card tip payout. Excludes: customer payments for goods/services → Self‑Employment & Side Hustle.
    > - Self‑Employment & Side Hustle — Business income paid to you. Examples: freelance invoice paid; Etsy payout; Uber/Lyft driver payout. Excludes: reimbursements → Banking Movements → Refund/Chargeback if merchant; otherwise categorize the underlying expense.
    > - Government Benefits — Social Security, unemployment, SNAP cash credits. Examples: SSA deposit; state unemployment. Excludes: tax refunds → Tax Refunds.
    > - Interest & Dividends — Bank interest, brokerage dividends. Examples: monthly savings interest; ETF dividend. Excludes: trading proceeds → Savings & Investments → Investment Sell/Withdrawal.
    > - Tax Refunds — Federal/state income tax refunds. Examples: IRS refund; state refund. Excludes: merchant returns → Banking Movements → Refund/Chargeback.
    > - Gifts Received — Monetary gifts to you. Examples: birthday cash; family transfer marked as gift. Excludes: payments for goods/services → classify by purpose.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>2) Housing & Utilities</strong></summary>
    > 
    > Definition: Ongoing costs to keep a primary residence running.
    > 
    > Sub‑categories
    > - Rent — Monthly rent to landlord or platform. Examples: rent check; property management ACH. Excludes: security deposit transfers → Banking Movements or Refund/Chargeback when returned.
    > - Mortgage Payment — Monthly mortgage payment. Treat as a single line item (principal+interest+escrow). Excludes: property tax paid separately → Taxes & Government.
    > - HOA/Condo Fees — Dues to associations. Examples: monthly HOA. Excludes: one‑off special assessments → keep here (still housing).
    > - Electricity — Utility bill. Examples: local power company ACH.
    > - Gas — Natural gas utility. Examples: gas utility autopay.
    > - Water & Sewer — Municipal water/sewer. Examples: city utilities.
    > - Trash & Recycling — Waste services. Examples: quarterly trash bill.
    > - Internet — Home broadband. Examples: cable/fiber ISP. Excludes: mobile data → Mobile Phone.
    > - Mobile Phone — Wireless plans. Examples: AT&T/Verizon/T‑Mobile. Excludes: device financing → Debt & Loans if financed; device purchase outright → Shopping & Personal Care → Electronics.
    > - Home Services & Maintenance — Repairs, cleaning, landscaping, pest control, handyman. Excludes: home insurance → Insurance.
    > - Home Renovation
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>3) Food & Dining</strong></summary>
    > 
    > Definition: Consumable food and beverage purchases.
    > 
    > Sub‑categories
    > - Groceries — Supermarkets, warehouse clubs. Includes household consumables if not split. Excludes: pet food → Shopping & Personal Care → Pets.
    > - Restaurants — Sit‑down dining. Excludes: bars without food → Bars & Alcohol.
    > - Treats — Bakeries, smoothies, ice cream, not quite a restaurant meal but also not a coffee shop.
    > - Coffee Shops
    > - Delivery & Takeout — DoorDash, Uber Eats, pizza delivery. Excludes: service fees refunded → Banking Movements → Refund/Chargeback.
    > - Meal Kits — HelloFresh, Blue Apron subscriptions. Excludes: one‑off groceries → Groceries.
    > - Bars & Alcohol — Bars, liquor stores. Excludes: wine subscriptions → Entertainment & Subscriptions → Subscriptions (or Restaurants if consumed on‑site with food).
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>4) Transportation & Auto</strong></summary>
    > 
    > Definition: Moving yourself and vehicles (excluding insurance and loan payments).
    > 
    > Sub‑categories
    > - Fuel — Gasoline/diesel. Includes EV charging if preferred to keep simple? See EV Charging below.
    > - EV Charging — Public/home charging network payments. Excludes: home electricity bill → Housing & Utilities → Electricity (if not separately metered).
    > - Public Transit — Bus, subway, commuter rail, passes.
    > - Rides & Taxis — Uber/Lyft, taxi fare. Excludes: airport shuttles while traveling → Travel → Local Transport (optional; otherwise keep here).
    > - Parking & Tolls — Garages, meters, toll roads. Excludes: fines/tickets → Taxes & Government → Fines & Tickets.
    > - Auto Service & Parts — Maintenance, tires, oil changes, parts.
    > - Car Wash & Detailing — Standalone wash/detail services.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>5) Health & Wellness</strong></summary>
    > 
    > Definition: Out‑of‑pocket health and wellness spending (premiums live under Insurance).
    > 
    > Sub‑categories
    > - Doctor & Hospital — Visits, procedures. Excludes: premiums → Insurance → Health Insurance.
    > - Pharmacy & Prescriptions — Rx co‑pays, pharmacy purchases. Excludes: general toiletries → Shopping & Personal Care → Beauty & Personal Care.
    > - Dental — Cleanings, orthodontics.
    > - Vision — Exams, glasses/contacts.
    > - Mental Health — Therapy, counseling.
    > - Fitness & Gym — Gym dues, classes, fitness apps.
    > - Wellness Products — OTC meds, supplements.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>6) Insurance</strong></summary>
    > 
    > Definition: Recurring premiums for risk coverage.
    > 
    > Sub‑categories
    > - Health Insurance — Medical/dental/vision premiums paid out of pocket. Excludes: employer payroll deductions if not visible; if visible, still here.
    > - Auto Insurance — Car insurance premiums.
    > - Home/Renters Insurance — Homeowners or renters policies.
    > - Flood Insurance
    > - Life & Disability Insurance — Term life, LTD/STD.
    > - Pet Insurance — Pet medical policies.
    > - Travel Insurance — Trip insurance. Excludes: lodging/airfare → Travel.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>7) Debt & Loans</strong></summary>
    > 
    > Definition: Payments and charges tied to credit cards and loans (non‑mortgage).
    > 
    > Sub‑categories
    > - Credit Card Payment — Payments from bank to credit card. Excludes: purchases on the card; those belong to their spend categories.
    > - Credit Card Interest & Fees — Interest charges, annual fees, late fees on cards.
    > - Student Loan Payment — Federal/private student loan payments.
    > - Auto Loan Payment — Car loan payments. Excludes: insurance → Insurance → Auto Insurance.
    > - Personal/BNPL Loan Payment — Personal loans, Affirm/Klarna/Afterpay.
    > - Loan Fees & Adjustments — Origination fees, deferment charges.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>8) Savings & Investments</strong></summary>
    > 
    > Definition: Growing assets via savings or investing; includes related fees (but income from investments is under Income).
    > 
    > Sub‑categories
    > - Savings Contribution — Moves to savings/high‑yield accounts. Excludes: pure internal shuffles between checking accounts → Banking Movements → Transfer: Own Accounts.
    > - Retirement Contribution — IRA/401(k) contributions visible in feed. Excludes: payroll pre‑tax deductions when not posted as bank transactions.
    > - Investment Buy — Purchases of stocks/ETFs/crypto/funds.
    > - Investment Sell/Withdrawal — Proceeds out of brokerage.
    > - Investment Fees & Commissions — Trading fees, advisory fees.
    > - 529/Other Long‑Term Savings — Education/other earmarked contributions.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>9) Shopping & Personal Care</strong></summary>
    > 
    > Definition: Non‑food consumer goods and personal care.
    > 
    > Sub‑categories
    > - Clothing & Accessories — Apparel, shoes, jewelry.
    > - Household Supplies — Cleaning supplies, paper goods.
    > - Electronics & Gadgets — Phones, laptops, peripherals.
    > - Furniture & Appliances — Home furnishings, small/major appliances.
    > - Beauty & Personal Care — Cosmetics, hair, spa.
    > - Pets — Pet food, supplies, grooming, vet visits. Excludes: pet insurance → Insurance → Pet Insurance.
    > - Postage & Shipping — USPS/UPS/FedEx retail.
    > 
    > Excludes: gifts for others → Gifts & Donations; books/media/apps → Entertainment & Subscriptions.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>10) Entertainment & Subscriptions</strong></summary>
    > 
    > Definition: Media, leisure, digital content, and subscription services.
    > 
    > Sub‑categories
    > - Streaming Video — Netflix, Hulu, etc.
    > - Music & Audio — Spotify, Audible.
    > - Gaming — Game purchases, in‑app, platform subs.
    > - Books, Apps & Media — eBooks, app stores.
    > - News & Publications — Newspapers, magazines.
    > - Hobbies & Leisure — Crafts, sports gear rentals, museum tickets.
    > - Cloud & Software Subscriptions — iCloud/Drive, productivity apps.
    > 
    > Excludes: live events while traveling → can stay here or under Travel → Activities; choose consistently.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>11) Education & Childcare</strong></summary>
    > 
    > Definition: Learning and dependent care costs.
    > 
    > Sub‑categories
    > - Tuition & School Fees — K‑12, college, private school.
    > - Books & Supplies — Textbooks, materials.
    > - Courses & Certifications — Online courses, bootcamps.
    > - Childcare & Babysitting — Daycare, sitters, after‑school care.
    > - School Activities & Lunch — Clubs, field trips, lunch accounts.
    > 
    > Excludes: student loan payments → Debt & Loans.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>12) Travel</strong></summary>
    > 
    > Definition: Spend tied to trips away from home. Use when you want trips grouped distinctly; otherwise classify to everyday categories and tag the trip.
    > 
    > Sub‑categories
    > - Flights — Airline tickets, seat fees.
    > - Lodging — Hotels, vacation rentals.
    > - Local Transport — Trains, car rentals, airport shuttles.
    > - Travel Meals & Dining — Restaurants while traveling (optional; alternatively keep under Food & Dining for budget consistency).
    > - Activities & Tours — Attractions, excursions.
    > - Baggage/Other Travel Fees — Baggage, resort fees.
    > 
    > Excludes: travel insurance → Insurance → Travel Insurance.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>13) Gifts & Donations</strong></summary>
    > 
    > Definition: Money given to others without direct goods/services for you.
    > 
    > Sub‑categories
    > - Gifts Given — Presents, cash gifts. Excludes: purchases for yourself → Shopping & Personal Care.
    > - Charitable Donations — 501(c)(3) donations. Excludes: crowdfunding for products → Shopping or Entertainment.
    > - Religious Giving — Tithes/offerings.
    > - Crowdfunding Support — GoFundMe, similar personal causes.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>14) Taxes & Government</strong></summary>
    > 
    > Definition: Taxes, fees, and payments to government entities.
    > 
    > Sub‑categories
    > - Federal Income Tax — Payments and estimates.
    > - State/Local Income Tax — Payments and estimates.
    > - Property Tax — Real estate taxes paid directly.
    > - Sales/Use Tax (Standalone) — Only when posted as its own transaction.
    > - DMV & Registration — Vehicle registration, license renewals. Excludes: parking meters/garages → Transportation & Auto → Parking & Tolls.
    > - Fines & Tickets — Parking/speeding tickets.
    > - Customs & Duties — Import fees.
    > 
    > Excludes: tax refunds → Income → Tax Refunds.
    > 
    > </details>
    > 
    > <details>
    > <summary><strong>15) Banking Movements (Transfers, Refunds & Fees)</strong></summary>
    > 
    > Definition: Non‑spend mechanics and bank‑level adjustments. Use these first when applicable.
    > 
    > Sub‑categories
    > - Transfer: Own Accounts — Moves between your accounts (checking↔savings, bank↔bank). Excludes: credit card payments → Debt & Loans → Credit Card Payment; investment contributions → Savings & Investments → Savings/Retirement Contribution.
    > - Transfer: External (P2P) — Venmo/Zelle/PayPal to/from others when purpose isn’t identifiable. Re‑categorize to the appropriate spend/income category if the memo clarifies.
    > - Credit Card Payment — Payment to card accounts. Excludes: card fees/interest → Debt & Loans → Credit Card Interest & Fees.
    > - Cash Withdrawal (ATM) — ATM withdrawals. Excludes: ATM fees → Bank Fee/Service Charge.
    > - Cash Deposit — Depositing cash at bank/ATM.
    > - Check Payment/Deposit — Paper/eCheck movement.
    > - Refund/Chargeback — Merchant returns, chargebacks, subscription reversals. If refund clearly offsets a prior categorized purchase, you may net it against that category.
    > - Reversal/Correction — Duplicate reversals, bank error corrections.
    > - Bank Fee/Service Charge — Monthly maintenance, overdraft, wire fees, ATM fees. Excludes: investment advisory/trade fees → Savings & Investments → Investment Fees.
    > 
    > Excludes: interest earned → Income → Interest & Dividends.
    > 
    > </details>
    > 
    > Edge cases and guidance
    > - Trip spending: Choose either “Travel” sub‑categories for all on‑trip spend or leave everyday categories (Food, Transport) and attach a trip tag; be consistent across the app.
    > - Merchant aggregators (Amazon, Walmart, Target): For Amazon, we actually have access to Amazon transaction data. So mark transactions from Amazon as "Amazon" and we'll reconcile them later. Otherwise, default to Shopping & Personal Care.
    > - Annual subscriptions billed via app stores: classify by content (e.g., streaming vs. cloud storage). If unclear, Entertainment & Subscriptions → Cloud & Software Subscriptions.
    > - Escrow and mortgage: Keep full mortgage payment under Housing & Utilities → Mortgage Payment (don’t split interest/escrow in daily views). Advanced analytics may decompose if desired.
    > - Reimbursements from employer or friends: If posted as a refund from the original merchant, use Banking Movements → Refund/Chargeback; if posted as a P2P from a person, Income → Gifts Received or Banking Movements → Transfer: External (P2P) and tag as reimbursement.

    Model your output after this example’s **tone, structure, and depth**, but adapt all content to the supplied domain.

    ---

    ### Output Format
    Produce the final Markdown taxonomy as the only output.  
    Do **not** restate the YAML or re-list instructions.

    ---

    Now, using this prompt, analyze the YAML and generate the complete taxonomy document for **Personal Finance Transactions**.
    """
)


# ----------------------------
# Promptorium integration (library-based)
# ----------------------------
def store_generated(markdown: str) -> None:
    """
    Store generated taxonomy markdown to Promptorium under key `taxonomy-rules`.
    Uses the Promptorium library and creates the key if it does not exist.
    """
    key = "taxonomy-rules"
    storage = FileSystemPromptStorage(find_repo_root())
    svc = PromptService(storage)
    # Try updating directly; if key doesn't exist, add then retry.
    try:
        svc.update_prompt(key, markdown)
        return
    except Exception:
        try:
            storage.add_prompt(key, custom_dir=None)
        except Exception:
            # If add_prompt fails because it already exists or any race, ignore and retry update.
            pass
        svc.update_prompt(key, markdown)


# ----------------------------
# Core helpers
# ----------------------------
def read_yaml_text(path: str) -> str:
    """
    Read the YAML file content as text.
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _normalize_yaml_for_hash(yaml_text: str) -> str:
    """
    Normalize YAML text for hashing.
    - Prefer canonicalization via PyYAML if available (sorted keys, stable dump)
    - Fallback to whitespace-trimmed text, which is stable but not key-sorted
    - Goal: semantically equivalent YAML yields identical hashes; whitespace-only diffs ignored
    """
    try:
        data = yaml.safe_load(yaml_text)
        # Some YAMLs may be empty (None); represent deterministically
        if data is None:
            return ""
        normalized = yaml.safe_dump(
            data,
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
        )
        return normalized.strip()
    except Exception:
        # Fallback: trim leading/trailing whitespace and collapse multiple blank lines
        # This ensures we are at least robust to pure whitespace edits.
        collapsed = re.sub(r"\n\s*\n+", "\n", yaml_text.strip())
        return collapsed


def compute_sha256(text: str) -> str:
    """
    Compute SHA-256 hash in hexadecimal for the given text.
    """
    sha = hashlib.sha256()
    sha.update(text.encode("utf-8"))
    return sha.hexdigest()


def _extract_front_matter(md: str) -> Tuple[Dict[str, Any], int]:
    """
    Extract YAML front matter from the top of a Markdown string.
    Returns (front_matter_dict, end_index_of_front_matter_block).
    If no front matter exists, returns ({}, 0).
    """
    if not md.lstrip().startswith("---"):
        return {}, 0

    # Find the first '---' after the opening line that closes the front matter.
    # We only consider front matter at the very start (ignoring leading whitespace).
    start = md.find("---")
    if start != 0:
        # If there's leading whitespace before '---', strip it and retry simply
        stripped = md.lstrip()
        if not stripped.startswith("---"):
            return {}, 0
        md = stripped
        start = 0

    # Find the closing delimiter
    # The closing '---' must occur after the initial line break
    next_delim_idx = md.find("\n---", 3)
    if next_delim_idx == -1:
        return {}, 0

    fm_block = md[4:next_delim_idx]  # content after first '---\n' up to '\n---'

    fm = yaml.safe_load(fm_block)
    if isinstance(fm, dict):
        return fm, next_delim_idx + 4  # include trailing '---\n'
    return {}, next_delim_idx + 4


def should_regenerate(
    latest_doc: Optional[str],
    input_hash: str,
    prompt_hash: str,
) -> bool:
    """
    Decide whether we should regenerate based on the latest_doc's front matter hashes.
    Returns True if:
      - no latest_doc is present
      - or either input_yaml_sha256 or prompt_sha256 differs
    """
    if not latest_doc:
        return True

    front_matter, _ = _extract_front_matter(latest_doc)
    prev_input = str(front_matter.get("input_yaml_sha256", "")).strip()
    prev_prompt = str(front_matter.get("prompt_sha256", "")).strip()

    if prev_input != input_hash:
        return True
    if prev_prompt != prompt_hash:
        return True
    return False


def render_prompt(merged_template: str, input_yaml: str) -> str:
    """
    Substitute the YAML input into the merged template.
    """
    return merged_template.replace("{input_yaml}", input_yaml)


def call_openai(markdown_prompt: str, model: str) -> str:
    """
    Call OpenAI to generate Markdown given a markdown_prompt.
    This function expects OPENAI_API_KEY to be available in the environment.

    Note: We avoid importing OpenAI types at module import time to keep mypy/ruff happy
    when OpenAI isn't installed in the environment (tests will mock this function).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")

    # Try the modern Responses API; fall back to Chat Completions if unavailable
    client = OpenAI(api_key=api_key)
    try:
        # Newer SDK (Responses API)
        resp = client.responses.create(
            model=model,
            input=markdown_prompt,
        )
        # The text can be located in multiple places; normalize to a single string.
        # Prefer output_text if present; otherwise join all text segments.
        text: Optional[str] = getattr(resp, "output_text", None)
        if text is None:
            # Fallback: try flattening content if output_text isn't available
            text = str(resp)
        return text
    except Exception:
        # Older SDK (Chat Completions)
        chat = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": markdown_prompt}],
        )
        if chat and chat.choices and chat.choices[0].message:
            return chat.choices[0].message.content or ""
        return ""


def _yaml_dump_front_matter(meta: Dict[str, Any]) -> str:
    """
    Serialize a small dict to YAML front matter text.
    - Prefer PyYAML if available
    - Otherwise write a minimal, safe subset
    """
    return yaml.safe_dump(
        meta,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    ).strip()


def wrap_with_front_matter(body_md: str, meta: Dict[str, Any]) -> str:
    """
    Wrap the given Markdown body with YAML front matter. The front matter should include:
      - taxonomy_version: str (set to a placeholder before storage)
      - input_yaml_sha256: str
      - prompt_sha256: str
      - model: str
      - created_at: iso8601
    """
    if "created_at" not in meta:
        meta["created_at"] = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    if "taxonomy_version" not in meta:
        meta["taxonomy_version"] = "TBD"
    fm = _yaml_dump_front_matter(meta)
    return f"---\n{fm}\n---\n\n{body_md.strip()}\n"


__all__ = [
    "DEFAULT_MERGED_TEMPLATE",
    "read_yaml_text",
    "_normalize_yaml_for_hash",
    "compute_sha256",
    "should_regenerate",
    "render_prompt",
    "call_openai",
    "wrap_with_front_matter",
    "store_generated",
]
