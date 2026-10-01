# HW03 Pipeline Specifications

## Specification A: Earnings Pipeline

Create a Python script named `hw03/hw03_earnings.py` that collects quarterly earnings information from SEC EDGAR for these five companies. Use these CIK values exactly and preserve their leading zeros:

- Apple Inc. | AAPL | 0000320193
- Microsoft Corporation | MSFT | 0000789019
- NVIDIA Corporation | NVDA | 0001045810
- JPMorgan Chase & Co. | JPM | 0000019617
- Walmart Inc. | WMT | 0000104169

Use `requests` for downloads and `beautifulsoup4` to convert HTML into plain text. Set the User-Agent header to `"MIS3060 Villanova sgunning@villanova.edu"` on every HTTP request.

For each company, query `https://data.sec.gov/submissions/CIK{cik}.json`. Filter for Form 8-K filings whose `items` field contains `"2.02"`. Select the four most recent quarterly earnings filings, using one filing per quarter.

For each selected filing, construct its filing index URL and identify the earnings press release exhibit in `.htm` format. Download that exhibit and strip the HTML while preserving readable spacing. If the exhibit cannot be found or downloaded, print a warning and continue without crashing.

Use regular expressions or other text pattern matching to extract:

- Reporting period, such as “fourth quarter fiscal 2024”
- Quarterly revenue
- Diluted earnings per share
- Quarterly net income

Extract the current reporting quarter’s figures, not prior-year comparison figures or full-year totals. Prefer GAAP diluted EPS and net income rather than adjusted figures. Make the units clear and consistent by saving revenue and net income in millions of US dollars and EPS in dollars per share.

If a field cannot be extracted, store the literal string `"NOT_FOUND"` instead of a blank cell or `None`. Do not guess missing values.

Print each processed row in this format:
`[Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X`

Indicate that revenue and net income are in millions.

Save the results to `hw03/earnings_history.csv` with these columns in this order:
`company`, `ticker`, `cik`, `filing_date`, `period`, `revenue_reported`, `eps_diluted`, `net_income`

Use request timeouts and a short delay between SEC requests. Handle download and parsing failures with clear warnings so one failed filing does not stop the entire script. Print the number of rows saved and the output file path when finished.

## Specification B: Executive Events Pipeline

Create a Python script named `hw03/hw03_executives.py` that collects executive and director departures and appointments from SEC EDGAR for these five companies. Use these CIK values exactly and preserve their leading zeros:

- Apple Inc. | AAPL | 0000320193
- Microsoft Corporation | MSFT | 0000789019
- NVIDIA Corporation | NVDA | 0001045810
- JPMorgan Chase & Co. | JPM | 0000019617
- Walmart Inc. | WMT | 0000104169

Use `requests` for downloads and `beautifulsoup4` to convert HTML into plain text. Set the User-Agent header to `"MIS3060 Villanova sgunning@villanova.edu"` on every HTTP request.

For each company, query `https://data.sec.gov/submissions/CIK{cik}.json`. Filter for Form 8-K filings whose `items` field contains `"5.02"` and whose `filingDate` falls within the past 12 months, calculated from the date the script runs. If the recent filings list does not cover the full time window, retrieve the additional submissions files referenced by the API as needed.

Download the full primary 8-K document for each matching filing and strip its HTML while preserving readable spacing. Focus extraction on the Item 5.02 section to avoid confusing unrelated names or dates with executive events.

For each departure or appointment, extract:

- Event type: `"departure"`, `"appointment"`, or `"both"`
- Person’s full name
- Title associated with the event
- Effective date of the change

Create a separate row for each distinct event. A filing announcing one person’s departure and another person’s appointment must produce two rows. Use `"both"` only when appropriate for a single person’s combined change, without merging different people into one row.

Do not assume every Item 5.02 filing contains a departure or appointment. If it only discusses compensation or another matter, print an explanatory message and do not invent an event. If a genuine event is identified but a field cannot be extracted, store `"NOT_FOUND"`. Do not substitute the filing date for an unknown effective date.

Print each extracted event in this format:
`[Ticker] | [Date] | [Event Type] | [Name] | [Title]`

Use the filing date for the printed date.

If a company has no matching Item 5.02 filings in the time window, print:
`[Ticker]: No executive events in past 12 months`

Do not report “no executive events” when the search failed because of a download error. Print a warning explaining the failure instead.

Save all events to `hw03/executive_events.csv` with these columns in this order:
`company`, `ticker`, `cik`, `filing_date`, `event_type`, `person_name`, `title`, `effective_date`

Use YYYY-MM-DD for dates when they can be determined. Create the CSV with column headers even if there are zero event rows.

Use request timeouts and a short delay between SEC requests. Handle download and parsing failures with clear warnings so one failed filing does not stop the entire script. Print the number of rows saved and the output file path when finished.