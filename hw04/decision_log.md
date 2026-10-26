# HW4 Decision Log: Wildcat Capital raw data

**Source of evidence.** All evidence comes from these reports:
- `reports/dq_summary_raw.csv` (287 checks: 7 ERROR, 9 WARN, 40 INFO, 231 PASS)
- `reports/profile_raw.csv`
- `reports/near_dup_clients_raw.csv`

Finding IDs (F001, F002, ...) refer to `dq_summary_raw.csv`.

A few overlap counts are not in those reports, because the audit did not measure them. They describe how the quarantined rows intersect other issues, and I computed them from the raw files while revising this log. They are marked **(raw overlap count)**. `02_clean.py` must recompute and assert every one of them.

Nothing here has been applied yet. This log is the instruction set for `scripts/02_clean.py`.

**How to read each entry**

- **Type** says how sure we are that something is wrong:
  - *confirmed defect*: breaks a hard rule or fails a reconciliation
  - *inferred convention*: the fix depends on a rule worked out from the data, not documented by Wildcat
  - *plausibility concern*: unusual, not provably wrong
  - *probable duplicate*: strongly supported, not a confirmed identity
  - *legitimate structure*: looks odd, should be preserved
- **Verification** gives the precondition checked *before* a step and the `assert` *after* it.
- **Stop rule:** if any repair or quarantine precondition fails, the script stops with a clear error naming the issue, the check and the count found. There are no fallback flags for this version. Every flag column has one meaning, stated in its issue.
- **Counts:** "raw" means the count in the raw files. "Clean" means the count expected in `data/clean/` after the order below. Where they differ, the difference is the quarantined rows.
- Overlapping audit findings (one bad column caught by several checks) are merged into one issue.

---

## Order of operations

The order is chosen so that quarantined rows leave **before** any value is changed. Repairs and flags then apply only to rows that stay in the clean data. This keeps every clean count exact, and it means no quarantined row is ever touched.

| Step | Table | Action | Issue |
|---|---|---|---|
| 0 | all | Load raw files as text; record raw row counts (F017 to F024) | |
| 1 | dim_client | Quarantine 25 probable-duplicate client IDs | 5 |
| 2 | fact_transactions | Quarantine 200 orphan-client rows (checked against the reduced dim_client) | 4 |
| 3 | dim_client | Standardize full state names | 6 |
| 4 | fact_transactions | Standardize `45.0` security IDs | 2 |
| 5 | fact_transactions | Correct negative Buy shares + set `shares_sign_corrected_flag` | 3 |
| 6 | fact_portfolio_snapshot | Convert `%` returns | 1 |
| 7 | several | Add the remaining flag columns | 7, 8, 9, 10 |
| 8 | all | Write clean files; build quarantine files from the **raw** tables by primary key; prove `raw = clean + quarantined` | |

**Quarantine file rule.** Each quarantine file is built by selecting the quarantined primary keys from the **raw** table, as loaded in step 0 (`dtype=str`, `keep_default_na=False`). Every original column is kept, in raw order, and every original cell value is preserved exactly as text: the same string that was read from the raw file, with no type conversion, trimming, rounding or blank-to-NA substitution. (CSV quoting and line endings in the written file may differ from the raw file; cell values may not.) `02_clean.py` asserts that each quarantined row's original columns equal the raw text values for that key. Audit information is added only as separate, clearly prefixed columns appended after the original columns:
- `qa_reason`
- `qa_step`
- for duplicate clients only, `qa_retained_client_id`

Under this order no quarantined row is edited before it is removed. Building the file from raw by key also guarantees this if the order is ever changed.

**Row-count proof (expected):**
- `dim_client`: 2,525 raw = 2,500 clean + 25 quarantined.
- `fact_transactions`: 298,772 raw = 298,572 clean + 200 quarantined.
- All other tables: raw = clean, 0 quarantined.

**Flag columns (0/1), each with a single meaning:**

| Flag | Meaning (= 1 only when) | Expected clean sum |
|---|---|---|
| `dim_client.risk_profile_missing_flag` | risk_profile is blank | 75 |
| `fact_transactions.shares_sign_corrected_flag` | this row's shares sign was actually changed in step 5 | 835 |
| `fact_transactions.after_last_snapshot_flag` | inactive client, txn month after last snapshot month | 2,410 |
| `fact_portfolio_snapshot.return_outlier_flag` | return_ytd (after Issue 1) or active_alpha_ytd outside the assumed band | 2,440 |
| `fact_portfolio_snapshot.aum_at_floor_flag` | aum = 1,000.00 | 420 |
| `fact_fees.aum_basis_at_floor_flag` | aum_basis = 1,000.00 | 386 |

---

## Summary

