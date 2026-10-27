# Wildcat Capital Data Cleaning Report

**To:** Wildcat Capital Portfolio Committee
**Re:** Audit and cleaning of the 2020 to 2024 warehouse extract (8 tables)

## Executive summary

The extract is now structurally ready for BI work, but it is not proven accurate.

**What improved.** Every nonblank transaction security ID was stored as text like `45.0`, so 0 of 197,175 trades, sales and dividends could join to the security table. After cleaning, all 13 relationships match 100% of eligible nonblank keys, and all assessable hard and inferred rule checks pass.

To get there, I changed 198,256 original cell values and logged each one; the six added flag columns are separate. I quarantined, not deleted, 25 probable duplicate clients and 200 transactions with no matching client.

**What still limits use.**

- 75 clients (3.0%) have no risk profile.
- Advisory Fee transactions and billed fees agree in only 1 of 28,746 matched client-months.
- Some returns, balances and dates look unusual and cannot be reliably corrected from the available extract.

## Cleaning summary

| Action | Table | Rows | Verification |
|---|---|---:|---|
| Quarantine probable duplicate clients | dim_client | 25 | Equal except ID and last name; one ID per pair has activity |
| Quarantine transactions with no client | fact_transactions | 200 | $10,888,495.37, restorable |
| Standardize `45.0` security IDs | fact_transactions | 197,044 | Every nonblank ID matches dim_security |
| Make negative Buy shares positive | fact_transactions | 835 | Reconcile within $0.01 after ignoring the sign |
| Convert `9.28%` returns to decimals | fact_portfolio_snapshot | 300 | Reconcile to benchmark and alpha only after dividing by 100 |
| Standardize full state names | dim_client | 77 | All 2-letter codes |
| Add flag columns | 4 tables | 6 | Five review flags plus one marking corrected Buys; flags change no values |

| Measure | Raw | Clean |
|---|---:|---:|
| Clients / transactions | 2,525 / 298,772 | 2,500 / 298,572 |
| Security ID / client match (transactions) | 0.0% / 99.933% | 100% / 100% |
| dim_client cell completeness | 99.785% | 99.786% |
| Clients missing a risk profile | 76 (3.01%) | 75 (3.0%) |
| Primary-key uniqueness | 100% | 100% |

These measures need context:

- **Completeness.** The 75 blank profiles are a tiny share of 35,000 client cells, so cell completeness barely moves. By client, 3.0% still lack a profile.
- **Key uniqueness.** Primary keys were already unique, because the duplicate clients had different IDs. A separate near-duplicate check is what found them.

## Key judgment calls

**1. Quarantining 25 probable duplicate clients.**

- *Evidence:* each pair matched on every column except ID and last name, including the opening balance to the cent. The names differed only by truncation or extension (Jacobson/Jacobso). One ID per pair had 158 to 295 activity rows; the other had none.
- *Decision:* I kept the ID that owns the history, so clients are not double-counted.
- *Risk:* these are probable duplicates, not confirmed identities, and the kept spelling is unverified. In two pairs the removed copy had the longer name (Pace/Pacen, Lee/Leen).

**2. Correcting 835 negative Buy share counts.**

- *Evidence:* all 836 raw negative Buys reconciled within the $0.01 tolerance after ignoring the sign. One was a quarantined orphan.
- *Decision:* I made the other 835 share counts positive. The positive-shares rule is inferred: every amount is positive, and every Sell reconciles with positive shares.
- *Risk:* a reversed trade would overstate holdings, so `shares_sign_corrected_flag` lets analysts exclude these rows.

**3. Leaving 75 risk profiles blank.**

- *Evidence:* these clients all use benchmark 3, like Balanced clients.
- *Decision:* I left the profiles blank and flagged them. A risk profile is a suitability fact, and the benchmark may be a system default.
- *Risk:* risk-profile reports show an unknown group of about 3%.

**4. Keeping the two fee sources separate.**

- *Evidence:* the two sources agree in 1 of 28,746 matched client-months and fail in 28,745. Billed fees (fact_fees) reconcile to AUM × rate and to snapshot AUM in all 122,197 fee months.
- *Decision:* the cause is unknown, so I changed neither table and kept this check out of every quality score.
- *Risk:* someone could combine the measures. fact_fees is the internally reconciled billed-fee measure, not verified recognized revenue.

## Limitations for BI

- **Consistency is not accuracy.** 100% results mean the tables agree with each other and the rules, not that every value is true.
- **Fees.** Never combine the two fee sources. 7,350 snapshot months have no fee row, so fees are understated if those bills are missing rather than waived.
- **Review flags (they change no values).** 2,440 snapshots have a return or alpha outside an assumed band. 420 snapshots and 386 fee rows show exactly $1,000.00 AUM. 2,410 inactive-client transactions fall after the client's last snapshot. Dashboards should state whether flagged rows are included.
- **Findings with no flag column.** In the validation reports only, the IQR check marks 251 clients and 6,257 transactions as unusually large for their group, which is unusual, not wrong. Also, 40,630 of 143,218 clean Buys and Sells are dated on weekends. The date table's trading-day column shows this but treats weekday holidays as trading days, so day-of-week analysis is unreliable.
- **Dividends.** What shares mean on Dividend rows is unresolved. An exploratory holdings comparison could not confirm or disprove dividend values, since opening positions, transfers, reinvestments and corporate actions are missing.
- **Loading.** Load ZIP codes and the certification value `None` as text.

---

AI-assisted report — reviewed for factual accuracy on 10/26/2026 by Santos Gunningham
