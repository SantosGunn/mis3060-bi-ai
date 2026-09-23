# HW02 EDA Script Specification

Author: Santos Gunningham

Create one Python script named `hw02_eda.py` for exploring Wildcat Capital’s transaction data. I will run it from my repository’s main folder using `python hw02/hw02_eda.py`.

The script must complete all the following tasks in one run:

1. Load `data/raw/fact_transactions.csv` into a pandas DataFrame without changing the original CSV.

2. Print the dataset’s shape, showing the number of rows and columns.

3. Print every column name and its data type as loaded, before making any conversions.

4. Print the number of missing values in every column.

5. Print descriptive statistics for every numeric column: count, mean, standard deviation, minimum, 25th percentile, median, 75th percentile, and maximum.

6. Print the count and percentage of transactions for each `txn_type`, sorted from most to least frequent.

7. Print the number of unique clients, advisors, and securities. Exclude missing values from these unique counts.

8. Print the earliest and latest `txn_date`. Use a temporary datetime conversion if needed, keeping the original column unchanged for the data-type check.

9. Check for duplicate `txn_id` values and print the number of duplicate entries beyond their first occurrence.

10. Print the mean, median, and skewness of `amount`.

11. Group transactions by `txn_type`. For each type, print the transaction count, mean amount, and median amount. Round the amounts to two decimal places and sort by mean amount from highest to lowest.

12. Calculate and print the correlation matrix for `shares`, `price`, and `amount`, rounded to two decimal places. List the three distinct variable pairs ranked by absolute correlation strength. Exclude self-correlations and do not list the same pair twice.

13. For each `txn_type`, print the minimum shares, maximum shares, and count of negative shares. Keep missing shares as missing rather than replacing them with zero.

14. Print a warning if the dataset’s shape is not exactly 298,772 rows and 9 columns.

15. Create the `hw02/charts/` folder if necessary and save these three clearly labeled charts:

* `hist_amount.png`: A histogram of amount with labeled vertical lines marking the mean and median.
* `box_amount_by_type.png`: A horizontal box plot of amount by transaction type.
* `scatter_shares_amount.png`: A scatter plot with shares on the x-axis and amount on the y-axis, colored by transaction type, with a legend.

16. Save a plain-text copy of all results from items 2–13 to `hw02/hw02_profile.txt`. Include clear section labels and show the results in the terminal as well.

17. Include a comment block at the top identifying the script, the dataset, the author Santos Gunningham, and the actual generation date.

Use pandas for analysis and matplotlib or seaborn for charts. Keep the code readable, with comments explaining each major section. Calculate all results from the CSV rather than hard-coding expected answers. Keep unusual values, including negative shares, in the analysis.