| # | Table / column | Findings covered | Type | Decision |
|---|---|---|---|---|
| 1 | fact_portfolio_snapshot.return_ytd (`%` text) | F001, F038 | Confirmed defect | Convert |
| 2 | fact_transactions.security_id (`45.0` text) | F002, F007 | Confirmed defect | Standardize |
| 3 | fact_transactions.shares (negative Buy) | F003, F004, F005 | Confirmed defect; fix uses an inferred convention | Standardize (sign) + flag |
| 4 | fact_transactions.client_id (orphans) | F006 | Confirmed defect | Quarantine |
| 5 | dim_client (25 client pairs) | F012, F051, F052, F044, F045, F046 | Probable duplicate | Quarantine the fact-less copy |
| 6 | dim_client.state (full names) | F009 | Confirmed defect (format) | Standardize |
| 7 | dim_client.risk_profile (blank) | F008, F055 | Completeness gap | Leave blank + flag |
| 8 | Extreme return_ytd / active_alpha_ytd | F010, F011 | Plausibility concern | Leave + flag |
| 9 | AUM at exactly 1,000.00 | F039 (+ fact_fees.aum_basis profile) | Plausibility concern | Leave + flag |
| 10 | Transactions after an inactive client's last snapshot | F016 | Plausibility concern | Leave + flag |
| 11 | Transactions on non-trading days | F013, F041, F034 | Plausibility concern | Leave as is |
| 12 | Snapshot months with no fee row | F014 | Unexplained cross-table gap | Leave as is |
| 13 | Advisory Fee transactions vs fact_fees | F015 | Unexplained cross-table mismatch | Leave as is; do not combine |
| 14 | Meaning of Dividend shares | F040, F056 | Unresolved interpretation | Leave as is (exploratory only) |
| 15 | Conditional blanks | F027, F028, F031, F032, F033, F050 | Legitimate structure | Leave as is |
| 16 | ZIP leading zeros | F026 | Legitimate structure | Leave as is (text) |
| 17 | certifications = "None" | F025 | Legitimate structure | Leave as is |
| 18 | Scientific-notation numbers | F029, F030 | Format only | Leave as is |
| 19 | Monthly rows dated before client_since, same month | F053, F054 | Legitimate structure | Leave as is |
| 20 | Weekday market holidays marked as trading days | F034 | Source limitation | Leave as is |
| 21 | Same security name on different tickers | F036, F037 | Not resolved | Leave as is |
| 22 | Dimension keys no fact uses | F042, F043, F047, F048, F049 | Legitimate structure | Leave as is |

**Coverage:**
- All 7 ERRORs (F001 to F007) are covered by Issues 1 to 4.
- All 9 WARNs (F008 to F016) are covered by Issues 5 to 13.
- The INFO findings needing a preservation or interpretation decision are Issues 14 to 22.
- Other INFO findings serve as evidence in Issues 1 to 13 (F034, F038, F039, F041, F044 to F046, F051, F052, F055).
- The remaining INFO findings are listed at the end. Every ERROR, WARN and INFO finding (F001 to F056) is cited at least once.

---

## Issue 1. Percentage text in return_ytd (step 6)

| Field | Entry |
|---|---|
| **Table / column** | fact_portfolio_snapshot.return_ytd |
| **Evidence** | F001 `type validity (float)`: 300 of 129,547 values fail to parse because they end in `%` (e.g. snapshot_id 42 = `9.28%`, 59 = `19.52%`, 1354 = `-3.18%`). The profile shows shapes `9.9%`:188 and `-9.9%`:112. F038: all 300 reconcile to `return_ytd - benchmark_return_ytd = active_alpha_ytd` (±0.0001) when divided by 100, and **0** reconcile without dividing. Example: 9.28% → 0.0928; 0.0928 - 0.08279 = 0.01001 vs stored alpha 0.009966 (within tolerance). |
| **Type** | Confirmed defect. What the `%` means is verified by a second column, not assumed. |
| **Dimension violated** | Validity, Consistency |
| **Decision** | **Convert**: strip `%`, divide by 100, and write decimal text. |
| **Justification** | A numeric load would turn these 300 into errors or nulls, so those account-months would silently drop out of return reporting. The alpha column shows the values are in percent units. |
| **Verification** | **Before:** exactly 300 values end in `%`, and all 300 pass the /100 alpha reconciliation; otherwise stop. **After:** 0 type-validity failures in return_ytd; the alpha reconciliation passes on all 129,547 rows at ±0.0001; `return_ytd >= -1` still passes; 300 rows logged in `value_changes.csv`. No snapshot rows are quarantined, so raw and clean counts are both 300. |
| **Risk if wrong** | If these were already decimals (9.28 meaning +928%), dividing would understate them. The 300 / 0 reconciliation result makes this very unlikely. |

