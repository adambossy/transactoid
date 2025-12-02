---
created_at: '2025-12-02T14:05:03.889698+00:00'
input_yaml_sha256: 3ab4c2383c4f35a5627814fa86f82397fca68eb418b0791d11e7f3420285e23b
model: gpt-5
prompt_sha256: 485deb653757a7b6205811837345c0155034480d6a58edbe78715220f5e18042
taxonomy_version: TBD
---

## Proposed 2-Level Personal Finance Transactions Taxonomy (v1)

### Overview
- Scope: A practical two-level taxonomy for classifying personal finance transactions across income, spending, savings/investing, loans, taxes, and non-spend bank movements.
- Goals: Make categorization consistent and user-friendly for budgeting, insights, automation, and reporting. Minimize overlap, reduce double-counting, and align with how users think about money.
- Coverage: Broad coverage of typical inflows and outflows with focused granularity at level 2. Exactly two levels: top-level category → optional sub-category.
- Organizing logic: Conceptual hierarchy that mirrors real-world intents (earn, live, move, maintain, grow, give), with a global decision order to resolve edge cases and overlaps.

### Top-Level Categories
- Income — Money you receive that increases your balance.
- Housing & Utilities — Costs to live in and run your home.
- Food & Dining — Consumable food and beverage purchases.
- Transportation & Auto — Moving yourself and operating vehicles (excluding insurance/loans).
- Health & Wellness — Out-of-pocket health and wellbeing spend (premiums excluded).
- Insurance — Recurring premiums for risk coverage.
- Debt & Loans — Payments and charges tied to credit cards and loans (non-mortgage).
- Savings & Investments — Contributions, trades, and investment fees (investment income under Income).
- Shopping & Personal Care — Non-food consumer goods and services for personal/household use.
- Entertainment & Subscriptions — Media, hobbies, digital content, and subscriptions.
- Education & Childcare — Learning and dependent care costs.
- Travel — Spend specifically tied to trips away from home.
- Gifts & Donations — Money given without direct goods/services returned.
- Taxes & Government — Taxes, fines, and official fees to government entities.
- Banking Movements (Transfers, Refunds & Fees) — Non-spend movements and bank-level adjustments.
- Pets — All pet-related goods and services (excluding pet insurance).
- Wedding — Wedding-specific spend; use as a dedicated project category.
- Work Expenses — Out-of-pocket work spending and reimbursable costs.
- Other — For rare items that don’t fit elsewhere; use sparingly.
- Unknown — Temporary holding when the merchant or purpose is unclear.

### Global Rules & Overlap Resolution
- Hierarchy depth: Exactly two levels (parent → child). No deeper nesting.
- Decision order (apply in this sequence):
  1) Banking Movements (transfers, refunds, bank fees, corrections)
  2) Income (salary, benefits, gifts received, interest/dividends, tax refunds)
  3) Debt & Loans (loan/card payments; card interest/fees)
  4) Insurance (all premiums), then Taxes & Government (taxes, government fees/fines)
  5) Savings & Investments (contributions, buys/sells, investment fees)
  6) Domain spend: Housing → Food → Transport → Health → Shopping → Entertainment → Education → Travel → Pets → Gifts
  7) Special project/label categories: Work Expenses, Wedding (use when intentionally tracking the project; otherwise classify by purchase type)
  8) Other → Unknown (last resort; temporary)
