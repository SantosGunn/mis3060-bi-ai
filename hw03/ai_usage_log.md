# HW03 AI Usage Log

Date: September 30, 2026

## Tools and responsibilities

I used Claude Cowork to generate the three Python scripts, create diagnostic and validation scripts, and revise the extraction logic. I ran the SEC pipelines, diagnostic scripts, timeline script, and Yahoo Finance validation in my local VS Code terminal. ChatGPT helped draft the specifications, guide the workflow, review code and output, formulate troubleshooting prompts, check public sources, and draft analysis.md, validation.md, and this usage log. I saved both specifications before asking Claude to generate the pipeline code.

Claude reported compilation checks and synthetic extraction tests before the first live runs. Later, it reported testing executive-script revisions against the locally downloaded filing sections. Those were Claude's reported tests, separate from the local runs whose output I reviewed and shared. Claude's SEC downloads were blocked, so the real downloads were performed through my local terminal.

## Main prompt 1: Earnings pipeline

I supplied the complete Specification A from specifications.md in the earnings conversation, including the five companies and exact CIKs, the Villanova email User-Agent, Item 2.02 filtering, four quarters per company, press-release discovery, plain-text extraction, required CSV columns, units, NOT_FOUND handling, and warnings. The complete specification is preserved in the submitted specifications.md under “Specification A: Earnings Pipeline.”

I appended this instruction:

> Save the script as hw03/hw03_earnings.py in my project folder. Do not run it yet. First show me the code so I can review it.

## Main prompt 2: Executive-events pipeline

In a new Claude Cowork conversation, I supplied the complete Specification B from specifications.md. It specified the same companies and User-Agent, Item 5.02 filings within the past 12 months, retrieval of older submissions files when needed, event types, names, titles, effective dates, separate events, no-event handling, and the required CSV columns. The complete specification is preserved in the submitted specifications.md under “Specification B: Executive Events Pipeline.”

I appended this instruction:

> Save the script as hw03/hw03_executives.py. Do not run it yet. Make sure a company with zero matching filings is handled without crashing, and a filing announcing a departure and an appointment produces separate event rows. Show me the code for review.

## Main prompt 3: Corporate-events timeline

In a new Claude Cowork conversation, I used this prompt:

> Write hw03/hw03_timeline.py to read hw03/earnings_history.csv and hw03/executive_events.csv.
>
> 1. For each executive-event row, find the nearest earnings filing_date for the same company. Use filing dates, not effective dates. Match by ticker and preserve CIKs as strings with leading zeros.
>
> 2. Calculate days_to_nearest_earnings as executive filing_date minus earnings filing_date. Negative means before earnings; positive means after.
>
> 3. Set event_timing to:
> - "same week" when the absolute difference is 7 days or less, including zero.
> - "before earnings" when the difference is less than -7.
> - "after earnings" when the difference is greater than 7.
>
> 4. Save hw03/corporate_events_timeline.csv with all information from both source tables plus days_to_nearest_earnings and event_timing. Clearly distinguish executive_filing_date from earnings_filing_date. Keep one output row per executive-event row, including separate role appointments for the same person.
>
> 5. Print each company's events, the matched earnings filing date, the day difference, and timing category. Print totals for before earnings, after earnings, and same week across all five companies.
>
> 6. If two earnings filings are equally close, choose the earlier one and document that rule. If no earnings match exists, retain the event, use NOT_FOUND for unavailable match fields, and print a warning. Handle an empty executive-events CSV without crashing.
>
> Use paths relative to the script's location. Do not change the source CSVs. Save the script without running it, and summarize how it works.

## Iterations and troubleshooting

### Earnings pipeline

Before the first run, code review identified a 60-day heuristic for grouping quarters, an assumption that the first table value always represented the current quarter, possible confusion between diluted share counts and diluted EPS, and all-NOT_FOUND rows created when no release was retrieved. I sent a follow-up prompt asking Claude to use actual reporting periods, preserve readable text structure, identify the correct quarter column, skip unavailable releases with warnings, and tighten GAAP and diluted-EPS checks. The prompt also asked it to distinguish JPMorgan's reported revenue from managed revenue.