## Issue 2. Transaction security IDs stored as `45.0` (step 4)

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions.security_id |
| **Evidence** | F002 `type validity (int)`: all 197,175 nonblank raw values are integers written as floats (e.g. txn_id 1 = `45.0`). F007: the raw text match to `dim_security.security_id` is **0%**. After dropping `.0`, there are 0 orphans (F267 PASS). **(raw overlap count)** 131 of the 197,175 belong to orphan rows quarantined in step 2. |
| **Type** | Confirmed defect (format) |
| **Dimension violated** | Validity, Referential Integrity |
| **Decision** | **Standardize** nonblank values matching `^\d+\.0+$` by dropping the decimal part (`45.0` → `45`). Blanks stay blank. |
| **Justification** | Without this, every trade, sale and dividend fails to join to its security, and asset-class reporting on transactions would be empty. The values are whole numbers, so only the format changes. |
| **Verification** | **Before (clean rows only):** every nonblank value matches `^\d+\.0+$`; expected 197,044 (197,175 raw - 131 quarantined); otherwise stop. **After:** raw-text match to dim_security = 100% of nonblank keys; 197,044 changes logged; blanks still 101,528 (Issue 15). |
| **Risk if wrong** | Very low. A non-zero decimal such as `45.5` would fail the precondition and stop the script. |

## Issue 3. Negative share counts on Buy transactions (step 5)

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions.shares (txn_type = Buy) |
| **Evidence** | F005: 836 raw negative share values, all on Buy. F003: the same 836 fail the bound `shares > 0`. F004: those 836 Buys (1.001% of 83,556) fail `amount = shares x price`, and all 836 reconcile within ±$0.01 when the sign is ignored. Example, txn_id 272: abs(-261.9719) × 441.71 rounds to 115,715.61, the stored amount. **(raw overlap count)** 1 of the 836 (txn_id 298603) is an orphan row quarantined in step 2, leaving 835 in clean data. |
| **Type** | Confirmed defect: the rows break the amount rule. The fix relies on an **inferred sign convention**: share counts are positive and direction comes from txn_type. This is inferred from the data, not documented by Wildcat. Support: every amount is positive (F196 PASS); all 59,755 Sells reconcile with positive shares (F240 PASS); negative shares appear only on these Buy rows (F005). |
| **Dimension violated** | Validity, Consistency |
| **Decision** | **Standardize (flip the sign)** on clean rows where all three hold: txn_type = Buy, shares < 0, and `abs(shares) × price` equals amount within ±$0.01. Set `shares_sign_corrected_flag = 1` only on rows actually changed. |
| **Justification** | Negative Buy shares would subtract from holdings and break shares × price calculations. The positive amount and the Buy label agree, and the minus sign is the only field that disagrees. |
| **Verification** | **Before (clean rows only):** count Buy rows with shares < 0 (expect 835), and confirm all 835 meet the reconciliation condition; if any does not, stop. **After:** 0 negative shares remain in clean data; the Buy amount rule passes on all clean Buys; price and amount unchanged (assert equality); 835 changes logged; flag sum = 835 = rows changed. The quarantined txn_id 298603 keeps its raw value `-411.3807` in the quarantine file. |
| **Risk if wrong** | If a negative Buy was really a reversal, flipping it turns a cancellation into a purchase and overstates holdings. The flag lets an analyst find all 835 corrected rows. |

## Issue 4. Transactions whose client does not exist (step 2)

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions.client_id → dim_client.client_id |
| **Evidence** | F006: 200 rows (0.067% of 298,772) point at client IDs that are missing even after normalization. There are 200 distinct orphan keys, one row each (e.g. 2702, 2704; txn_id 298573 → client 3191). The profile shows transaction client_id has 2,700 distinct values with a max of 3,192, while dim_client ends at 2,525. Transaction advisor IDs have no orphans (F266 PASS). **(raw overlap counts)** By type: Buy 58, Dividend 38, Sell 35, Deposit 25, Advisory Fee 24, Withdrawal 20. 69 are cash-type rows with blank security_id / shares / price; 131 have a nonblank security_id; 1 is a negative-share Buy (txn_id 298603). |
| **Type** | Confirmed defect |
| **Dimension violated** | Referential Integrity |
| **Decision** | **Quarantine** all 200 rows to `data/audit/quarantine_fact_transactions_orphan_client.csv`, built from the raw table by txn_id, with `qa_reason` and `qa_step` appended. No placeholder clients and no guessed IDs. |
| **Justification** | These rows cannot be tied to a client, risk profile or tier. Quarantining keeps them traceable instead of letting a join drop them silently. |
| **Verification** | **Before:** run after step 1 against the reduced dim_client. Expect 200 orphan rows and 200 distinct keys. Since the 25 removed client IDs have no fact rows (Issue 5), the count must still be exactly 200; any other count stops the script. **After:** client match rate = 100%; 298,772 = 298,572 + 200; every original cell in the quarantine file equals the raw text value for that txn_id. Log the total `amount` of quarantined rows in `cleaning_log.csv` (**(raw overlap count)** 10,888,495.37). |
| **Risk if wrong** | If these are real clients missing from the client extract, client activity is understated by 200 transactions. The quarantine file allows restoring them. |