- Overlap resolution:
  - Refunds: Merchant refunds → Banking Movements → Refund/Chargeback (do not classify as negative spend).
  - P2P (Venmo, Zelle, PayPal): If memo clearly indicates purpose, classify to that purpose; otherwise Banking Movements → Transfer: External (P2P).
  - Mortgage vs Debt: Mortgage Payment stays under Housing & Utilities to reflect “cost of living.”
  - Travel vs everyday categories: If you want trip rollups, use Travel sub-categories for on-trip spend (including car rentals and meals). Otherwise keep under everyday categories and tag the trip; be consistent.
  - Lodging vs Hotels: Prefer Travel → Lodging for any accommodation (including hotels). Travel → Hotels may be used if your feed distinctly separates hotels, but avoid double use.
  - EV charging: Use Transportation & Auto → EV Charging for pay-per-charge networks; home charging on your electric bill stays under Housing & Utilities → Electricity unless separately metered.
  - Home Decor vs Furniture: Small decor→ Housing & Utilities → Home Decor; furniture/appliances → Shopping & Personal Care → Furniture & Appliances.
  - Supplements vs Wellness Products: Vitamins/supplements → Health & Wellness → Supplements; thermometers, OTC devices, etc. → Wellness Products.
  - Mental Health vs Therapy: If mental health-specific, prefer Mental Health; general counseling can use Therapy. If both appear, use the more specific Mental Health.
  - Rental car: Everyday/local use → Transportation & Auto → Rental Car. On a trip → Travel → Local Transport.
  - Sales tax: Keep embedded with the purchase. Only use Taxes & Government → Sales/Use Tax (Standalone) if posted as its own transaction.
- Exclusions:
  - Do not split mortgage payments into principal/interest/escrow in day-to-day classification.
  - Do not double-count credit card purchases and subsequent card payments.
  - Cash withdrawals are not “spend.” If later data supports cash categorization, tag that separately.
  - Employer reimbursements paid as refunds from the original merchant → Banking Movements → Refund/Chargeback; P2P reimbursements → Banking Movements → Transfer: External (P2P) or Income → Gifts Received if explicitly a gift.

---

### Category Definitions

<details>
<summary><strong>1) Income</strong></summary>

Definition: Money received that increases your balance (earned or unearned).

Sub-categories
- Salary & Wages — Regular pay from employment.
  - Examples: biweekly payroll deposit; W-2 paycheck; hourly wage direct deposit.
  - Excludes: bonuses/commissions → Bonus & Commission; tips → Tips.
- Bonus & Commission — Variable compensation from employment.
  - Examples: annual bonus; sales commission; referral bonus from employer.
  - Excludes: customer gratuities → Tips.
- Tips — Gratuities paid by customers or pooled tip outs.
  - Examples: card tip payout; cash tips deposited; tip share from shift.
  - Excludes: payments for services/products you sold → Self-Employment & Side Hustle.
- Self-Employment & Side Hustle — Business income paid to you personally.
  - Examples: freelance invoice paid; Etsy/Square payout; rideshare/food delivery payout.
  - Excludes: merchant refunds → Banking Movements → Refund/Chargeback.
- Government Benefits — Income from public programs.
  - Examples: Social Security; unemployment; disability benefits; SNAP cash credits.
  - Excludes: tax refunds → Tax Refunds.
- Interest & Dividends — Passive income from deposits or investments.
  - Examples: savings account interest; bond interest; ETF dividend.
  - Excludes: trading proceeds → Savings & Investments → Investment Sell/Withdrawal.
- Tax Refunds — Income tax refunds from government.
  - Examples: IRS refund; state return refund; amended return refund.
  - Excludes: merchant chargebacks → Banking Movements → Refund/Chargeback.
- Gifts Received — Monetary gifts received from individuals.
  - Examples: birthday cash; family transfer labeled “gift.”
  - Excludes: payments for goods/services you provided → categorize by purpose.

</details>

<details>
<summary><strong>2) Housing & Utilities</strong></summary>

Definition: Ongoing costs to live in and maintain a primary residence.

Sub-categories
- Rent — Payments to landlord or rental platform.
  - Examples: monthly rent; property management ACH; rent via online portal.
  - Excludes: security deposit moves → Banking Movements (transfer/refund as applicable).
- Mortgage Payment — Monthly mortgage payment (principal+interest+escrow together).
  - Examples: bank auto-draft; mortgage servicer ACH.
  - Excludes: property tax paid separately → Taxes & Government → Property Tax.
- HOA/Condo Fees — Recurring dues to associations.
  - Examples: HOA monthly fees; condo association dues; special assessments (still here).
- Electricity — Residential electric utility.
  - Examples: local power utility autopay; separate EV circuit billed with home power.
  - Excludes: public EV charging → Transportation & Auto → EV Charging.