The first real run saved 17 rows. Apple, Microsoft, NVIDIA, and JPMorgan each produced four rows. Walmart produced only one row, with all three financial fields marked NOT_FOUND, while several releases were skipped because the period could not be identified.

I ran a diagnostic script locally and shared the actual Walmart release text. In a new Claude conversation, the troubleshooting prompt began:

> What regex pattern would reliably extract the quarterly revenue figure from this text?

The rest of the prompt asked for a targeted fix using the attached release: consolidated quarterly revenue rather than segment or guidance figures, reporting-period identification from results headings, and GAAP diluted EPS and net income from the consolidated statements. It requested source excerpts and proposed patterns without hard-coded financial values.

The diagnostic showed that Walmart's headline and highlights were inside table blocks excluded from the original period and narrative searches. Its column headings also split the month/day and year across separate rows. Claude added a reporting-period fallback using results-table labels, corrected the date-heading alignment, and added a scoped highlights revenue fallback. I chose exact consolidated-statement revenue as the primary value rather than the rounded highlights figure.

The next run saved 20 rows with no NOT_FOUND financial fields. The other four companies' printed results stayed unchanged. Walmart was the company that required company-specific troubleshooting after the live earnings run; the JPMorgan distinction was addressed during the earlier code review.

### Executive-events pipeline

The first real run saved 29 rows. Review identified a likely duplicate, Suzanne Nora Johnson and Nora Johnson, missing or incomplete titles, questionable “both” classifications, and dates that appeared to be board-action dates rather than role-effective dates.

Claude created a diagnostic script, which I ran locally to save Item 5.02 source sections. There was initially a filename mismatch: Claude had saved debug_502_sections.py, while the command used debug_executive_filings.py. Claude saved the requested filename, and I reran the diagnostic successfully.

Using the saved filing text, Claude proposed and implemented parsing changes for Apple, NVIDIA, JPMorgan, and Walmart. These covered compound surnames and shorter name references, lowercase titles, business-unit names, defined dates such as “Transition Date,” conditional effective dates, and separate role appointments. The Microsoft rows were unchanged in the reported before-and-after review.

Specific decisions included keeping Kathryn McLay's April 30, 2026 company departure separate from her January 31 role-end date; leaving Nicholas Parker's effective date as NOT_FOUND because his August 24 start was only anticipated; and keeping Jennifer Newstead's January senior vice president appointment separate from her March 1 general counsel appointment. The January appointment retained NOT_FOUND because no exact day was stated. John Furner's CEO appointment and board election also remained separate events.

The revised live run saved 33 rows. It removed the Nora Johnson duplicate, corrected several dates and classifications, improved titles, and added distinct appointments that had previously been merged. Remaining REVIEW messages described source uncertainty rather than being silently replaced with guessed dates.

### Timeline and validation

The timeline script ran successfully and saved 33 rows: 23 before earnings, 7 after earnings, and 3 within seven days. ChatGPT independently recalculated the recorded day differences and timing categories in the uploaded timeline and found that all matched. The count is by event row, not independent announcement; multiple roles or people from the same filing can contribute multiple rows.

For external validation, ChatGPT checked Walmart's official earnings release and the public announcement of John Furner's CEO appointment. I also used Claude to generate validate_yfinance.py and ran it locally. It selected the quarter ended July 31, 2026 explicitly. Yahoo's Total Revenue of $187,937,000,000 and Net Income of $6,366,000,000 matched the extraction after conversion to millions. These checks are documented in validation.md; they do not verify every extracted row.

## One generated behavior I had not specified initially

Claude initially treated Item 2.02 filings less than 60 days apart as the same reporting quarter. I had asked for one filing per quarter but had not specified that method. The shortcut needed adjustment because filing-date spacing alone does not establish the reporting period. After review, I asked Claude to identify distinct quarters from the releases' actual reporting periods instead.