## Issue 5. 25 probable duplicate clients (step 1)

| Field | Entry |
|---|---|
| **Table / column** | dim_client (pairs differ only in last_name) |
| **Evidence** | **F012:** 50 rows in 25 pairs are identical on age, city, state, zip_code, initial_aum (to the cent), client_since and advisor_id. In every pair last_name differs by truncation or extension. **near_dup_clients_raw.csv:** risk_profile, client_tier, primary_account_type and is_active are also identical in every pair (`other_attrs_differ` blank). **F052:** each group has exactly one ID with facts. The fact-bearing IDs have 158 to 295 fact rows; the other IDs have 0 fees, 0 snapshots and 0 transactions. **F051 / F044 to F046:** the fact-less IDs are exactly 2501 to 2525. **(raw overlap counts)** Among these 25: 4 have ZIPs with a leading zero, 1 has a blank risk_profile (2510), and 1 has a full state name (2517, `Florida`). Their retained partners carry the same raw values (1267 is blank; 739 is `Florida`), which is why the pairs match on state in raw. Comparing every column except client_id and last_name, all 25 pairs are equal, including first_name, and in all 25 the shorter last_name is a strict prefix of the longer one. |
| **Type** | **Probable duplicate, strongly supported.** These are not confirmed to be the same person. Name length cannot settle which spelling is right: in 23 pairs the fact-less copy is shorter (Jacobson / Jacobso), in 2 it is longer (Pace / Pacen, Lee / Leen). |
| **Dimension violated** | Uniqueness |
| **Decision** | **Quarantine** the 25 fact-less IDs to `data/audit/quarantine_dim_client_probable_duplicates.csv`, built from the raw table by client_id. Append `qa_reason`, `qa_step` and `qa_retained_client_id` (the fact-bearing ID in the same pair). Keep the fact-bearing row with its last_name unchanged. |
| **Justification** | Keeping both would count about 25 clients twice and inflate headcounts by tier and advisor. The row to keep is chosen by evidence (it owns all the account history), not by name length. No fact row changes. The kept spelling is the one attached to the history, not a verified legal name; this goes in `README_clean.md`. |
| **Verification** | **Before** (on raw text values, before step 3 changes any state name): for each of the 25 pairs, assert that (a) every column **except client_id and last_name** is equal. client_id is the identifier being deduplicated, so it is excluded; **first_name is included and must be equal**; so must age, city, state, zip_code, initial_aum, client_since, advisor_id, risk_profile, client_tier, primary_account_type and is_active. (b) Exactly one ID has fact rows across the three fact tables and the other has 0. (c) last_name is the **only** column allowed to differ, and only in the documented way: both values nonblank, not equal, and the shorter one an exact (case-sensitive) prefix of the longer one (truncated or extended). Any other last_name difference, or any difference in another column, stops the script. **After:** dim_client has 2,500 rows; 2,525 = 2,500 + 25; no clean fact row points at a quarantined ID; the near-duplicate check returns 0. |
| **Risk if wrong** | If any pair were really two people (e.g. relatives at one address), a real client record would be hidden. An identical opening balance to the cent and identical start date make that unlikely, but it is not ruled out. If the fact-less copy holds the correct spelling, the clean table keeps a misspelled name. That is a naming limitation; the account data is unaffected. |

## Issue 6. State stored as full names (step 3)

| Field | Entry |
|---|---|
| **Table / column** | dim_client.state |
| **Evidence** | F009 `allowed values`: 78 of 2,525 raw rows (3.089%) hold full names: Pennsylvania 25, Florida 15, New York 14, New Jersey 13, California 5, Illinois 4, Texas 2. **(raw overlap count)** 1 of these (client 2517, Florida) is quarantined in step 1, leaving 77 in clean data. |
| **Type** | Confirmed defect (format) |
| **Dimension violated** | Consistency, Validity |
| **Decision** | **Standardize** with an explicit 7-entry mapping: Pennsylvania→PA, Florida→FL, New York→NY, New Jersey→NJ, California→CA, Illinois→IL, Texas→TX. |
| **Justification** | Mixed formats split one state into two groups in reports and maps. |
| **Verification** | **Before (clean rows only):** every non-code value is a key in the mapping (expect 77 rows, including retained client 739); an unmapped value stops the script. **After:** the allowed-values check returns 0; 77 changes logged; row count unchanged. This standardizes the format only. It does not prove the state is correct, and ZIPs are not used to check it. The quarantined row 2517 keeps `Florida` in the quarantine file. |
| **Risk if wrong** | Very low. A wrong mapping entry would misplace a few clients by region. |