- Gas — Residential natural gas utility.
  - Examples: gas utility bill; heating gas charge.
- Water & Sewer — Municipal or private water/sewer charges.
  - Examples: city utilities water/sewer bill.
- Trash & Recycling — Waste and recycling services.
  - Examples: municipal trash; private hauler bill.
- Internet — Home broadband.
  - Examples: cable/fiber ISP; modem rental bundled.
  - Excludes: mobile cellular plans → Mobile Phone.
- Mobile Phone — Wireless service plans and add-ons.
  - Examples: AT&T/Verizon/T-Mobile bill; family plan charges.
  - Excludes: device financing → Debt & Loans → Personal/BNPL Loan Payment; device purchased outright → Shopping & Personal Care → Electronics & Gadgets.
- Home Services & Maintenance — Cleaning, repairs, lawn, pest, handyman.
  - Examples: plumber; HVAC repair; house cleaner; landscaping; pest control.
  - Excludes: major remodels → Home Renovation; homeowners insurance → Insurance.
- Home Renovation — Material/labor for significant upgrades or remodels.
  - Examples: kitchen remodel; roof replacement; new windows; contractor draws.
  - Excludes: decor and small fixes → Home Services & Maintenance or Home Decor.
- Home Decor — Decorative home goods and minor aesthetic updates.
  - Examples: wall art; curtains; lamps; throw pillows.
  - Excludes: furniture/appliances → Shopping & Personal Care → Furniture & Appliances.

</details>

<details>
<summary><strong>3) Food & Dining</strong></summary>

Definition: Consumable food and beverage purchases.

Sub-categories
- Groceries — Supermarkets, warehouse clubs, grocery delivery as groceries.
  - Examples: Costco; Kroger; Instacart groceries.
  - Excludes: restaurant meals → Restaurants; liquor-only → Bars & Alcohol.
- Restaurants — Sit-down or counter-service meals consumed as meals.
  - Examples: dine-in restaurants; fast-casual; food courts.
  - Excludes: pure bars → Bars & Alcohol; delivery platforms → Delivery & Takeout.
- Treats — Dessert/snack shops that are not full meals.
  - Examples: ice cream; frozen yogurt; smoothie bars; bakeries.
  - Excludes: coffee-focused → Coffee Shops.
- Coffee Shops — Cafes and coffee chains.
  - Examples: Starbucks; local cafe; espresso bar.
  - Excludes: pastry-only shops → Treats.
- Delivery & Takeout — Food platforms and restaurant delivery/takeout orders.
  - Examples: DoorDash; Uber Eats; pizza delivery; pickup orders.
  - Excludes: refunded service fees → Banking Movements → Refund/Chargeback.
- Meal Kits — Subscription or recurring meal-prep kits.
  - Examples: HelloFresh; Blue Apron; Home Chef.
  - Excludes: one-off groceries → Groceries.
- Bars & Alcohol — Bars, pubs, liquor stores, wine shops.
  - Examples: bar tab without significant food; bottle shop; wine club pickup.
  - Excludes: wine/beer subscriptions with streaming/bundles → Entertainment & Subscriptions when clearly content-driven.

</details>

<details>
<summary><strong>4) Transportation & Auto</strong></summary>

Definition: Moving yourself and operating vehicles (excluding insurance and loan payments).

Sub-categories
- Fuel — Gasoline/diesel for vehicles.
  - Examples: Shell; Exxon; Costco fuel.
  - Excludes: EV public charging → EV Charging.
- EV Charging — Pay-per-use EV charging networks.
  - Examples: Electrify America; ChargePoint; Supercharger (network billing).
  - Excludes: home EV charging on home electric bill → Housing & Utilities → Electricity.
- Public Transit — Mass transit fare and passes.
  - Examples: subway/bus cards; commuter rail; ferries.
- Rides & Taxis — Ride-hailing and taxis.
  - Examples: Uber; Lyft; traditional taxi.
  - Excludes: airport shuttles while on a trip → Travel → Local Transport (if using Travel scheme).
