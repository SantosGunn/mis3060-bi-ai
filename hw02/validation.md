# HW02 Validation

## 2A — Known-Answer Benchmarks
| Check | Expected | Your Script Produced | Match? | Notes |
|---|---|---|---|---|
| Dataset shape | (298772, 9) | (298772, 9) | Yes | Expected rows and columns. |
| Null count — security_id | 101,597 | 101,597 | Yes | 34% of rows. |
| Null count — amount | 0 | 0 | Yes | No missing amounts. |
| Unique txn_type values | 6 | 6 | Yes | Six types in the value counts. |
| Count of Buy transactions | 83,556 | 83,556 | Yes | Matches benchmark. |
| txn_date data type | object | str | No | Text dtype differs; investigation below. |
| Earliest txn_date | 2020-01-01 | 2020-01-01 | Yes | Matches benchmark. |
| Latest txn_date | 2024-12-30 | 2024-12-30 | Yes | Matches benchmark. |
| Duplicate txn_id count | 0 | 0 | Yes | No repeated transaction IDs. |
| Mean amount | $54,075.17 | $54,075.17 | Yes | Matches to two decimal places. |
| Median amount | $41,220.48 | $41,220.49 | No | Rounding difference; investigation below. |
| Skewness of amount | 1.15 | 1.1463 | Yes | Rounds to 1.15. |
| Correlation shares–amount | 0.65 | 0.65 | Yes | Matches to two decimal places. |
| Correlation price–amount | 0.64 | 0.64 | Yes | Matches to two decimal places. |
| Correlation shares–price | 0.00 | 0.00 | Yes | Matches to two decimal places. |
| Negative shares count (Buy only) | 836 | 836 | Yes | All negative shares occur in Buy rows. |
| Profile file created | Yes | Yes | Yes | hw02_profile.txt saved. |
| Chart files created (3) | Yes | Yes | Yes | All three saved and visually reviewed. |

### Discrepancy Investigation

**Date type:** My environment uses pandas 3.0.6 and loads txn_date as str rather than object. I ran verify_discrepancies.py on the real CSV. It confirmed that the column contains text, is not a datetime type, and has identical values when loaded explicitly as object.

**Median:** The verification script found that the two middle amounts are $41,219.90 and $41,221.07. Their exact average is $41,220.485. The original script's f-string displays $41,220.49, while NumPy and pandas rounding display $41,220.48. This explains the one-cent difference without changing the source data.

### Claude Conversation About the Discrepancies

**My question:**

I ran the script on the real dataset. It completed and saved the profile and three charts, but two results differ from my assignment’s benchmarks:

1. txn_date is reported as str; the expected type is object. My installed pandas version is 3.0.6. Investigate whether the pandas version explains this difference and whether the column is still text rather than a datetime type.
2. The median amount prints as 41,220.49; the expected value is 41,220.48. Help me independently check the two middle amounts and their unrounded average to determine why the displayed result differs.

There is also a MatplotlibDeprecationWarning about vert=False. Explain whether this affects the saved chart.

Do not force results to match the benchmarks or change the source CSV. Explain the discrepancies and give me any verification commands I should run.

I included my full terminal output with this question.

**Claude’s response:**

Neither difference is a wrong answer. The data is the same, and the two gaps come from how pandas labels text and how the median gets rounded. I've attached `verify_discrepancies.py` so you can confirm both on the real CSV. It only reads the file. Put it in `hw02/` and run:

`python hw02/verify_discrepancies.py`

I tested it on a fake dataset where I planted the two middle amounts, not on your actual CSV.

**1. str instead of object: the pandas version explains it, and the column is still text**

- pandas 3.0 changed the default so text columns load as a new string type, printed as str. pandas 2.x loaded the same column as object and printed object, so your benchmark was probably made on pandas 2.x.
- It's the same text either way. Nothing gets converted to a date when the file loads. The script only uses a temporary datetime copy in section 8.
- The check prints `is text (string dtype)? True` and `is datetime? False`. It also reloads the column with `dtype=object` (the pandas 2 behavior) and should print `values identical? True`.

If your write-up needs to say why, one sentence covers it: "pandas 3.0 loads text as the str dtype, which pandas 2.x reported as object."

**2. Median 41,220.49 vs 41,220.48: a rounding tie, most likely**

- You have 298,772 amounts, an even number, so the median is the average of the two middle values (positions 149,386 and 149,387 once sorted).
- If those two add up to an odd number of cents, the unrounded average ends in exactly half a cent: 41,220.485.
- A computer can't store 41,220.485 exactly. It holds 41220.485000000000582…, which is a hair above the halfway point.
- The script prints with `f"{x:,.2f}"`, which rounds that stored value correctly and gives .49.
- pandas `.round(2)` and `np.round(x, 2)` multiply by 100 and round an exact .5 to the nearest even number, which gives .48. Your benchmark was most likely made with one of those.

When you run the check, look for three lines: the two middle values, `exact decimal average: 41220.485`, and the rounding lines showing .49 for the f-string and .48 for np.round/Series.round. If the exact average isn't a .xx5 value, this explanation is wrong and the cause is something else. In that case, send me the output.

One thing I should own: section 11 of my script rounds with pandas `.round(2)`, but section 10 uses the f-string. So the script itself applies two rounding rules to tie values. It doesn't change any real numbers, but you might mention it or pick one rule. I haven't changed anything to match the benchmark.

**3. The vert=False warning doesn't affect your chart**

It's only a notice that this option will go away later. Matplotlib 3.11 still accepts it, so box_amount_by_type.png came out horizontal as intended. You can confirm by opening the PNG. The option will stop working in Matplotlib 3.13. The future-proof version swaps `vert=False` for `orientation="horizontal"` in the `ax.boxplot(...)` call, and the chart looks identical. I can make that edit if you want.