## Issue 7. Missing risk profiles (step 7)

| Field | Entry |
|---|---|
| **Table / column** | dim_client.risk_profile |
| **Evidence** | F008: 76 of 2,525 raw clients (3.01%) are blank. F055: snapshots for blank-profile clients all use benchmark 3 (3,942 rows), the benchmark Balanced clients use (38,960 rows). Each named profile maps to one benchmark (F282 PASS). Client 2510 (blank) is quarantined in Issue 5, and its retained pair 1267 is also blank. |
| **Type** | Completeness gap. The benchmark pattern is evidence, not proof. |
| **Dimension violated** | Completeness |
| **Decision** | **Leave blank** and set `risk_profile_missing_flag = 1`. Do not fill with "Balanced". |
| **Justification** | Risk profile records the client's own risk tolerance, which is a suitability fact. Benchmark 3 may be a default assigned when the profile is missing, so it does not show the client chose Balanced. |
| **Verification** | **After:** 76 raw = 75 clean + 1 quarantined; no blank filled; flag sum = 75. |
| **Risk if wrong** | Reports by risk profile show an "(unknown)" group of about 3%. If Wildcat documents that benchmark 3 is assigned from the profile, the blanks could be filled later with that evidence. |

## Issue 8. Extreme YTD returns and alpha (step 7)

| Field | Entry |
|---|---|
| **Table / column** | fact_portfolio_snapshot.return_ytd, active_alpha_ytd |
| **Evidence** | F010: 2,157 return values (1.665%) are outside the assumed band [-0.6, 1.0]. F011: 2,217 alpha values (1.711%) are outside it too. The profile shows return_ytd from -0.993708 to 94.668215, and alpha from -1.22245 to 94.569541. These rows still pass the hard bound `return >= -1` (F181 PASS) and the alpha reconciliation (F236 PASS). |
| **Type** | Plausibility concern. The band is my assumption, not a business rule. |
| **Dimension violated** | Accuracy / Plausibility |
| **Decision** | **Leave as is**. Set `return_outlier_flag = 1` where return_ytd (after Issue 1) or active_alpha_ytd is outside the band. |
| **Justification** | The three return columns agree with each other, so there is no internal error and no source for a "right" value. The flag marks rows to **investigate**. Whether to include them in a particular analysis is a decision for that analysis, stated there, not made here. |
| **Verification** | **After:** values unchanged except the 300 converted in Issue 1; flag sum = 2,440, computed on the converted column (**(raw overlap count)** 2,157 return + 2,217 alpha − 1,934 both; matches F010 and F011, which already scale `%` values); alpha reconciliation still passes on all rows. No snapshot rows are quarantined. |
| **Risk if wrong** | If the values are real, the flag is harmless. If they are errors, unflagged summaries could be distorted; the flag makes them easy to examine. |

## Issue 9. AUM at exactly 1,000.00 (step 7)

| Field | Entry |
|---|---|
| **Table / column** | fact_portfolio_snapshot.aum; fact_fees.aum_basis |
| **Evidence** | F039: 420 snapshots have aum exactly 1,000.00, which is also the column minimum (profile numeric_min). In fact_fees, `aum_basis = 1000.0` is the most common value (386 rows, profile top_values). Fees on these rows still reconcile to `aum_basis × bps / 10000 / 12` (F230 PASS), and fee AUM equals snapshot AUM (F277 PASS). Snapshots 1463 and 1464 (client 29) appear among the examples for both F039 and F010. The audit did not measure how far the two findings overlap beyond that. |
| **Type** | Plausibility concern. A repeated exact minimum *may* be a system floor; that is a hypothesis. |
| **Dimension violated** | Accuracy / Plausibility |
| **Decision** | **Leave as is**. Set `aum_at_floor_flag` (snapshots) and `aum_basis_at_floor_flag` (fees) = 1 where the value equals 1,000.00. |
| **Justification** | No other source holds the true balance, so a replacement would be invented. The flag makes these rows easy to investigate alongside Issue 8. Neither is assumed to cause the other. |
| **Verification** | **After:** values unchanged; flag sums 420 and 386 (no snapshot or fee rows are quarantined). |
| **Risk if wrong** | If 1,000 is a placeholder, AUM totals and related returns for those months are unreliable. The flags allow them to be examined or excluded deliberately. |