- Parking & Tolls — Garages, meters, tolls.
  - Examples: city parking meter; toll transponder; event parking lot.
  - Excludes: tickets/fines → Taxes & Government → Fines & Tickets.
- Auto Service & Parts — Vehicle maintenance and parts.
  - Examples: oil change; tires; brake service; wiper blades.
- Car Wash & Detailing — Standalone wash/detail services.
  - Examples: automated wash; hand wash; full detail.
- Rental Car — Car rentals for local use or non-trip situations.
  - Examples: local weekend rental; test drives; replacement rentals.
  - Excludes: car rentals while traveling → Travel → Local Transport.

</details>

<details>
<summary><strong>5) Health & Wellness</strong></summary>

Definition: Out-of-pocket health and wellness spending (premiums under Insurance).

Sub-categories
- Doctor & Hospital — Office visits, urgent care, inpatient/outpatient services.
  - Examples: specialist copays; surgery fees; imaging centers.
  - Excludes: insurance premiums → Insurance → Health Insurance.
- Pharmacy & Prescriptions — Prescription copays and pharmacy purchases.
  - Examples: Rx pickup; pharmacy-processed vaccines.
  - Excludes: general toiletries → Shopping & Personal Care → Beauty & Personal Care.
- Dental — Cleanings, fillings, orthodontics, periodontics.
  - Examples: dental exam; braces; root canal.
- Vision — Exams, glasses/contacts, LASIK.
  - Examples: optometrist visit; frames; contact lenses.
- Mental Health — Counseling, psychiatry, therapy specific to mental health.
  - Examples: psychologist sessions; psychiatrist copays; teletherapy.
  - Excludes: general life coaching → Therapy (if not healthcare).
- Fitness & Gym — Gyms, studios, fitness classes/apps.
  - Examples: gym membership; yoga studio; Peloton app.
- Wellness Products — OTC health goods and devices.
  - Examples: thermometers; first-aid kits; heating pads; OTC meds.
  - Excludes: vitamins/supplements → Supplements.
- Medical — General medical expenses not covered by other medical sub-categories.
  - Examples: medical equipment; lab fees; durable medical equipment.
- Supplements — Vitamins and dietary supplements.
  - Examples: multivitamins; protein powder; omega-3s.
- Therapy — Non-medical counseling/coaching services.
  - Examples: couples counseling; life coach.
  - Excludes: clinical mental health care → Mental Health.

</details>

<details>
<summary><strong>6) Insurance</strong></summary>

Definition: Recurring premiums for personal risk coverage.

Sub-categories
- Health Insurance — Medical/dental/vision insurance premiums paid out of pocket.
  - Examples: marketplace premiums; COBRA; standalone dental/vision plans.
- Auto Insurance — Vehicle insurance premiums.
  - Examples: six-month policy premium; monthly auto policy charge.
- Home/Renters Insurance — Homeowners or renters policy premiums.
  - Examples: HO-3 premium; renters insurance.
- Flood Insurance — Flood policy premiums.
  - Examples: NFIP or private flood policy.
- Life & Disability Insurance — Term life, whole life, long/short-term disability.
  - Examples: term-life premium; LTD policy.
- Pet Insurance — Pet medical policy premiums.
  - Examples: monthly pet health plan.
- Travel Insurance — Trip insurance premiums.
  - Examples: single-trip policy; annual travel medical policy.

</details>

<details>
<summary><strong>7) Debt & Loans</strong></summary>

Definition: Payments and charges tied to credit cards and loans (non-mortgage).

Sub-categories
- Credit Card Interest & Fees — Interest, annual fees, late fees on credit cards.
  - Examples: monthly interest; annual fee; late fee; foreign transaction fees.
  - Excludes: card payment itself → Banking Movements → Credit Card Payment.
- Student Loan Payment — Payments to student loan servicers.
  - Examples: federal loan payment; private student loan autopay.
- Auto Loan Payment — Car loan payments.
  - Examples: monthly auto loan ACH.
  - Excludes: auto insurance → Insurance → Auto Insurance.
- Personal/BNPL Loan Payment — Personal loans and buy-now-pay-later installments.
  - Examples: Affirm/Klarna/Afterpay installments; bank personal loan payment.