### My Verification Results

I ran `python hw02/verify_discrepancies.py` on the actual CSV. It confirmed:

- txn_date contains text and is not a datetime type.
- Loading txn_date as object gives identical values.
- The two middle amounts are 41219.9 and 41221.07.
- Their exact decimal average is 41220.485.
- F-string formatting gives 41220.49.
- NumPy and pandas rounding give 41220.48.

These checks explain both benchmark differences. I did not change the raw CSV or force the results to match.

## 2B — Explain the Code and Output

### 1. Predicted Output Compared with Actual Output

I used a new Claude Cowork conversation to review the script. Claude explained the output structure but could not predict exact data values without the CSV, so most numerical results were placeholders. The actual output followed the structure it described. Claude suggested txn_date would appear as object, but my output showed str, which the separate verification explained. Its example involving negative Sell shares did not apply: all 836 negative-share transactions were Buys.

### 2. Unexpected Results Flagged by Claude

Claude flagged the negative-share Buys, unusually large Dividend amounts, the large difference between the mean and median Advisory Fee, gaps in client IDs, and the fact that amounts are positive across all transaction types. It also suggested the data might be synthetic. These were concerns or hypotheses rather than confirmed errors. After my follow-up question, Claude acknowledged that negative-share Buys could be legitimate reversals and should not automatically be corrected or removed.

### 3. Missing security_id Values

Claude identified the 101,597 missing security_id values and explained that Deposit, Withdrawal, and Advisory Fee transactions do not involve a specific security. Their counts add up to 35,981 + 29,850 + 35,766 = 101,597. The missing values therefore make business sense rather than automatically indicating incomplete data.

### 4. Date Column Concern

Claude flagged that txn_date is stored as text rather than a datetime type. It needs to be converted before calculating time differences or using date-based operations such as monthly resampling. The script uses a temporary datetime conversion to calculate the date range, while leaving the original column unchanged.

### Chart Review

**Histogram:** The chart matches Claude’s explanation. Most transactions have lower amounts, with a long right tail of larger transactions. The mean ($54,075.17) is higher than the median ($41,220.49), consistent with the reported right skew.

**Box plot:** The chart matches Claude’s explanation. Buy, Sell, and Dividend have similar medians and wide spreads, while Deposit and Withdrawal have narrower distributions centered around $50,000. Advisory Fee has a much lower median and many large outliers, consistent with its mean being much higher than its median. The chart is horizontal as intended despite the warning.

**Scatter plot:** The chart shows a positive relationship between shares and amount, consistent with the reported correlation of 0.65. The negative-share Buy transactions appear to the left of zero with positive amounts. Deposit, Withdrawal, and Advisory Fee show n=0 because their shares are missing, so they cannot be plotted. Overlapping points make Buy, Sell, and Dividend difficult to distinguish on the positive side.

### Follow-up Question and Answer

**Question:** You described the 836 negative-share Buy transactions as almost certainly sign errors. Could they instead be legitimate corrections or reversals? What additional records would distinguish those explanations, and should I preserve and flag these rows until I know? Also, does a Pearson correlation rounded to 0.00 prove that shares and price are independent?

**Claude’s answer**
Yes, they could be legitimate reversals, and I overstated it. The data supports "suspicious and inconsistent," not "almost certainly errors." Preserving and flagging them is the right call.
Pearson only measures straight-line relationships. A U-shaped, curved, or variance-changing relationship can have r ≈ 0 and still be strongly dependent.

## 2C — Business Check & Cross-Validation

### 1. Missing Security Information

Deposits, withdrawals, and advisory fees involve moving cash or charging for a service rather than buying or selling a specific security. It makes sense that these transactions would have no security ID, shares, or price. Their counts add up to 35,981 + 29,850 + 35,766 = 101,597, which matches the number of missing values in each column.

### 2. More Buys Than Sells

Having 83,556 Buys compared with 59,755 Sells could mean clients were adding money to their portfolios or reinvesting cash over the five years. However, transaction counts alone do not prove that more money was invested than sold, since individual transactions can have different dollar amounts. I would compare total Buy and Sell amounts before drawing that conclusion.

### 3. Dates Stored as Text

If the dates stayed as strings, subtracting them to calculate the days between transactions would cause an error. The script would first need to convert txn_date to a datetime type, sort the transactions by date, and then calculate the time differences. This allows Python to work with actual dates instead of text.

### 4. Clients per Advisor

With 2,700 clients and 25 advisors, the average is 108 clients per advisor. That seems plausible if advisors have support staff and technology to help manage accounts. However, the workload would depend on how much attention each client needs, and the average does not show whether clients are evenly distributed across advisors.

### 5. Negative Shares on Buy Transactions

The 836 negative-share Buys could be sign errors made when entering or importing the data. Another possibility is that they reverse or correct earlier purchases. I would check the data dictionary, look for matching original transactions, and review audit logs or custodian records to understand what happened. Until then, I would keep these rows unchanged and flag them for investigation rather than automatically deleting them or making the shares positive.



### 6. Cross-Validation Results

I ran both scripts in the VS Code terminal. Direct filtering returned 83,556 Buy transactions, with no case or whitespace variants. The subtraction method counted 298,772 total rows and subtracted 215,216 transactions across the other five types, leaving 83,556. It also confirmed that all remaining rows were labeled Buy.

### 7. Agreement Between Methods

Both methods returned 83,556, matching the assignment benchmark. There was no discrepancy to investigate.

### 8. Why Subtraction Is Useful

Subtraction checks the count using different logic from direct filtering, which can help reveal filtering mistakes or overlooked categories. Agreement increases confidence, although it does not guarantee that both scripts are free of errors.