## Issue 10. Transactions after an inactive client's last snapshot (step 7)

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions.txn_date vs last snapshot month (inactive clients) |
| **Evidence** | F016: 2,410 of 21,092 transactions (11.426%) for inactive clients are dated after that client's last snapshot month. Example: client 13, last snapshot 2023-03-01, transactions to 2023-11-16. The is_active flag agrees with snapshot coverage (F271, F272 PASS). The quarantined orphan rows have no client, so they are outside this check and the count is the same in clean data. |
| **Type** | Plausibility concern. The data has no account-closing date. |
| **Dimension violated** | Consistency |
| **Decision** | **Leave as is**. Set `after_last_snapshot_flag = 1`. |
| **Justification** | This could be real wind-down activity or late postings. Without a closing date, removing it could delete real money movement. |
| **Verification** | **After:** values unchanged; flag sum 2,410. |
| **Risk if wrong** | If these are errors, activity totals for closed accounts are overstated. The flag allows filtering. |

## Issue 11. Transactions on non-trading days

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions.txn_date (with dim_date.is_trading_day) |
| **Evidence** | F013: raw, 40,649 of 143,311 Buys and Sells (28.364%) fall on non-trading days. F041: cash events show a similar rate, 44,350 of 155,461 (28.528%). F034: weekends are 522 of 1,827 calendar days. Transactions appear spread across all seven days rather than following a trading calendar. **(raw overlap counts)** 19 of the Buy/Sell and 34 of the cash-event weekend rows are quarantined orphans. Clean data is therefore expected to hold 40,630 of 143,218 and 44,316 of 155,354. |
| **Type** | Plausibility concern. The pattern looks systematic, not a few bad rows. |
| **Dimension violated** | Accuracy / Plausibility |
| **Decision** | **Leave as is.** No flag column, because joining to `dim_date.is_trading_day` gives the same information. |
| **Justification** | The real trade date is unknown, and moving dates would invent data. The dates may be posting or settlement dates, but that is unconfirmed. |
| **Verification** | **After:** txn_date unchanged on all clean rows (assert). |
| **Risk if wrong** | Day-of-week analysis and price-on-date comparisons will be unreliable. Noted as a limitation in `README_clean.md`. |

## Issue 12. Snapshot months with no fee row

| Field | Entry |
|---|---|
| **Table / column** | fact_portfolio_snapshot → fact_fees (client + month) |
| **Evidence** | F014: 7,350 of 129,547 snapshots (5.674%), across 2,261 clients, have no fee row for that month. Every fee month has a snapshot (F278 PASS), and AUM matches where both exist (F277 PASS). |
| **Type** | Unexplained cross-table gap |
| **Dimension violated** | Completeness |
| **Decision** | **Leave as is.** Do not create fee rows. |
| **Justification** | The gap could be fee waivers, billing timing or missing billing data. Creating rows would mean guessing a rate and fee type. |
| **Verification** | **After:** fact_fees row count unchanged (122,197). |
| **Risk if wrong** | If billing data is missing, billed fees are understated. Recorded as a limitation. |

## Issue 13. Advisory Fee transactions vs fact_fees

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions (txn_type = Advisory Fee) vs fact_fees, by client-month |
| **Evidence** | F015: there are 30,679 client-months with fee debits. 28,746 also have a fact_fees row, and **only 1** of those 28,746 matches within ±$0.01 (client 1810, December 2023: $111.00 in transactions vs $111.01 billed); 28,745 do not. The median per-client-month ratio of transaction debits to billed fees is 3.11. Over the 28,746 overlapping client-months, transaction debits total $248,887,342.62 and billed fees total $46,632,368.54 (Part D R4; shown side by side, not combined). |
| **Part D correction** | This entry first said **none** of the 28,746 matched. That came from a floating-point error in the Part A check: summed as floats, the difference of exactly $0.01 for client 1810 became 0.0100000000000051 and failed the ≤ $0.01 test. Part D's exact-decimal reconciliation (R4) found the 1 match. `01_profile.py` now sums with exact decimals, and F015 reports 28,745 failures out of 28,746. One agreeing client-month out of 28,746 does not change the conclusion: the two measures do not reconcile. **The decision is unchanged.** |
| **Type** | Unexplained cross-table mismatch |
| **Dimension violated** | Consistency |
| **Decision** | **Leave both as is.** Do not adjust either table to match the other, and do not add or combine them in one measure until Wildcat explains how they relate. |
| **Justification** | The mismatch is real, but its cause is unknown. The tables might record different things (e.g. different charges or timing), or one might be wrong; the audit cannot tell which. fact_fees is the **internally reconciled billed-fee measure**: amount = aum_basis × bps / 10000 / 12 (F230 PASS) and its AUM matches snapshots (F277 PASS). That makes it the more internally consistent source for billed fees. It has **not** been verified as recognized revenue. |
| **Verification** | None to apply. `README_clean.md` will state both measures, the mismatch, and the rule against combining them. |
| **Risk if wrong** | Combining or substituting one for the other could misstate fees in either direction. Preserving both and documenting the gap keeps the question open for Wildcat to answer. |

