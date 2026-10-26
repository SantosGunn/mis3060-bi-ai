# HW04 – Wildcat Capital data-quality audit

Assignment: [HW04_Data_Cleaning.md](HW04_Data_Cleaning.md). Part A is done; Part B ([decision_log.md](decision_log.md)) is reviewed; Part C (`scripts/02_clean.py`) is reviewed; Parts D–E are not started.

## Structure

```
hw04/
  decision_log.md            Part B decision log (instructions for 02_clean.py)
  data/raw/                  the eight source CSVs (read only, never modified)
  data/clean/                Part C output: the 8 clean tables + README_clean.md
  data/audit/                cleaning_log.csv, value_changes.csv, quarantine_*.csv
  scripts/01_profile.py      Part A audit / profiler
  scripts/02_clean.py        Part C cleaning program (implements decision_log.md)
  scripts/verify_setup.py    stale copy of the pre-review profiler (see "Noted, not changed")
  reports/profile_raw.csv    per-column profile
  reports/dq_summary_raw.csv one row per check
  reports/near_dup_clients_raw.csv  per-client near-duplicate evidence
```

## How to run

From `hw04/`:

```
.\.venv\Scripts\python.exe scripts\01_profile.py
.\.venv\Scripts\python.exe scripts\02_clean.py
```

`02_clean.py` stops with a named error, before writing anything, if any precondition or post-check fails.

## Part A: audit (`scripts/01_profile.py`)

Reads all eight CSVs as text (`dtype=str, keep_default_na=False`). Row and column counts match the assignment table. Writes:

| File | Contents |
|---|---|
| `reports/profile_raw.csv` | Per-column profile (75 columns, 8 tables): blanks, literal null tokens, distinct count, top values, value shapes, parse failures vs expected type, whitespace, mixed formats, length and numeric/date min/max |
| `reports/dq_summary_raw.csv` | One row per check: 7 ERROR, 9 WARN, 40 INFO, 231 PASS |
| `reports/near_dup_clients_raw.csv` | Per-client evidence for the 50 near-duplicate `dim_client` rows |

Check groups: (1) column level: type, allowed values, hard ranges, plausibility bands, key uniqueness, conditional blanks; (2) single table: exact duplicates, duplicates ignoring the PK, near-duplicates, row contradictions; (3) referential integrity: all 13 relationships (10 ID-based, 3 to `dim_date`); (4) cross-table business rules.

Severity follows the assignment: ERROR, WARN, INFO. PASS rows are also kept, so the summary shows which checks ran and found nothing.

### Main findings (raw extract)

- `fact_transactions.security_id`: all 197,175 nonblank values are stored as floats (`'45.0'`). They match `dim_security` only after normalization.
- `fact_transactions`: 836 Buys have negative `shares`. All 836 reconcile to `amount` if the sign is ignored.
- `fact_transactions.client_id`: 200 rows reference 200 client ids that are missing from `dim_client`.
- `fact_portfolio_snapshot.return_ytd`: 300 values carry a `%` suffix. All 300 reconcile with alpha only after dividing by 100.
- `dim_client`: 76 blank `risk_profile` values and 78 full state names (e.g. `Pennsylvania`).
- `dim_client`: 25 near-duplicate pairs whose `last_name` differs by a prefix: 23 copies are truncated (`Jacobso`), 2 are extended (`Pacen`, `Leen`). In every pair, the copy is an id in 2501–2525 with no facts, and the original id carries all the facts.
- Buy/Sell on weekends (40,649 rows). Snapshot months with no fee row (7,350). Advisory Fee transactions never reconcile to `fact_fees` (median ratio 3.11). 2,410 transactions after an inactive client's last snapshot.

### Assumptions (inferred, not documented)

No Wildcat data dictionary was supplied. These rules come from the data or from general domain knowledge, and the profiler applies them as stated:

- **Allowed-value lists are inferred.** The lists for `region`, `risk_profile`, `client_tier`, `primary_account_type` / `account_type`, `fee_type`, `txn_type`, `asset_class` and `day_of_week` were built from the values observed in the extract, plus standard US state codes. They are treated as ERROR (WARN for `state`), but they are not documented domains. A legitimate value that simply did not appear would be missed, and an unlisted legitimate value would be flagged.
- **Sign conventions are inferred.** The rule "`shares` and `amount` are positive; `txn_type` carries the direction" comes from the data: Sell rows carry positive shares and every `amount` is positive. The ERROR on the 836 negative-share Buys depends on this assumption. Fee and AUM positivity follow the same reasoning.
- **Plausibility bands are assumptions (WARN):** advisor experience ≤ 50 years; AUM target $1M–$10B; expense ratio and fee ≤ 300 bps; client age 18–110; `client_since` ≥ 1950; YTD return and alpha in [−0.6, 1.0].
- **Client-tier AUM bands** (<$500k Retail, $500k–5M HNW, ≥$5M UHNW) are assumptions.
- **Dividend holdings comparison is exploratory.** Net shares held are rebuilt only from in-extract Buys and Sells. Opening positions, transfers, reinvestment lots and corporate actions such as splits are not in the extract. Only 172 of 23,751 dividends have `shares` within 1% of the rebuilt position, but that result can neither confirm nor rule out what dividend `shares` means. The only firm result is that `amount = shares × price` holds on all 53,864 dividends.

## Claude Code review notes

### Round 1 – profiler logic

| # | Flagged | Change |
|---|---|---|
| 1 | `near_duplicates()` used `any()` for prefix matching across name columns, so an identical first name made any last-name difference count as "truncated/extended". | Each compare column is now classified separately (identical / case-whitespace / truncated-extended / other). A truncation needs a real difference and a nonblank shorter value. Labels name the column, e.g. `last_name:truncated/extended=25`. All pairs within each group are compared. The count is unchanged (25 last-name pairs: 23 truncated, 2 extended), but it now rests on the right test. |
| 2 | Business assumptions were hard ERROR bounds: advisor experience, AUM target, expense ratio, fee bps, age 18–110, `client_since` ≥ 1950. | `ranges` (ERROR) holds only bounds that are true by definition, each with a stated basis. The assumptions moved to `plausible` / `plausible_dates` (WARN). |
| 3 | The finding "Dividend amount equals full position value" (WARN) read `shares × price = amount` as proof that the dividend equals the whole position. | Replaced with an INFO that states only internal consistency, plus an exploratory holdings comparison (see Assumptions). |
| 4 | The non-trading-day merge called `drop_duplicates("date")` on `dim_date` with no report. | It now goes through `unique_lookup()`, which always records key uniqueness with examples and reports duplicates that conflict on `is_trading_day`. The merge uses `validate="many_to_one"` and asserts the row count is unchanged. |
| 5 | The near-duplicate client check reported only aggregate fact-row counts. | It now writes `reports/near_dup_clients_raw.csv`: one row per candidate id with its group, names, unmatched attributes, and per-fact-table counts and date spans. This is evidence only; no quarantine decision is made. |
| – | `Series.dt.dayofweek` deprecation warning. | Switched to `dt.day_of_week`. |

### Round 2 – Part A requirements check against HW04_Data_Cleaning.md

| Flagged | Change |
|---|---|
| "Must work on **any** table": for a column with no schema entry, `infer_type` assigned a type only when ≥95% of values parsed. Otherwise it fell back to `str`, which hides parse failures and mixed formats. A test table with `$2.00` among numbers and `01/02/2024` / `2024-13-01` among dates showed 0 parse failures. | `infer_type` now picks the type most nonblank values parse as, provided at least half do; ties go to the narrower type. Values with leading zeros stay text. On the test table, the bad values are now reported as parse failures and mixed formats. The eight Wildcat tables are unaffected because every column has a schema type: `profile_raw.csv` is byte-identical after the rerun. |
| The dividend holdings finding could read as conclusive. | The finding is renamed "(exploratory)", and its note lists the missing data: opening positions, transfers, reinvestment lots, corporate actions. |
| The repo-root `.gitignore` ignores `*.csv`, and its exception `!hw*/*.csv` does not reach `hw04/reports/`, so the required `profile_raw.csv` and `dq_summary_raw.csv` would never have been committed. | Added `!reports/*.csv` to `hw04/.gitignore`; the root file is unchanged. `data/raw/` stays ignored. |
| README lacked the "structure" section the submission checklist asks for, and did not mark the inferred rules as assumptions. | Added the Structure section and the Assumptions section. |