- Loan Fees & Adjustments — Origination fees, deferment/forbearance charges, other loan adjustments.
  - Examples: origination fee debit; payment processing fee from lender.

</details>

<details>
<summary><strong>8) Savings & Investments</strong></summary>

Definition: Building assets via saving and investing; includes related fees. Investment income lives under Income.

Sub-categories
- Savings Contribution — Transfers into savings/high-yield accounts.
  - Examples: recurring savings move; emergency fund transfer.
  - Excludes: lateral checking-to-checking moves → Banking Movements → Transfer: Own Accounts.
- Retirement Contribution — IRA/401(k)/Roth contributions visible in the feed.
  - Examples: IRA contribution from checking; SEP contribution.
- Investment Buy — Purchases of stocks/ETFs/funds/crypto.
  - Examples: brokerage buy order; recurring ETF buy; crypto purchase.
- Investment Sell/Withdrawal — Proceeds from selling investments or withdrawing funds.
  - Examples: stock sale proceeds to bank; brokerage cash withdrawal.
- Investment Fees & Commissions — Advisory, trading, platform fees.
  - Examples: trade commission; advisory fee; robo-advisor fee.
- 529/Other Long-Term Savings — Education or other earmarked long-horizon accounts.
  - Examples: 529 plan contribution; HSA transfers if treated as savings.

</details>

<details>
<summary><strong>9) Shopping & Personal Care</strong></summary>

Definition: Non-food consumer goods and personal services for you or your household.

Sub-categories
- Clothing & Accessories — Apparel, shoes, jewelry.
  - Examples: sneakers; winter coat; watch; handbag.
  - Excludes: costumes for production reimbursed by employer → Work Expenses.
- Household Supplies — Consumables and cleaning supplies.
  - Examples: paper towels; detergent; trash bags.
  - Excludes: decor → Housing & Utilities → Home Decor.
- Electronics & Gadgets — Consumer electronics and accessories.
  - Examples: phone; tablet; headphones; chargers; smart home devices.
- Furniture & Appliances — Home furnishings and appliances (small or major).
  - Examples: sofa; bed frame; washer/dryer; microwave.
  - Excludes: built-in remodel fixtures → Housing & Utilities → Home Renovation.
- Beauty & Personal Care — Cosmetics, hair, spa, toiletries.
  - Examples: shampoo; skincare; salon services; spa treatments.
- Postage & Shipping — Retail postage and shipping services.
  - Examples: USPS postage; UPS/FedEx counter charges; mailbox rental.
- Dry Cleaning — Dry cleaning and garment care.
  - Examples: suit dry cleaning; alterations if billed by cleaner.
  - Excludes: tailoring for wedding attire → Wedding (optional; see guidance).

Excludes: gifts for others → Gifts & Donations; books/apps/media → Entertainment & Subscriptions.

</details>

<details>
<summary><strong>10) Entertainment & Subscriptions</strong></summary>

Definition: Media, digital content, hobbies/leisure, and subscription services.

Sub-categories
- Streaming Video — TV/video streaming services.
  - Examples: Netflix; Hulu; Disney+.
- Music & Audio — Music, audiobooks, podcasts platforms.
  - Examples: Spotify; Apple Music; Audible.
- Gaming — Games, DLC, in-app purchases, platform subscriptions.
  - Examples: Steam; Xbox Game Pass; mobile game IAPs.
- Books, Apps & Media — Ebooks, print books, app stores, media purchases.
  - Examples: Kindle books; App Store apps; movie purchases.
- News & Publications — Newspapers, magazines, professional journals.
  - Examples: NYT digital; magazine subscription.
- Hobbies & Leisure — Non-travel leisure activities and hobby supplies.
  - Examples: craft supplies; board games; local museum tickets; sports league fees.
- Cloud & Software Subscriptions — Storage, productivity, utility software subs.
  - Examples: iCloud; Google One; password manager; Adobe Creative Cloud.

</details>

<details>
<summary><strong>11) Education & Childcare</strong></summary>

Definition: Learning-related costs and care for dependents.