## Issue 14. Meaning of Dividend shares (exploratory)

| Field | Entry |
|---|---|
| **Table / column** | fact_transactions.shares, amount (txn_type = Dividend) |
| **Evidence** | All 53,864 raw dividends satisfy amount = shares × price (F239 PASS). F040, an exploratory comparison: of 23,751 dividends where an earlier in-extract position can be estimated, 172 (0.724%) have shares within 1% of it, with a median shares/held ratio of 0.68. Another 30,113 have no earlier Buy in the extract. F056: dividends occur on all four asset classes. **(raw overlap count)** 38 dividends are quarantined orphans, so clean data has 53,826. |
| **Type** | Unresolved interpretation, not a confirmed defect |
| **Dimension violated** | None confirmed |
| **Decision** | **Leave as is.** Do not recompute dividend shares or amounts. |
| **Justification** | The holdings comparison is **exploratory only**. The extract has no opening positions, transfers, reinvestment lots or corporate actions, so holdings cannot be rebuilt reliably. It neither confirms nor rules out any reading of the shares field. |
| **Verification** | **After:** on all 53,826 retained Dividend rows, assert that shares, price and amount equal their raw text values exactly. security_id is the only column allowed to change, and only by the planned Issue 2 standardization (clean value = raw value with the `.0` suffix removed). Every other column also equals its raw value. |
| **Risk if wrong** | If dividend amounts record something other than cash income, income totals could be misstated. Dividend totals are reported with this caveat. |

## Issue 15. Conditional blanks

| Field | Entry |
|---|---|
| **Table / column** | dim_security.sector, dim_security.expense_ratio_bps; fact_transactions.security_id, shares, price |
| **Evidence** | F027: sector is blank on exactly the 219 securities whose asset_class is Fixed Income, Alternative or Cash Equivalent, and filled on all Equity rows. F028: expense_ratio_bps is blank on exactly the 281 securities with is_etf = False, and filled on all ETFs. F031 to F033 and F050: security_id, shares and price are blank on 101,597 raw transactions (34.005%), exactly the Deposit, Withdrawal and Advisory Fee rows. The reverse checks all pass (F141 to F144, F198 to F203). **(raw overlap count)** 69 of those 101,597 rows are quarantined orphans, so each of the three transaction columns has 101,528 blanks in clean data. |
| **Type** | Legitimate structure, based on the observed conditions |
| **Dimension violated** | None |
| **Decision** | **Leave as is.** Do not fill with 0, "N/A" or "Unknown". |
| **Justification** | The blanks line up exactly with category conditions in both directions. That is consistent with "not applicable for this category" rather than missing data. The audit shows the pattern, not Wildcat's reasons for it. Filling with 0 would distort averages (e.g. a 0 bps expense ratio). |
| **Verification** | **After:** dim_security blanks unchanged (219, 281). Transaction blanks: 101,597 raw = 101,528 clean + 69 quarantined, for each of the three columns. Conditional-blank rules still pass on clean data. |
| **Risk if wrong** | If some blanks are real gaps, sector or expense reporting would be incomplete for those securities. Noted in README_clean. |

## Issue 16. ZIP codes with leading zeros

| Field | Entry |
|---|---|
| **Table / column** | dim_client.zip_code |
| **Evidence** | F026: 232 of 2,525 raw ZIPs start with 0 (e.g. 02635). All are 5 digits (F103 PASS; profile min_len = max_len = 5). **(raw overlap count)** 4 of the 232 belong to quarantined copies. |
| **Type** | Legitimate structure |
| **Dimension violated** | None |
| **Decision** | **Leave as is.** Keep as text; the BI tool must load it as text. |
| **Justification** | ZIP is a code, not a number. A numeric read turns 02635 into 2635. |
| **Verification** | **After:** 232 raw = 228 clean + 4 quarantined, all still starting with 0; every clean ZIP is 5 characters. |
| **Risk if wrong** | None to the data. The risk comes only from loading the file incorrectly, which README settings address. |

## Issue 17. The word "None" in advisor certifications

