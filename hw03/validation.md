# HW03 Data Validation

Validation date: September 30, 2026.

## 5A — Known-Answer Check: Earnings

Company: Walmart (WMT). Period: second quarter fiscal 2027, the three months ended July 31, 2026. The earnings filing is dated August 20, 2026. Revenue and net income in the CSV are in millions of US dollars; EPS is dollars per share.

Official source: [Walmart Q2 FY2027 earnings release, consolidated statements of income](https://stock.walmart.com/sec-filings/all-sec-filings/content/0000104169-26-000145/earningsreleasefy27q2.htm).

| Check | Official Source | Your CSV | Match? |
| --- | --- | --- | --- |
| Walmart Q2 FY2027 revenue | $187,937 million | 187937 million | Yes |
| Walmart Q2 FY2027 diluted EPS | $0.80 | 0.80 | Yes |

The official statement also reports net income attributable to Walmart of $6,366 million. This is the definition used for the CSV's net_income field for Walmart, rather than consolidated net income before subtracting noncontrolling interests.

### Extraction issue and correction

The first real earnings run saved 17 rows. Walmart's latest releases were skipped because the period search excluded table blocks, and its one saved Q4 FY2026 row had NOT_FOUND for revenue, EPS, and net income. A local diagnostic showed that Walmart placed the headline and highlights inside HTML tables. Its explicit quarter/year labels, such as Q2 FY27, also appeared beyond the original 3,000-character search window.

A new Claude Cowork conversation reviewed the actual release text. Before the fix, reporting-period detection searched prose only. After the fix, a fallback used the headline's quarter and matching results-table fiscal-year labels, excluding guidance and prior-year comparisons. The proposed results-column pattern was `^Q([1-4])\s*FY\s*'?(\d{2}|\d{4})$`. A scoped highlights revenue fallback used `^Revenue of \$(\d{1,3}(?:,\d{3})*(?:\.\d+)?) ?(billion|million)\b` within the matching quarterly highlights section. Previously, the narrative search could not reach that section because it was inside a table.

The table parser was also corrected to connect a separate month/day heading with its period group and year columns. Exact consolidated statement revenue was preferred over rounded highlights revenue. After these changes, the run saved 20 earnings rows with all three financial fields populated, including four Walmart quarters. The other four companies' printed results were unchanged. These checks do not independently establish the accuracy of every earnings row.

## 5B — Known-Answer Check: Executive Events

Selected event: John R. Furner's appointment as Walmart President and Chief Executive Officer, disclosed in the November 14, 2025 filing.

Public source: [Walmart announcement dated November 14, 2025](https://stock.walmart.com/sec-filings/all-sec-filings/content/0000104169-25-000172/pressrelease111425.htm).

| Check | News Source Confirms? | Notes |
| --- | --- | --- |
| Person name and title | Yes | The announcement names John Furner as President and Chief Executive Officer. The extracted record uses his fuller name, John R. Furner. |
| Event type (departure/appointment) | Yes | The announcement identifies his selection to succeed Doug McMillon. The CSV classifies this role change as an appointment. |
| Effective date | Yes | Both the announcement and the corrected CEO appointment record give February 1, 2026. |

Furner's board election is retained as a separate event rather than combined with his CEO appointment. The initial executive run produced 29 rows. Review and corrections addressed a duplicate short-name reference to Suzanne Nora Johnson, board-action dates mistaken for effective dates, missing titles, and distinct appointments merged into one row. The revised run produced 33 rows. Uncertain or incompletely specified effective dates remain NOT_FOUND. Nicholas Parker's anticipated August 24, 2026 start date was not treated as a confirmed effective date, and Kathryn McLay's company departure uses April 30, 2026, separately from the January 31 end of her role.

## 5C — Cross-Validation: Earnings via Yahoo Finance

The local validate_yfinance.py script retrieved Walmart's quarterly income statement through yfinance and selected July 31, 2026 explicitly. This is the same quarter checked in 5A. The following results are from the script's terminal output.

| Metric | From 8-K text extraction | From yfinance | Match? |
| --- | --- | --- | --- |
| Revenue | $187,937 million | Total Revenue: $187,937,000,000, or $187,937 million | Yes; difference $0 |
| Net income attributable to Walmart | $6,366 million | Net Income: $6,366,000,000, or $6,366 million | Yes; difference $0 |

There was no discrepancy after aligning the quarter and converting Yahoo's dollar values to millions. The validation script did not modify either source CSV.

## 5D — Pipeline Integrity Checks

| Check | Expected | Actual | Pass/Fail |
| --- | --- | --- | --- |
| earnings_history.csv row count | Up to 20 (5 companies × 4 quarters) | 20 rows reported by the earnings run and loaded by the timeline script | Pass |
| executive_events.csv row count | At least 0 (document actual) | 33 rows reported by the executive run and loaded by the timeline script | Pass |
| corporate_events_timeline.csv created | Yes | Created with 33 rows; uploaded CSV inspected | Pass |
| Earnings rows with all three financial fields NOT_FOUND | 0 (investigate if greater than 0) | 0 in the final 20-row earnings terminal output | Pass |

The uploaded timeline contained 33 rows: 23 before earnings, 7 after earnings, and 3 within seven days. Its recorded day differences and timing categories were independently recalculated from the two filing-date columns and matched for every row. Matching uses filing dates, not effective dates, and searches only the four earnings filings available for each company. Separate role appointments count as separate event rows, so the counts do not represent 33 independent announcements. Passing these integrity checks does not prove that every extracted event or financial value is accurate.