Sub-categories
- Tuition & School Fees — K–12, college, private school, program tuition.
  - Examples: university tuition; private school tuition; lab fees.
- Books & Supplies — Textbooks, school materials, uniforms if required by school.
  - Examples: textbooks; calculators; art supplies.
- Courses & Certifications — Continuing education, online courses, bootcamps.
  - Examples: Coursera; professional certification exam fee; coding bootcamp.
- Childcare & Babysitting — Daycare, sitters, after-school care.
  - Examples: daycare tuition; babysitter payment; nanny share.
- School Activities & Lunch — Clubs, field trips, lunch accounts.
  - Examples: PTA fees; field trip payment; school lunch top-up.

Excludes: student loan payments → Debt & Loans → Student Loan Payment.

</details>

<details>
<summary><strong>12) Travel</strong></summary>

Definition: Spend tied to trips away from home. Use Travel to group trip costs distinctly; otherwise classify under everyday categories and add a trip tag.

Sub-categories
- Flights — Airline tickets and seat fees.
  - Examples: airfare; seat selection fee; change fee.
- Lodging — All accommodations while traveling (hotels, rentals).
  - Examples: hotel stays; vacation rentals; hostels; resort fees.
- Local Transport — Transportation at destination, including car rentals.
  - Examples: airport shuttles; train passes; rental car during trip; rideshare at destination.
  - Excludes: routine/local rentals → Transportation & Auto → Rental Car.
- Travel Meals & Dining — Meals and drinks while traveling (if using Travel rollup).
  - Examples: airport meals; destination restaurants.
  - Excludes: if you keep meals under Food & Dining, do so consistently and tag the trip.
- Activities & Tours — Attractions, excursions, tickets on trip.
  - Examples: museum passes; guided tours; theme park tickets.
- Baggage/Other Travel Fees — Baggage, change, resort/amenity, visa service fees.
  - Examples: baggage fee; resort amenities fee; visa processing fee.
- Hotels — Hotel stays specifically (optional if using Lodging).
  - Examples: Marriott; Hilton; boutique hotel.
  - Guidance: Prefer Lodging for all accommodations to avoid split use. Use Hotels only if your data stream differentiates it and you need that distinction.

Excludes: travel insurance → Insurance → Travel Insurance.

</details>

<details>
<summary><strong>13) Gifts & Donations</strong></summary>

Definition: Money given to others without direct goods/services for you.

Sub-categories
- Gifts Given — Presents and cash gifts to individuals.
  - Examples: birthday gift; wedding cash envelope; holiday gifts.
  - Excludes: charitable donations → Charitable Donations.
- Charitable Donations — Donations to registered charities.
  - Examples: 501(c)(3) donation; foundation gift; charity fundraiser.
- Religious Giving — Tithes and offerings to religious organizations.
  - Examples: weekly tithe; holiday offering.
- Crowdfunding Support — Support for personal causes or non-product campaigns.
  - Examples: GoFundMe for medical bills; community support fund.
  - Excludes: crowdfunding to buy a product → Shopping & Personal Care or Entertainment depending on item.

</details>

<details>
<summary><strong>14) Taxes & Government</strong></summary>

Definition: Taxes, fines, and payments to government entities.

Sub-categories
- Federal Income Tax — Payments and estimates to IRS.
  - Examples: 1040 balance due; quarterly estimates; extension payment.
- State/Local Income Tax — Payments and estimates to state/local authorities.
  - Examples: state return payment; city tax payment; quarterly estimates.
- Property Tax — Real estate property taxes paid directly.
  - Examples: county tax bill; city property tax.
- Sales/Use Tax (Standalone) — Only when sales/use tax posts as its own transaction.
  - Examples: separate use tax payment to state.
  - Excludes: embedded sales tax → leave with the purchase category.
- DMV & Registration — Vehicle registration, licensing, and related fees.
  - Examples: registration renewal; driver’s license fee.
  - Excludes: parking meters/garages → Transportation & Auto → Parking & Tolls.
- Fines & Tickets — Government-issued penalties.
  - Examples: parking ticket; speeding ticket; toll violation.
