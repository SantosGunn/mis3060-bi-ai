# HW06 — DAX Measure Library: AUM & Performance

## Results and structure

The completed reconciliation reported **160 passed, 0 failed, 160 total**: 16 measures across ten slices. The three missing values are Year=2020 Ending AUM LY, AUM YoY % and Organic Growth Rate. BLANK is preserved as an empty CSV cell, not converted to zero.

| Path | Purpose |
|---|---|
| powerbi/hw06.pbix | Working Power BI model and Measures report page; saved separately from these documentation files |
| powerbi/measures.md | All 16 DAX measures, patterns, formats, manager meanings and Part C answers |
| scripts/01_reconcile_measures.py | Independent pandas calculations and reconciliation |
| reports/powerbi_values.csv | Actual DAX export, measure/slice/value |
| reports/pandas_values.csv | Independently computed values |
| reports/measure_reconciliation.csv | Power BI versus pandas, difference and match |
| reports/design_evidence.json | Grain, coverage, design and edge-case diagnostics |
| claude/model_metadata.md | Original INFO.VIEW table, column and relationship exports |
| claude/dax_session.md | Full DAX prompt and Claude response, followed by actual test queries |
| claude/verification.md | Observed tests, review, changes and limitations |

## Inputs and execution

The Power BI work started from the posted Wildcat_Star_Model.pbix. The independently processed CSVs are in `hw05/data`; this is the actual directory used by the successful run. The script reads dim_date.csv, dim_client.csv, fact_portfolio_snapshot.csv, fact_fees.csv and fact_transactions.csv. The directory also contains the other model dimensions. Validated row counts are 1,827 dates, 2,500 clients, 129,547 snapshots, 122,197 fees and 298,572 transactions. The snapshot grain is unique client/date, with 60 monthly dates from January 2020 through December 2024.

From the repository root, with the project's Python environment activated and pandas installed:

```powershell
python hw06/scripts/01_reconcile_measures.py
```

The script resolves default directories relative to its own location. Explicit alternatives are supported:

```powershell
python hw06/scripts/01_reconcile_measures.py --data-dir hw05/data --reports-dir hw06/reports
```

For a fresh export, run the saved-measure DAX query in claude/dax_session.md in the completed PBIX. Preserve all 160 rows as `reports/powerbi_values.csv` with headers `measure,slice,value`, no bracketed headers, numeric values as plain raw decimals, and blanks as empty cells. Do not copy pandas output into this file. The full export includes Alpha Signal text and raw decimal ratios. Currency symbols, thousands separators and percentage signs are rejected by the parser.

Coverage is Grand Total, each year 2020–2024, each of HNW/Retail/UHNW in 2024, and December 2024. All measures are tested on every slice, exceeding the minimum slice coverage. Currency tolerance is 0.01; ratios and bps use 0.0001; counts and labels must match exactly. Blank versus zero fails. Exit codes: 0 all match; 1 numerical/text mismatches; 2 invalid inputs; 3 missing Power BI export. Invalid or missing export removes a stale reconciliation file so it cannot be mistaken for new evidence.

## Draft, run and review

Claude drafted the reconciliation script; it was run in the local VS Code terminal and reviewed with Claude Code before committing. The initial run computed pandas values but stopped because the Power BI export did not yet exist. After exporting the real saved measures, the first complete comparison passed 160/160. No numerical mismatch required a formula or script fix. Marking dim_date as the date table was a model setup correction made earlier, after checking its Power BI setting.

The reviewer found no bugs affecting this dataset and reported the following scope limits and hypothetical cases:

- **Top 10 dates:** the data cannot distinguish one common last date from per-client last dates numerically because no departed client reaches the top ten. The documented DAX fixes LastSnapshot before iterating clients, making the intended common-date rule explicit.
- **Alpha no-fallback:** the aggregate slices all have eligible rows at their latest date, so their match alone did not test no-fallback behavior. A subsequent real Power BI test of client 29 in 2024 returned December 1 with blank alpha and signal, matching pandas and closing that gap.
- **Signal coverage:** the reconciliation tests In line and Outperforming. The additional client test covers blank. Lagging and exact threshold boundaries remain untested in Power BI; the documentation does not claim exhaustive branch coverage.
- **Rank-ten ties:** the review warned about generic TOPN tie behavior. The submitted DAX has client_id as a secondary ascending sort key, consistent with taking exactly ten clients. The dataset has no AUM tie at rank ten in any reconciled slice.
- **Unmatched client IDs:** pandas would group unmatched IDs separately while a dimension-based Power BI grouping can combine them under the blank member. There are no unmatched IDs here, so no change was required for this dataset.
- **Missing tiers and client_since:** an absent tier would only warn, and malformed client_since would stop the script even though measures do not use it. All three tiers are present and client_since parses successfully.

The review reported maximum differences of approximately $0.000099 for naive SUM, $0.000032 for Avg Monthly AUM, and 0.00000000005 for ratios, all comfortably inside tolerance. The script's synthetic tests were reported by Claude to cover match/mismatch, blank versus zero, invalid values, duplicate and missing export rows. Those are separate from the observed real-data run.

The JSON originally labeled the ICE9 formula as a candidate. After the review, ICE9_DAX_Foundations.docx Part B Task 4 was obtained and confirmed the same formula. Part C(b) documents this confirmation; the original evidence file and script were preserved without silently rewriting their provenance. No script change was necessary.

## Interpretation and reproducibility limits

Passing reconciliation establishes agreement between independent calculations on these inputs and tested slices, not universal correctness for arbitrary data. In particular, the naive SUM agrees in both tools but remains the wrong way to report AUM across time. See powerbi/measures.md for the $419.73M stale-balance effect, fee coverage gap and alpha exclusions.

The PBIX must be kept on Apporto's persistent drive and copied locally to powerbi/hw06.pbix, with the Measures page open when saved. The documentation archive does not contain that working PBIX. The existing script and reports must remain alongside these files. Before submission, verify the PBIX is present, review the documents against the saved model, commit the completed hw06 folder with a meaningful message, push, and submit its repository folder URL in Brightspace. If the PBIX exceeds GitHub's 100 MB limit, submit it through Brightspace instead and record that actual delivery here.
