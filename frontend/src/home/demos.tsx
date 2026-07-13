import type { ReactNode } from "react";
import { DemoBubble } from "@penny/ui";
import type { home } from "./copy";

/** Placeholder demo conversations (from design-reference), keyed by feature
 *  id. Content-only — the words/numbers are expected to iterate with copy.ts.
 *  Keyed by the copy's own id union so renaming a feature there without
 *  updating its demo is a compile error, not an empty panel in prod. */
export const demos: Record<(typeof home.features)[number]["id"], ReactNode> = {
  analyze: (
    <>
      <DemoBubble role="user">Where did my spending surge last year, and why?</DemoBubble>
      <DemoBubble role="penny">
        Three months broke your ~$4.1k baseline:
        <table>
          <thead>
            <tr><th>Month</th><th>Spend</th><th>Driver</th></tr>
          </thead>
          <tbody>
            <tr><td>Sep</td><td>$5,900</td><td>Italy trip ($1,930 flights+hotels)</td></tr>
            <tr><td>Dec</td><td>$7,200</td><td>Gifts $1,900 + holiday travel $900</td></tr>
            <tr><td>Mar</td><td>$5,400</td><td>MacBook Pro $2,000 + $620 dental</td></tr>
          </tbody>
        </table>
        All three are <b>one-offs</b>, not a lifestyle shift — your recurring baseline held steady.
        The one to watch is Dec; it repeats every year.
      </DemoBubble>
    </>
  ),
  project: (
    <>
      <DemoBubble role="user">Net worth in 5 years — keep renting vs. buy a $750k house?</DemoBubble>
      <DemoBubble role="penny">
        Modeling 20% down, 6.75% 30-yr, 4% appreciation, 7% market return:
        <table>
          <thead>
            <tr><th>Path</th><th>Net worth, yr 5</th></tr>
          </thead>
          <tbody>
            <tr><td>Rent + invest</td><td>~$600k</td></tr>
            <tr><td>Buy $750k</td><td>~$540k</td></tr>
          </tbody>
        </table>
        Counter-intuitively, <b>renting edges ahead over 5 years</b> — $169k in upfront cash and the
        higher carry compound faster than equity + appreciation. The lines cross around{" "}
        <b>year 8</b>, after which buying pulls ahead. Illustrative; not tax advice.
      </DemoBubble>
    </>
  ),
  budget: (
    <>
      <DemoBubble role="user">Budget from my 12-mo averages, tightened 10%.</DemoBubble>
      <DemoBubble role="penny">
        Discretionary lines cut 10%, essentials held:
        <table>
          <thead>
            <tr><th>Category</th><th>12-mo avg</th><th>Target</th></tr>
          </thead>
          <tbody>
            <tr><td>Travel</td><td>$720</td><td>$648</td></tr>
            <tr><td>Groceries</td><td>$625</td><td>$563</td></tr>
            <tr><td>Restaurants</td><td>$430</td><td>$387</td></tr>
            <tr><td>Shopping</td><td>$410</td><td>$369</td></tr>
            <tr><td>Delivery</td><td>$250</td><td>$225</td></tr>
          </tbody>
        </table>
        New target: <b>$4,170/mo</b>, down from $4,636. That's ~$5,600/yr redirected. Want me to go
        conservative (15%) on the discretionary lines only?
      </DemoBubble>
    </>
  ),
  forecast: (
    <>
      <DemoBubble role="user">Forecast my cash flow to year-end. Any tight months?</DemoBubble>
      <DemoBubble role="penny">
        Projecting income, every recurring bill, and seasonal patterns against your $48k liquid
        buffer:
        <table>
          <thead>
            <tr><th>Month</th><th>Proj. liquid low</th></tr>
          </thead>
          <tbody>
            <tr><td>Sep</td><td>$14.2k</td></tr>
            <tr><td>Nov</td><td>$12.1k</td></tr>
            <tr><td>Dec</td><td><b>$8.6k ⚠</b></td></tr>
          </tbody>
        </table>
        <b>December</b> is the pinch: holiday spend collides with your $1,400 annual auto-insurance
        renewal. Moving that renewal to autopay in Jan, or pre-funding $1.5k in Nov, keeps you above
        your $10k line.
      </DemoBubble>
    </>
  ),
  trends: (
    <>
      <DemoBubble role="user">Where's lifestyle creep showing up, YoY?</DemoBubble>
      <DemoBubble role="penny">
        Discretionary is up <b>11% YoY</b> vs ~3% inflation — so ~8% real creep. The recurring
        offenders:
        <table>
          <thead>
            <tr><th>Category</th><th>YoY</th></tr>
          </thead>
          <tbody>
            <tr><td>Delivery</td><td>+31%</td></tr>
            <tr><td>Subscriptions</td><td>+22%</td></tr>
            <tr><td>Restaurants</td><td>+18%</td></tr>
          </tbody>
        </table>
        These are <b>baseline shifts every month</b>, not one-time bumps — three new subscriptions
        and a steady DoorDash climb. That's where the discipline pays off.
      </DemoBubble>
    </>
  ),
  optimize: (
    <>
      <DemoBubble role="user">Get me to $40k in 24 months. What do I cut, least painful first?</DemoBubble>
      <DemoBubble role="penny">
        You need <b>$1,667/mo</b>. You already net ~$1,450 surplus — so we need ~$220 more, ranked
        by pain:
        <table>
          <thead>
            <tr><th>Cut</th><th>+ / mo</th></tr>
          </thead>
          <tbody>
            <tr><td>2 unused subscriptions</td><td>$54</td></tr>
            <tr><td>Coffee: 2 fewer shop visits/wk</td><td>$50</td></tr>
            <tr><td>Delivery −40%</td><td>$100</td></tr>
            <tr><td>Trim shopping</td><td>$60</td></tr>
          </tbody>
        </table>
        That's <b>$264/mo</b> from the four least-painful moves — target met with room to spare,
        without touching travel or restaurants.
      </DemoBubble>
    </>
  ),
};