- Customs & Duties — Import duties and customs fees.
  - Examples: international shipment duty; customs processing fee.

Excludes: tax refunds → Income → Tax Refunds.

</details>

<details>
<summary><strong>15) Banking Movements (Transfers, Refunds & Fees)</strong></summary>

Definition: Non-spend movements and bank adjustments. Apply these first when applicable.

Sub-categories
- Transfer: Own Accounts — Moves between your accounts (same owner).
  - Examples: checking ↔ savings; bank ↔ bank; internal credit union transfers.
  - Excludes: credit card payments → Credit Card Payment; investment contributions → Savings & Investments.
- Transfer: External (P2P) — Person-to-person transfers when purpose is unclear.
  - Examples: Venmo/Zelle/PayPal transfer without clear memo.
  - Guidance: If memo shows purpose (e.g., “rent”), reclassify to that category.
- Credit Card Payment — Payments from bank to card accounts.
  - Examples: monthly card payoff; statement autopay.
  - Excludes: card interest/fees → Debt & Loans → Credit Card Interest & Fees.
- Cash Withdrawal (ATM) — ATM cash withdrawals.
  - Examples: ATM cash out; branch cash withdrawal.
  - Excludes: ATM fee → Bank Fee/Service Charge.
- Cash Deposit — Depositing physical cash.
  - Examples: ATM cash deposit; branch cash deposit.
- Check Payment/Deposit — Paper or eCheck payments and deposits.
  - Examples: mailed check clearing; mobile check deposit.
- Refund/Chargeback — Merchant refunds, reversals of purchases.
  - Examples: returned merchandise refund; disputed charge reversal; subscription refund.
  - Guidance: Optionally net against the original categorized purchase if your system supports linking.
- Reversal/Correction — Bank error corrections and duplicate reversals.
  - Examples: duplicate transaction reversal; posting correction.
- Bank Fee/Service Charge — Bank-level fees and service charges.
  - Examples: monthly maintenance fee; overdraft fee; wire fee; out-of-network ATM fee.
  - Excludes: investment advisory/trading fees → Savings & Investments → Investment Fees & Commissions.

Excludes: interest earned → Income → Interest & Dividends.

</details>

<details>
<summary><strong>16) Pets</strong></summary>

Definition: Goods and services for household pets (excluding pet insurance premiums).

Sub-categories
- Adoption, Licensing & Microchipping — Initial pet acquisition and official fees.
  - Examples: shelter adoption fee; city pet license; microchipping service.
- Boarding & Daycare — Overnight boarding, daycare facilities.
  - Examples: kennel stays; doggy daycare.
- Food & Treats — Pet food and treats.
  - Examples: kibble; canned food; training treats.
- Grooming — Grooming services and supplies.
  - Examples: bath and cut; nail trim; grooming tools.
- Litter & Waste — Litter, waste bags, pads, disposal systems.
  - Examples: cat litter; dog waste bags; puppy pads.
- Medications & Preventives — Vet-prescribed meds and preventives.
  - Examples: flea/tick; heartworm meds; antibiotics.
- Supplies & Accessories — Collars, leashes, bowls, beds, toys.
  - Examples: crate; scratching post; travel carrier.
- Training & Behavior — Classes and behaviorists.
  - Examples: obedience classes; behavior consultation.
- Veterinary Care — Vet exams, procedures, tests.
  - Examples: vaccinations; dental cleanings; lab tests.
- Walking & Sitting — Pet sitters and dog walkers.
  - Examples: Rover/Walkers; neighborhood sitter.

Excludes: pet insurance → Insurance → Pet Insurance.

</details>

<details>
<summary><strong>17) Wedding</strong></summary>

Definition: Wedding-specific spending you want tracked as a dedicated project. Use when you prefer to aggregate all wedding costs; otherwise classify by purchase type and tag “Wedding.”

Sub-categories
- None (umbrella project category).
  - Examples: venue deposit; catering; photographer; attire alterations; invitations; officiant; favors; decorations.
  - Excludes: gifts to others → Gifts & Donations; travel for honeymoon → Travel.

