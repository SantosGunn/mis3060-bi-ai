# HW1: Business Context

## Question 1: Loan Statuses

### Exact Prompt

Wildcat Capital labels loans as Current, Paid Off, Delinquent, or Default. What does each status mean for a consumer lender, and how should a portfolio committee respond differently to delinquent loans versus defaulted loans? Explain the business meaning without calculating anything from the CSV, and identify any definitions we should confirm with Wildcat.

### Summary of Claude's Response

Claude explained that Current generally means payments are up to date, while Paid Off means the loan has been repaid. It described delinquency as missed payments and default as a more serious stage, although Wildcat's exact definitions are not documented. For delinquent loans, the committee should focus on helping accounts return to regular payments, while defaulted loans require more attention to recovery and possible losses. Claude also recommended confirming the status thresholds, the date of the data, and whether loans can change back to another status.

### Follow-Up Question

What triggers Wildcat to change a loan from Delinquent to Default?

## Question 2: Borrower Risk Attributes

### Exact Prompt

Wildcat Capital records borrowers’ credit scores, debt-to-income ratios, and annual incomes. How should a consumer lender consider these three attributes together when assessing credit risk, and what could be misleading about relying on just one? Explain the business implications without calculating anything from the CSV.

### Summary of Claude's Response

Claude explained that credit score reflects past credit behavior, DTI shows debt payments relative to income, and annual income adds context about the borrower's financial capacity. A borrower could look strong on one measure but still have problems shown by the others. Looking at all three can help a lender consider approval, pricing, and loan size, but the response did not establish which measure predicts default best for Wildcat. Claude also noted that we need to confirm how DTI is calculated, whether income is verified, and when the attributes were recorded.

### Follow-Up Question

Does Wildcat's DTI include the proposed loan payment, and is the income verified?

## Question 3: Loan Purpose

### Exact Prompt

Wildcat Capital has five loan purposes: Auto, Personal, Home Improvement, Education, and Business. Why should a portfolio committee monitor credit risk separately for each purpose instead of relying only on an overall default rate? Explain the business implications without calculating anything from the CSV, and do not assume a loan is secured just because of its purpose.

### Summary of Claude's Response

Claude explained that the overall default rate can hide problems in individual loan purposes. The overall rate can also change because the mix of loans changes, even when the performance within a category tells a different story. Reviewing each purpose helps the committee identify where it may need to adjust pricing, underwriting, or exposure limits. Claude also pointed out that loan age affects comparisons and that purpose alone does not establish whether a loan has collateral or how much could be recovered after default.

### Follow-Up Question

How can Wildcat distinguish a change in loan-purpose mix from an actual change in credit performance?

## Question 4: Default Rate Definitions

### Exact Prompt

Wildcat Capital classifies loans as Current, Paid Off, Delinquent, or Default. How could including or excluding Paid Off loans change the meaning of a reported default rate, and what should a BI analyst explain to the portfolio committee about the denominator and reporting period? Discuss this conceptually without calculating anything from the CSV.

### Summary of Claude's Response

Claude explained that including or excluding Paid Off loans changes the denominator and therefore the meaning of a default rate. Including repaid loans gives a broader view of recorded loan outcomes, while a measure focused on loans still held requires a clear definition of which accounts remain in the portfolio. The response distinguished a snapshot of statuses from defaults occurring during a period and defaults observed within a fixed time after origination. It recommended stating the numerator, denominator, reporting date, observation window, and whether the measure uses loan counts or dollars. These interpretations still depend on confirming how Wildcat records defaults, recoveries, and closed loans.

### Follow-Up Question

Does Wildcat keep charged-off loans in the file, and can a previously defaulted loan later appear as Paid Off?

## Question 5: Data Limitations

### Exact Prompt

Wildcat Capital records credit score, debt-to-income ratio, annual income, loan purpose, and loan status. Before a portfolio committee uses these fields to change lending policies, what definitions and data limitations should a junior BI analyst clarify, and how should the analyst explain uncertainty to non-technical executives? Keep this conceptual and do not calculate anything from the CSV.

### Summary of Claude's Response

Claude recommended confirming the meaning, source, and recording date of each field before using it to change lending policies. It highlighted possible limitations such as missing payment history, older borrower information, small groups, and differences in how long loans have been outstanding. It also explained that records of approved loans do not directly show how rejected applicants would have performed. For executives, Claude suggested separating what the data supports from assumptions and unanswered questions, then explaining what additional information would help. The numerical range in its communication example was illustrative and was not a finding about Wildcat.

### Follow-Up Question

Who at Wildcat can confirm the field definitions and provide a dated data dictionary?