Checked and met, no change: per-column profile metrics; the four check groups; ERROR/WARN/INFO tagging; all 13 relationships; text-only reads; both required report files.

### Round 3 – Part B decision log review

Checked `decision_log.md` against Part B, `dq_summary_raw.csv`, `near_dup_clients_raw.csv` and the raw files. The counts were recomputed independently from raw.

**Verified, no change needed**
- **Coverage:** all 7 ERRORs (F001–F007) and 9 WARNs (F008–F016) are covered by Issues 1–13. Every one of the 40 INFOs is cited. Every finding ID still points at the check it describes.
- **Required fields:** all 22 entries have Table/column, Evidence, Dimension violated, Decision, Justification and Risk.
- **Overlap counts:** all match the raw data, including:
  - 200 orphan rows / 200 keys, by type Buy 58, Dividend 38, Sell 35, Deposit 25, Advisory Fee 24, Withdrawal 20
  - 69 blank and 131 nonblank `security_id` among orphans; 1 negative-share orphan (txn 298603, `-411.3807`)
  - clean counts: 197,044 security IDs, 835 negative Buys, 101,528 conditional blanks, 53,826 dividends, 77 full state names, 75 blank risk profiles, 228 leading-zero ZIPs
  - weekend rows: 40,630 / 143,218 Buy/Sell and 44,316 / 155,354 cash events
  - 2,410 after-last-snapshot transactions; flag bases of 420 and 386 rows at the 1,000.00 floor
- **Order of operations:** the order is sound.
  - Removing the 25 fact-less clients (step 1) does not change the 200 orphans (step 2).
  - Step 1's equality checks run on raw values before step 3 changes state names. This matters because pair 2517/739 both hold `Florida`.
  - Step 4 runs before the step 5 Buy reconciliation; Issue 1 runs before the Issue 8 flag.
  - Quarantine files are built from raw by key, so no quarantined value is ever edited.

**Changed**

| Flagged | Change |
|---|---|
| The quarantine rule promised "byte-for-byte" columns, which pandas cannot guarantee: CSV quoting and line endings can change. | It now promises that every original cell value is preserved exactly as text (read with `dtype=str, keep_default_na=False`; no conversion, trimming or NA substitution), and asserts it per key. Issue 4's verification wording now matches. |
| **Contradiction:** Issue 14 asserted "Dividend rows unchanged", but step 4 standardizes `security_id` on those same rows. | It now asserts that shares, price and amount on the 53,826 retained dividends equal their raw text. `security_id` may change only by the Issue 2 `.0` removal, and all other columns stay equal. |
| Issue 5's "all non-name attributes equal" left open whether client_id and first_name were compared. | It now compares every column except client_id and last_name; first_name must be equal. last_name may differ only as a nonblank, case-sensitive strict prefix (truncated or extended). Evidence added: 25/25 pairs pass all three, and the partners 1267 (blank risk) and 739 (`Florida`) carry the same raw values. |
| `return_outlier_flag` expected sum was "recomputed at run time", which the stop rule cannot assert. | Set to 2,440 (2,157 return + 2,217 alpha − 1,934 both), marked as a raw overlap count. |
| The quarantined orphan amount was to be logged with no expected value. | Expected total added: 10,888,495.37. |
| Issue 20 dimension "Accuracy" was not in the assignment's vocabulary. | Changed to "Accuracy/Plausibility". |
| The coverage note did not say where the INFOs used in Issues 1–13 are cited. | It now lists them and states that F001–F056 are all cited. |

### Round 4 – Part C cleaning program review

Reviewed `scripts/02_clean.py` and its outputs against Part C and the committed `decision_log.md`. Everything below was checked independently by reading the written files back from disk, not by reusing the script's own checks.

