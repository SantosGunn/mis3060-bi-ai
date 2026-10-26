# Clean Wildcat Capital data (`data/clean/`)

Produced by `scripts/02_clean.py` from `data/raw/` following `decision_log.md`. Raw files are never modified. Every changed cell is in `data/audit/value_changes.csv`; every step is in `data/audit/cleaning_log.csv`; removed rows are in `data/audit/quarantine_*.csv` with their raw values.

## Row counts

| Table | Clean rows | Quarantined |
|---|---:|---:|
| dim_advisor | 25 | 0 |
| dim_benchmark | 8 | 0 |
| dim_client | 2,500 | 25 |
| dim_date | 1,827 | 0 |
| dim_security | 500 | 0 |
| fact_fees | 122,197 | 0 |
| fact_portfolio_snapshot | 129,547 | 0 |
| fact_transactions | 298,572 | 200 |

## How to load these files

- Read every file **as text first**. In pandas: `pd.read_csv(path, dtype=str, keep_default_na=False)`. Default parsing turns `None` into null, drops ZIP leading zeros and reads `529` as a number.
- Then set the column types below. Blanks are meaningful (see limitations); load them as null, never as 0.

## Relationships (13, all many-to-one, fact/child → dimension/parent)

| # | From (many) | To (one) | Note |
|---|---|---|---|
| 1 | `dim_client.advisor_id` | `dim_advisor.advisor_id` |  |
| 2 | `dim_security.benchmark_id` | `dim_benchmark.benchmark_id` |  |
| 3 | `fact_fees.client_id` | `dim_client.client_id` |  |
| 4 | `fact_fees.advisor_id` | `dim_advisor.advisor_id` |  |
| 5 | `fact_portfolio_snapshot.client_id` | `dim_client.client_id` |  |
| 6 | `fact_portfolio_snapshot.advisor_id` | `dim_advisor.advisor_id` |  |
| 7 | `fact_portfolio_snapshot.benchmark_id` | `dim_benchmark.benchmark_id` |  |
| 8 | `fact_transactions.client_id` | `dim_client.client_id` |  |
| 9 | `fact_transactions.advisor_id` | `dim_advisor.advisor_id` |  |
| 10 | `fact_transactions.security_id` | `dim_security.security_id` | blank on Deposit / Withdrawal / Advisory Fee rows (no security) |
| 11 | `fact_fees.fee_date` | `dim_date.date` | monthly, always the 1st |
| 12 | `fact_portfolio_snapshot.snapshot_date` | `dim_date.date` | monthly, always the 1st |
| 13 | `fact_transactions.txn_date` | `dim_date.date` |  |

Every key now matches its parent as text (no `45.0`-style IDs remain).

## Column types for a BI tool

**dim_advisor**

| Column | Type |
|---|---|
| advisor_id | Whole number (key) |
| first_name | Text |
| last_name | Text |
| region | Text |
| years_experience | Whole number |
| aum_target_mm | Whole number |
| certifications | Text (keep the word `None`; do not treat it as null) |

**dim_benchmark**

| Column | Type |
|---|---|
| benchmark_id | Whole number (key) |
| name | Text |
| asset_class | Text |
| ticker_proxy | Text |

**dim_client**

| Column | Type |
|---|---|
| client_id | Whole number (key) |
| first_name | Text |
| last_name | Text |
| age | Whole number |
| city | Text |
| state | Text (2-letter code) |
| zip_code | **Text** (leading zeros) |
| risk_profile | Text (blank allowed) |
| client_tier | Text |
| primary_account_type | Text (`529` is a category, not a number) |
| initial_aum | Fixed decimal (currency) |
| client_since | Date (YYYY-MM-DD) |
| advisor_id | Whole number (FK) |
| is_active | True/False |
| risk_profile_missing_flag | Whole number 0/1 |

**dim_date**

| Column | Type |
|---|---|
| date_id | Whole number (key) |
| date | Date (YYYY-MM-DD; join key for facts) |
| year | Whole number |
| quarter | Whole number |
| month | Whole number |
| month_name | Text (sort by month) |
| week_of_year | Whole number (ISO week) |
| day_of_week | Text |
| is_month_end | Whole number 0/1 |
| is_quarter_end | Whole number 0/1 |
| is_year_end | Whole number 0/1 |
| is_trading_day | Whole number 0/1 |

**dim_security**

| Column | Type |
|---|---|
| security_id | Whole number (key) |
| ticker | Text |
| name | Text |
| asset_class | Text |
| sector | Text (blank for non-equity) |
| benchmark_id | Whole number (FK) |
| is_etf | True/False |
| expense_ratio_bps | Decimal (blank for non-ETFs; do not fill with 0) |

**fact_fees**

| Column | Type |
|---|---|
| fee_id | Whole number (key) |
| client_id | Whole number (FK) |
| advisor_id | Whole number (FK) |
| fee_date | Date (FK to dim_date.date) |
| fee_type | Text |
| aum_basis | Fixed decimal (currency) |
| bps_charged | Decimal |
| amount | Fixed decimal (currency) |
| aum_basis_at_floor_flag | Whole number 0/1 |

**fact_portfolio_snapshot**

| Column | Type |
|---|---|
| snapshot_id | Whole number (key) |
| client_id | Whole number (FK) |
| advisor_id | Whole number (FK) |
| benchmark_id | Whole number (FK) |
| snapshot_date | Date (FK to dim_date.date) |
| year | Whole number |
| month | Whole number |
| aum | Fixed decimal (currency) |
| return_ytd | Decimal (fraction: 0.0928 = 9.28%; some values in e-notation) |
| benchmark_return_ytd | Decimal (fraction) |
| active_alpha_ytd | Decimal (fraction; some values in e-notation) |
| cash_pct | Decimal (fraction) |
| account_type | Text |
| return_outlier_flag | Whole number 0/1 |
| aum_at_floor_flag | Whole number 0/1 |

