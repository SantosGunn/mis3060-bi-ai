# Part D — Verification of AUM-Weighted Alpha

## Draft and setup

Claude received the three INFO.VIEW exports plus the monthly client/snapshot grain, balance additivity, YTD semantics and exact suspect-exclusion rule. Its full prompt and response are preserved in dax_session.md. The measure ran with the drafted calculation logic; no formula correction was needed. Percentage formatting was applied. Claude advised checking the date-table setting rather than assuming the metadata proved it. Power BI showed the setting was Off; dim_date was then marked using its date column.

## Test and independent reconciliation

The complete diagnostic query proposed in Claude's original response was not recorded as run. Instead, a saved-measure export query tested all 16 measures over ten slices (160 rows). The actual query and additional edge test are in dax_session.md. Independent pandas calculations were written before reading the Power BI export. The final run reported **Passed: 160; Failed: 0; Total: 160**.

The following rows, identified by measure=AUM-Weighted Alpha and the slice key, establish agreement on the requested contexts. Ratios below are raw decimals, not percentages.

| Slice | Power BI | Independent pandas | Match |
|---|---:|---:|---|
| Grand Total | 0.0144799468 | 0.01447994680056427 | True |
| Year=2022 | 0.0284940699 | 0.028494069910815337 | True |
| Year=2024\|Tier=HNW | 0.0139880428 | 0.01398804282685563 | True |
| Year=2024\|Tier=Retail | 0.0240410089 | 0.024041008923824755 | True |
| Year=2024\|Tier=UHNW | 0.0140966253 | 0.014096625252727847 | True |

The literal slice keys contain a vertical bar; the CSV is authoritative. Ratio tolerance is 0.0001. Grand Total uses December 2024 (2,177 eligible rows), whereas Year=2022 uses December 2022 (2,421 eligible rows), confirming that the year filter changes the evaluation date. Tier-specific agreement tests preservation of the client filter. These diagnostics come from pandas; the alpha outputs come independently from Power BI.

## Edge case: all latest returns suspect

A separate Power BI query filtered client 29 and year 2024. It returned last snapshot **2024-12-01**, with **Alpha BLANK and Signal BLANK**. Pandas found one suspect row at that date and zero eligible rows. It also found an earlier eligible alpha of 0.106621 on 2024-02-01. The measure correctly did not substitute that older return. This additional test closes the initial code review's concern that the aggregate slices could not distinguish latest-date selection before versus after suspect exclusion. It is separate from the 160-row reconciliation.

## Debug, confirmed claim and limits

Claude's claim that suspect rows must be excluded from both numerator and denominator was checked in pandas: at the grand total, eligible AUM is $12,714,028,572.76, below total Ending AUM by $15,543,506.10; the eligible numerator is 184,098,457.35441887. Their ratio matches Power BI. Including suspects instead gives 0.01667843242874973. The client 29 test also confirms the no-fallback behavior in Power BI.

No alpha formula change was necessary. The date-table setting was corrected after the explicit UI check. The review found no script defect affecting this dataset. This evidence is specific to tested contexts: Lagging, exact ±2% boundaries and a zero-AUM denominator were not verified against Power BI. The 2024 tiers and 2022 year exercise filter-context edge cases, while client 29 directly exercises the empty-eligible-set and blank-signal case.