</details>

<details>
<summary><strong>18) Work Expenses</strong></summary>

Definition: Out-of-pocket expenses for work that are not payroll-deducted. Use when you expect reimbursement or want to track work costs separately.

Sub-categories
- None (umbrella category).
  - Examples: conference registration; client meals; mileage tolls; software for work; certification exam for job.
  - Excludes: employer-paid corporate card charges (not in personal feed); salary deductions → not applicable; if refunded by merchant → Banking Movements → Refund/Chargeback.

Guidance: If reimbursed via P2P and unclear, use Banking Movements → Transfer: External (P2P) and tag as reimbursement.

</details>

<details>
<summary><strong>19) Other</strong></summary>

Definition: Rare, miscellaneous items that do not clearly fit elsewhere. Use sparingly and consider recategorization later.

Sub-categories
- None (catch-all).
  - Examples: unusual one-off services; experimental categories.
  - Excludes: anything that reasonably fits another category.

</details>

<details>
<summary><strong>20) Unknown</strong></summary>

Definition: Temporary placeholder when the merchant or purpose cannot be determined yet.

Sub-categories
- None (temporary holding).
  - Examples: truncated descriptors; unrecognized cash-like postings.
  - Guidance: Revisit and reclassify when additional details emerge.

</details>

---

### Edge Cases & Guidance
- Trip strategy: Choose either Travel (all on-trip spending) or everyday categories with a trip tag. Be consistent across the app.
- Merchant aggregators (Amazon, Walmart, Target):
  - If detailed line items are unavailable, default to Shopping & Personal Care. Split when known (e.g., Groceries + Household Supplies + Electronics).
  - If your system reconciles Amazon orders later, temporarily label “Amazon” and reconcile downstream.
- Credit card payments: Always Banking Movements → Credit Card Payment. Do not double-count underlying purchases.
- Sales tax: Keep embedded in the purchase category. Only use Sales/Use Tax (Standalone) if it posts separately.
- Refunds and reimbursements:
  - Merchant refunds → Refund/Chargeback.
  - Employer or friend reimbursements: If P2P and purpose is clear, reclassify to underlying category or use Work Expenses when appropriate; otherwise keep as Transfer: External (P2P).
- Mortgage escrow: Keep the full mortgage payment under Mortgage Payment; do not split in daily classification.
- Device purchases/financing:
  - Outright device purchase → Shopping & Personal Care → Electronics & Gadgets.
  - Financed device installments → Debt & Loans → Personal/BNPL Loan Payment.
  - Cellular service plan → Housing & Utilities → Mobile Phone.
- Car rentals:
  - On trip → Travel → Local Transport.
  - Local/one-off not tied to a trip → Transportation & Auto → Rental Car.
- Lodging vs Hotels (duplication management):
  - Prefer Travel → Lodging for all accommodations. Use Travel → Hotels only if your feed explicitly distinguishes hotels and you need the split; avoid using both for the same user simultaneously.
- Wellness overlap:
  - Mental health clinical care → Health & Wellness → Mental Health.
  - Non-clinical coaching → Health & Wellness → Therapy.
  - Supplements (vitamins) vs OTC devices/meds → Supplements vs Wellness Products.
- Splitting mixed purchases: Encourage splits (e.g., target run with groceries + household supplies). If splitting is not feasible, choose the dominant purpose.
- Income from investments:
  - Interest/dividends → Income → Interest & Dividends.
  - Trading proceeds → Savings & Investments → Investment Sell/Withdrawal.
  - Investment fees → Savings & Investments → Investment Fees & Commissions.
- Fines vs parking/tolls:
  - Parking meters/garages → Transportation & Auto → Parking & Tolls.
  - Tickets/violations → Taxes & Government → Fines & Tickets.
- Pets: All pet spend under Pets (not Shopping), except pet insurance → Insurance → Pet Insurance.
- Special projects:
  - Wedding and Work Expenses can override everyday categories when the intent is to manage the project budget. Otherwise classify by purchase type and add a project tag.
- Use Other and Unknown sparingly: Reclassify when clarity improves.