**fact_transactions**

| Column | Type |
|---|---|
| txn_id | Whole number (key) |
| client_id | Whole number (FK) |
| advisor_id | Whole number (FK) |
| security_id | Whole number (FK; blank on cash-type rows) |
| txn_date | Date (FK to dim_date.date) |
| txn_type | Text |
| shares | Decimal (blank on cash-type rows) |
| price | Decimal (blank on cash-type rows) |
| amount | Fixed decimal (currency, always positive) |
| shares_sign_corrected_flag | Whole number 0/1 |
| after_last_snapshot_flag | Whole number 0/1 |

## Added flag columns (0/1; 1 = condition true)

| Table.column | Meaning | Rows = 1 |
|---|---|---:|
| dim_client.risk_profile_missing_flag | risk_profile is blank (not filled) | 75 |
| fact_transactions.shares_sign_corrected_flag | the shares sign on this Buy was changed from negative to positive in cleaning | 835 |
| fact_transactions.after_last_snapshot_flag | inactive client; transaction month is after the client's last snapshot month | 2,410 |
| fact_portfolio_snapshot.return_outlier_flag | return_ytd or active_alpha_ytd outside the assumed band [-0.6, 1.0]; investigate, do not auto-exclude | 2,440 |
| fact_portfolio_snapshot.aum_at_floor_flag | aum is exactly 1,000.00 | 420 |
| fact_fees.aum_basis_at_floor_flag | aum_basis is exactly 1,000.00 | 386 |

## Changes made

- dim_client.state: 77 full names → 2-letter codes (format only; the state itself was not verified).
- fact_transactions.security_id: 197,044 values `45.0` → `45`.
- fact_transactions.shares: 835 negative Buy share counts made positive, only where |shares| × price = amount within $0.01.
- fact_portfolio_snapshot.return_ytd: 300 `x%` values → x/100, verified against benchmark_return_ytd and active_alpha_ytd.
- dim_client: 25 probable-duplicate clients quarantined.
- fact_transactions: 200 orphan-client transactions quarantined.

## Known limitations (kept on purpose; see decision_log.md)

1. **Probable duplicate clients (Issue 5).** 25 client IDs with no facts were quarantined because they matched a fact-bearing client on every column except client_id and last_name (first_name equal), and last_name differed only as a strict prefix. They are strongly supported duplicates, not confirmed identities. The kept last_name is the spelling attached to the account history, not a verified legal name.
2. **Orphan transactions removed (Issue 4).** 200 transactions point at client IDs not in dim_client. If those clients exist elsewhere, client activity is understated; the rows can be restored from the quarantine file.
3. **Share sign convention is inferred (Issue 3).** Shares are treated as always positive with direction from txn_type. This is inferred from the data, not documented. If a negative Buy was really a reversal, the corrected row overstates holdings; use shares_sign_corrected_flag to find them.
4. **State standardization is format only (Issue 6).** No check that the state is correct.
5. **Missing risk profiles (Issue 7).** Left blank and flagged. These clients use benchmark 3, the same as Balanced clients, but that does not prove their risk tolerance.
6. **Extreme returns and alpha (Issue 8).** Values outside the assumed band are flagged, not changed. The band is an assumption. Flagged rows should be investigated; whether to include them is a decision for each analysis.
7. **AUM at exactly 1,000.00 (Issue 9).** May be a system floor; not confirmed. Not assumed to cause the extreme returns.
8. **Activity after an inactive client's last snapshot (Issue 10).** Flagged, not removed. No account-closing date exists to judge it.
9. **Transactions on non-trading days (Issue 11).** About 28% of trades fall on weekends, the same share as weekend days in the calendar. Dates were not moved. Day-of-week and price-on-date analysis is unreliable. Join to dim_date.is_trading_day to identify them.
10. **Snapshot months without a fee row (Issue 12).** No fee rows were created. If billing data is missing, billed fees are understated.
11. **Advisory Fee transactions do not match fact_fees (Issue 13).** None of the overlapping client-months match. Keep both; **do not add or combine them in one measure** until Wildcat explains the relationship. fact_fees is the internally reconciled billed-fee measure; it is not verified recognized revenue.
12. **Dividend shares (Issue 14).** The meaning of shares on Dividend rows is unresolved. A holdings comparison was exploratory only (no opening positions, transfers, reinvestment lots or corporate actions). Report dividend totals with this caveat.
13. **Conditional blanks (Issue 15).** sector is blank exactly for Fixed Income, Alternative and Cash Equivalent securities; expense_ratio_bps is blank exactly for non-ETFs; security_id, shares and price are blank exactly on Deposit, Withdrawal and Advisory Fee rows. Treated as not applicable; never fill with 0.
14. **ZIP codes (Issue 16) and `None` certifications (Issue 17)** must be loaded as text.
15. **Scientific notation (Issue 18).** Some small returns/alpha are written like `9.9e-05`; they are valid decimals and were left as written.
16. **Monthly rows dated before client_since in the same month (Issue 19)** are expected: monthly rows are stamped on the 1st.
17. **Market holidays (Issue 20).** dim_date marks every weekday as a trading day, so weekday market holidays count as trading days.
18. **Same security name on different tickers (Issue 21).** Three pairs; may be separate securities, not proven. Not merged.
19. **Unused dimension members (Issue 22).** Some benchmarks and most dates are not used by every fact table; this is expected.