| Field | Entry |
|---|---|
| **Table / column** | dim_advisor.certifications |
| **Evidence** | F025: 6 of 25 advisors have the literal value `None`. Other values are CFA, CFP, `CFP, CFA` and `CFP, CIMA`; no field is blank. |
| **Type** | Legitimate structure. "None" reads as "no certification", a real answer. |
| **Dimension violated** | None |
| **Decision** | **Leave as is.** Keep the text `None`. |
| **Justification** | Blanking it would lose the difference between "no certification" and "unknown". The README warns that pandas reads `None` as null by default. |
| **Verification** | **After:** 6 values still equal `None`. |
| **Risk if wrong** | If "None" meant "not recorded", six advisors would be counted as uncertified. Low impact on 25 rows. |

## Issue 18. Numbers in scientific notation

| Field | Entry |
|---|---|
| **Table / column** | fact_portfolio_snapshot.return_ytd, active_alpha_ytd |
| **Evidence** | F029: 135 return values (e.g. `9.9e-05`). F030: 756 alpha values (e.g. `-1.9e-05`). All parse as floats (F171 PASS) and pass the alpha reconciliation (F236). |
| **Type** | Format difference only |
| **Dimension violated** | None (minor text-format Consistency) |
| **Decision** | **Leave as is.** |
| **Justification** | BI tools read `9.9e-05` as 0.000099. Rewriting would add 891 log entries with no change in value. |
| **Verification** | **After:** 0 type-validity failures in both columns. |
| **Risk if wrong** | None to values. |

## Issue 19. Monthly rows dated before the client start date, same month

| Field | Entry |
|---|---|
| **Table / column** | fact_fees.fee_date, fact_portfolio_snapshot.snapshot_date vs dim_client.client_since |
| **Evidence** | F053: 858 fee rows and F054: 930 snapshots are dated before client_since, always in the same month. None are in an earlier month (F275, F280 PASS). No transaction precedes client_since (F286, F287 PASS). Monthly rows are always stamped on the 1st (F231, F235 PASS). |
| **Type** | Legitimate structure |
| **Dimension violated** | None |
| **Decision** | **Leave as is.** |
| **Justification** | A client joining on the 18th has a first monthly row stamped on the 1st of that month. |
| **Verification** | **After:** the "earlier month" checks still return 0. |
| **Risk if wrong** | None. |

## Issue 20. Weekday market holidays marked as trading days

| Field | Entry |
|---|---|
| **Table / column** | dim_date.is_trading_day |
| **Evidence** | F034: 522 non-trading days equal 522 weekend days, so no weekday is marked non-trading. All other calendar attributes match the date (F213 to F223 PASS). |
| **Type** | Source limitation |
| **Dimension violated** | Accuracy/Plausibility (minor) |
| **Decision** | **Leave as is.** |
| **Justification** | Adding an exchange-holiday calendar would bring in outside data that is not part of this extract. The column is correct for weekends. |
| **Verification** | **After:** dim_date unchanged. |
| **Risk if wrong** | Weekday market holidays are counted as trading days, so trading-day counts are somewhat overstated. Noted in README_clean. |

## Issue 21. Same security name on different tickers

| Field | Entry |
|---|---|
| **Table / column** | dim_security.name |
| **Evidence** | F036 / F037: 3 pairs (6 rows) share a name with different tickers: 38 OLAB / 62 YXPS, 317 RONV / 371 YMS, 388 PPJV / 395 UFA. Tickers are unique (F137 PASS). |
| **Type** | Not resolved. These may be separate securities from one issuer (e.g. different funds or share classes), but the data does not prove it. |
| **Dimension violated** | None confirmed (possible Uniqueness) |
| **Decision** | **Leave as is.** |
| **Justification** | Different tickers suggest different securities, and merging them would combine transaction histories with no evidence that they are the same. |
| **Verification** | None. |
| **Risk if wrong** | If two rows are the same security, its activity is split across two IDs. Joins use security_id, so nothing breaks. Noted in README_clean. |

## Issue 22. Dimension keys no fact uses

| Field | Entry |
|---|---|
| **Table / column** | dim_benchmark, dim_date (as parents) |
| **Evidence** | F042: benchmarks 6 and 8 are not used by any security. F043: snapshots use only benchmarks 1, 3 and 8. F047 / F048: 1,767 of 1,827 dates are not used by the monthly fee and snapshot tables. F049: only 2024-12-31 has no transaction. |
| **Type** | Legitimate structure |
| **Dimension violated** | None |
| **Decision** | **Leave as is.** |
| **Justification** | A dimension may contain members no fact uses (a full calendar, benchmarks used only by securities). Removing them would break future loads. |
| **Verification** | None. |
| **Risk if wrong** | None. |

---

## INFO findings reviewed that need no decision

- F017 to F024: raw row and column counts. These are the baseline for the `raw = clean + quarantined` proof.
- F035: dim_date covers 2020-01-01 to 2024-12-31.
