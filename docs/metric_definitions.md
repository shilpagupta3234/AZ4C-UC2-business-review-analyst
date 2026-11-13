# Saffron Trail Foods: Metric Definitions

**Owner:** Financial Planning & Analysis · **Version:** 3.1 · **Applies to:** all management and board reporting

These are the only approved definitions. If a number in a report does not follow them, the report is wrong.

## M1. Gross sales
List price × quantity, before any discount.

## M2. Discounts
Everything taken off gross sales on the invoice: trade discounts by channel and promotional discounts. Stored per order line as `discount_amount`.

## M3. Net revenue
Order-line net revenue (gross sales minus discounts) **minus refunds for returns**.

- Order-line net revenue counts in the month of the **order date**.
- Refunds count in the month of the **return date**, not the month of the original order. A July order returned in August reduces August net revenue.
- A region's net revenue uses the region recorded on the order.

## M4. Net cost of goods sold (COGS)
Order-line COGS (month of order) minus COGS reversed on returns (month of return).

- Returns that come back saleable (reasons `unsold` and `short expiry`) are restocked, so their cost is reversed.
- Returns that come back **damaged** are written off. Their cost is **not** reversed (`cogs_reversed` is zero), so a damaged return reduces revenue but leaves the cost in.

## M5. Gross margin %
(Net revenue − Net COGS) ÷ Net revenue × 100, to 2 decimal places.

**When anyone in the business says "margin" without another word, they mean gross margin % as defined here.**

## M6. Contribution margin
Net revenue − Net COGS − freight cost. Freight cost is recorded per order (`freight_cost`) and counts in the month of the order.

## M7. Revenue against target
Actual net revenue (M3) compared with `revenue_target` for the same region and calendar month. Report the gap in rupees and as a percentage of target.

## M8. Promotion cost
The promotional part of discounts on orders placed during a promotion, in that promotion's region. Trade discounts by channel are not promotion cost.

*Synthetic and fictional data.*
