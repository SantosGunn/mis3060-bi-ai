# HW1: Prompt Engineering Comparison

## Analytical Question

What should a BI dashboard for a loan portfolio committee include, and why?

## Setup

I used a separate conversation in the Wildcat Cowork project for each strategy, starting with zero-shot. The project already had instructions and access to the Wildcat folder, so zero-shot means no additional context in the prompt itself. All three responses referred to the project data.

The excerpts below contain the first 150 whitespace-separated words, including headings and list numbers. Formatting has been simplified. Evaluations consider the full responses.

## Strategy 1: Zero-Shot

### Exact Prompt

What should a BI dashboard for a loan portfolio committee include, and why?

### First 150 Words of Claude's Response

> Pulled up your Wildcat data to ground this. You've got 2,340 loans, originated 2015-2025, 27 states, with status (Current / Paid Off / Delinquent / Default), amount, rate, term, credit score, DTI, purpose, income, and state.
>
> Start from what the committee decides
>
> A loan portfolio committee isn't browsing. They meet to make a handful of recurring calls: are we taking on more risk than we planned, is anything concentrating, is credit deteriorating, and should we change who we lend to or how we price it. Every tile on the dashboard should map to one of those. If a chart doesn't change a decision, cut it.
>
> The five layers
>
> 1. Portfolio snapshot. Total outstanding balance, loan count, average loan size, weighted average rate, weighted average term. This is the "how big is the book" orientation row. Weighted average, not simple average, because a $200K loan and a $5K loan shouldn't count

### Evaluation

This gave a useful starting point even though the prompt was short. Claude explained the main dashboard sections and connected them to committee decisions. It also listed missing information, such as current balances and payment history. However, it was too confident about building same-age vintage curves from the available data. The answer was already specific to Wildcat because Claude used the project context, so this was not a context-free response.

## Strategy 2: Role-Assigned

### Exact Prompt

You are a senior business intelligence analyst presenting to a loan portfolio committee of three senior executives who do not have technical analytics backgrounds. What should a BI dashboard for a loan portfolio committee include, and why?

### First 150 Words of Claude's Response

> Poked around the folder first. The only data file is `02_Data/Raw/wildcat_loans_clean.csv`, 2,340 loans, 12 columns, originations from Apr 2015 to Dec 2025. That shapes what's actually buildable, so I'll answer the general question and then say what Wildcat's data does and doesn't support.
>
> The governing principle
>
> Three non-technical execs on a portfolio committee are there to make decisions: tighten or loosen credit, reprice, shift where the sales team hunts, decide if a problem is real or noise. So every element on the dashboard should answer "what do we do differently on Monday?" If a chart can't lose an argument, it's decoration.
>
> Practical version: one screen, four to six KPIs at the top, three to four supporting visuals, no scrolling for the main story.
>
> What it should include
>
> 1. Portfolio health headline (the top strip)
>
> Total outstanding balance, loan count, weighted average interest rate, and a delinquency/default rate. Each with a

### Evaluation

The role and audience made the response more focused on what executives would actually use. Claude recommended a small number of KPIs, plain-English chart titles, and keeping detailed tables off the main screen. It explained decisions the dashboard could support instead of only listing metrics. Some wording was still too dramatic or technical for the audience, and it repeated the unsupported claim about vintage curves. Assigning a professional role improved the presentation but did not guarantee accuracy.

## Strategy 3: Few-Shot

### Exact Prompt

Here is an example of the output format I want, using a different business topic:

Dashboard element: Weekly sales
What it shows: Total sales compared with the previous week.
Why it matters: Helps managers see whether sales are improving.
Decision it supports: Whether to adjust promotions or staffing.

Using that same format, answer: What should a BI dashboard for a loan portfolio committee include, and why?

### First 150 Words of Claude's Response

> Here's what a loan portfolio committee dashboard should cover. I checked the Wildcat data file first (`02_Data/Raw/wildcat_loans_clean.csv`, 2,340 loans, originations 2015-04 to 2025-12) so I could flag which of these you can actually build from what you have.
>
> Buildable from the current file
>
> Dashboard element: Portfolio size and outstanding balance
> What it shows: Total loan dollars and loan count, trended by origination month.
> Why it matters: Tells the committee whether the book is growing, flat, or shrinking.
> Decision it supports: Whether to push origination volume or pull back.
>
> Dashboard element: Loan status mix
> What it shows: Share of loans in each status (Current, Paid Off, Delinquent, Default), by count and by dollars.
> Why it matters: This is the headline health measure of the book.
> Decision it supports: Whether to tighten underwriting or add collections staff.
>
> Dashboard element: Delinquency and default rate trend
> What it shows: Delinquent plus Default as a

### Evaluation

This response was the easiest to scan because each dashboard element followed the same four-part structure. The example helped Claude consistently connect a metric to a business decision. However, the organized format made some questionable recommendations look more reliable than they were. It placed outstanding balance, historical delinquency trends, and same-age vintage curves under things that were buildable, despite later acknowledging missing data. The example controlled the format better than it controlled factual accuracy.

## Conclusion

The role-assigned response was the most useful for understanding how a BI analyst should present information to executives. It gave clearer advice about what to prioritize and what to leave off the main dashboard. The few-shot response was the easiest to turn into an outline, while zero-shot gave a useful general starting point. All three still needed verification, so a more detailed prompt did not automatically produce a more accurate answer. This was a small comparison within one project, so the results do not prove that one strategy is always better.

## Fact-Check

### Check 1: Default Percentage

Claim from the zero-shot response: 106 defaults out of 2,340 loans is 4.5% by count.

Method: Independently recalculate the percentage using the numbers in Claude's response.

Calculation: 106 / 2,340 × 100 = 4.5299%.

Result: The arithmetic is correct when rounded to one decimal place. This verifies the calculation only, not whether the CSV actually contains 106 defaulted loans. The underlying count and definition of Default still need verification.

### Check 2: Geographic Concentration

Claim from the role-assigned response: PA has 384 loans, NJ has 272, and NY has 264, together representing roughly 39% of 2,340 loans.

Method: Add the three stated counts and divide by the stated total.

Calculation: (384 + 272 + 264) / 2,340 × 100 = 39.3162%.

Result: Roughly 39% is arithmetically correct using Claude's stated counts. This is a percentage of loan count, not current outstanding balance. The individual state counts have not been independently checked against the CSV.

### Check 3: Same-Age Vintage Curves

Claim: The available data supports default curves comparing loans at the same age.

Method: Compare the recommendation with the fields and limitations described in the full responses.

Result: The claim is not supported by the information Claude provided. An origination date and a single current status do not reveal when a loan defaulted. Comparing defaults within the first 12 or 24 months would require default timing or suitable historical performance records. Current status can be grouped by origination year, but that is not the same as comparing performance at an equal loan age.

### Check 4: Outstanding Balance

Claim from the few-shot response: Portfolio size and outstanding balance are buildable from the current file.

Method: Compare this recommendation with the response's own missing-data section.

Result: The response contradicts itself. It later says that loan_amount is the original amount and that remaining principal is unavailable. Original loan dollars should be labeled as origination volume, not current outstanding balance. An estimated balance would require additional assumptions and would not be an observed balance.

### Verification Limits

These checks use independent arithmetic and comparisons within the supplied responses. They are not an independent audit of the CSV or a review of external lending sources. Claude's reported counts, column meanings, and statements about Wildcat policy should not be treated as fully verified.