**Verified, no change needed**
- **Order and decisions:** steps 1–8 run in the decision-log order (quarantine duplicates → orphans → state → security_id → Buy sign → `%` returns → flags → verify and write). Each repair matches its documented decision. Every step prints rows affected and before/after values, checks its preconditions with `require` and its after-state with `verify`. `verify` also works under `python -O`, unlike a bare `assert`.
- **Raw unchanged:** the script only reads `data/raw`, and it re-reads raw from disk at the end and asserts equality. Rerunning `01_profile.py` on `data/raw` reproduces the committed `reports/*.csv` exactly (0 diff lines).
- **Row counts:** raw = clean + quarantined for all 8 tables: dim_client 2,525 = 2,500 + 25; fact_transactions 298,772 = 298,572 + 200; the other six have 0 quarantined. Clean and quarantined key sets are disjoint, together equal the raw keys, and are unique.
- **Quarantine:** both files keep the raw columns in raw order, and every original cell equals the raw text. Extra columns are only `qa_*`; `qa_retained_client_id` points at 25 distinct clean clients.
- **Change log:** comparing every original cell in clean against raw by primary key gives 198,256 changed cells. These match `value_changes.csv` exactly as a multiset: 0 unlogged, 0 phantom, 0 no-op rows. By column: state 77, return_ytd 300, security_id 197,044, shares 835. In dim_client, only `state` changed.
- **Flags:** all six recomputed independently from the clean data and match their documented meanings and sums: shares_sign_corrected 835 (equal to rows whose sign actually changed), risk_profile_missing 75, return_outlier 2,440, aum_at_floor 420, aum_basis_at_floor 386, after_last_snapshot 2,410.
- **Repairs:** amount = shares × price holds on every traded clean row; all traded shares are positive; alpha reconciles on all snapshots; security_id, client_id and advisor_id text-match their parents 100%.
- **README_clean.md:** has 13 relationships, a BI type for all 81 clean columns, the 6 flags, and 19 known limitations.
- **Repeatable:** two consecutive runs produce byte-identical outputs (SHA-256 of all 13 files) and identical console output.

**Changed**

| Flagged | Change |
|---|---|
| NaN could pass silently, because NaN compares False. Step 5 found and post-checked negative shares with `as_float(shares) < 0`, so an unparseable value such as `(5)` would be neither fixed nor caught. Step 6's after-check counted `gap > tol`, so a blank or non-numeric benchmark or alpha would "reconcile". Step 7 gave an unparseable return or alpha a flag of 0. | Added `numeric()`, a stop rule requiring every relevant value to parse: shares and price on traded rows, all amounts, benchmark, alpha and non-`%` returns, converted returns, AUM and aum_basis. Added `n_outside_tol()`, which counts `not(gap <= tol)` so NaN is a failure. Step 5 also re-checks after the edit that shares are still numeric. Tested by injecting `(5)`, `n/a`, a blank and `abc` into copies of the data: each stops with a named `CleaningError`. On the real data, outputs are unchanged. |
| The README_clean duplicate-client limitation said "every column except last_name". | Now says "except client_id and last_name (first_name equal)", matching the decision log. |
| `hw04/.gitignore`: the root `*.csv` rule hid the Part C deliverables. | Added `!data/clean/*.csv` and `!data/audit/*.csv`. All 12 clean and audit CSVs are now visible to git; `data/raw/` and `.venv/` are still ignored. |

### Noted, not changed

- `scripts/verify_setup.py` is a byte-identical copy of the **pre-review** `01_profile.py` (SHA-256 `08BA22E8…`). It is not identical to the current profiler, so it was not deleted. It is untracked, so git cannot restore it if deleted.
- For `str` columns, `mixed_formats` detects only case/whitespace variants. Abbreviation-vs-full-name mixes (e.g. `PA` vs `Pennsylvania`) show up in `top_shapes` and in the `state` allowed-values WARN, not in the `mixed_formats` flag.
- The business rules in `row_rules()` and `cross_table()` are table-specific by nature; the profiler and column, duplicate and referential checks are generic.
