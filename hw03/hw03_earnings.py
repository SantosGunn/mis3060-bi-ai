"""
=============================================================================
Script:     hw03_earnings.py
Purpose:    Collect the four most recent quarterly earnings releases
            (Form 8-K, Item 2.02) for five companies from SEC EDGAR and
            extract the reporting period, revenue, diluted EPS, and net income.
Author:     Santos Gunningham
Generated:  2026-09-30 (revised)

Run from the repository's main folder:
    python hw03/hw03_earnings.py

Output:
    hw03/earnings_history.csv

Units:
    revenue_reported and net_income  -> millions of US dollars
    eps_diluted                      -> US dollars per share (GAAP, diluted)
    Any field that cannot be extracted is saved as the string NOT_FOUND.

How it works:
    1. Filings: every Form 8-K whose items include 2.02 is a candidate.
       Candidates are processed newest first. The reporting period is read
       from each press release, and filings are kept until four DISTINCT
       reporting quarters are collected (or candidates run out). A release
       whose period cannot be identified is skipped with a warning.
       The period comes from the prose headline / lead paragraph; if none
       is found there, from the results headline ("reports second quarter
       results") plus results-table column headings ("Q2 FY27 | Q2 FY26"),
       ignoring guidance/outlook tables.
    2. Plain text: the EX-99 press release is converted to plain text.
       Paragraphs become lines. Tables are kept as blocks between
       [TABLE] and [/TABLE] lines, one table row per line, with cells
       separated by " | ".
    3. Tables: the column headings of each table ("Three Months Ended",
       "September 28, 2024", "3Q24", "Q3 FY25", ...) are read to find the
       ONE column that is the release's own quarter. If no column, or more
       than one column, matches, the table is not used. Row labels are
       matched with regular expressions ("Total net sales", "Diluted
       earnings per share", ...). A row only counts if its number of values
       lines up with the number of heading columns. A month/day heading on
       its own row ("Three Months Ended / July 31, / 2026 | 2025") is
       attached to its column group.
    4. Revenue: the income statement is the primary source. A "<Nth>
       Quarter Highlights" bullet such as "Revenue of $187.9 billion" is a
       reasonableness check (a mismatch beyond rounding -> NOT_FOUND) and
       the fallback when the statement value is missing.
       Narrative fallback: if no table gives a value, lead-paragraph
       sentences such as "quarterly revenue of $94.9 billion" are used, as
       long as the sentence does not refer to a different period, guidance,
       full-year, adjusted, or non-GAAP figures.
    5. Exclusions apply to all three metrics: adjusted / non-GAAP / full-year
       figures are never used. When a release reports both "managed" and
       "reported" revenue (JPMorgan), only figures explicitly labeled
       "reported" are accepted for revenue_reported.
    6. Anything missing or ambiguous is NOT_FOUND. Nothing is guessed.
=============================================================================
"""

import csv
import re
import time
from collections import deque
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Comment, NavigableString

# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
COMPANIES = [
    # (company name, ticker, CIK with leading zeros)
    ("Apple Inc.", "AAPL", "0000320193"),
    ("Microsoft Corporation", "MSFT", "0000789019"),
    ("NVIDIA Corporation", "NVDA", "0001045810"),
    ("JPMorgan Chase & Co.", "JPM", "0000019617"),
    ("Walmart Inc.", "WMT", "0000104169"),
]

HEADERS = {"User-Agent": "MIS3060 Villanova sgunning@villanova.edu"}
REQUEST_TIMEOUT = 30          # seconds
REQUEST_DELAY = 0.25          # seconds between SEC requests (SEC limit is 10/sec)

QUARTERS_WANTED = 4
MAX_REPORT_LAG_DAYS = 120     # a quarter-end date must fall 0-120 days before the filing
PERIOD_SEARCH_CHARS = 3000    # where the release's own period is looked for
HEADLINE_CHARS = 400          # two different periods here = ambiguous
LEAD_CHARS = 6000             # narrative fallback only searches the lead text

NOT_FOUND = "NOT_FOUND"
SEC_BASE = "https://www.sec.gov"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

OUT_PATH = Path(__file__).resolve().parent / "earnings_history.csv"
COLUMNS = [
    "company", "ticker", "cik", "filing_date", "period",
    "revenue_reported", "eps_diluted", "net_income",
]


# -----------------------------------------------------------------------------
# HTTP helper
# -----------------------------------------------------------------------------
def sec_get(url):
    """GET a URL with the required User-Agent, a timeout, and a short delay.
    Returns the response, or None (with a warning) if the request fails."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"  WARNING: request failed for {url} ({exc})")
        return None
    finally:
        time.sleep(REQUEST_DELAY)


# -----------------------------------------------------------------------------
# Step 1: candidate filings and the press release exhibit
# -----------------------------------------------------------------------------
def earnings_candidates(submissions):
    """All Form 8-K filings whose items include 2.02, newest first."""
    recent = submissions.get("filings", {}).get("recent", {})
    candidates = []
    for form, items, acc, fdate in zip(
        recent.get("form", []),
        recent.get("items", []),
        recent.get("accessionNumber", []),
        recent.get("filingDate", []),
    ):
        if form != "8-K":
            continue
        if "2.02" not in [i.strip() for i in (items or "").split(",")]:
            continue
        candidates.append({"accession": acc, "filing_date": fdate})
    candidates.sort(key=lambda f: f["filing_date"], reverse=True)
    return candidates


def find_press_release(cik, accession):
    """Read the filing index page and return the URL of the EX-99 .htm
    exhibit that looks most like the earnings press release (or None)."""
    acc_nodash = accession.replace("-", "")
    index_url = (f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/"
                 f"{acc_nodash}/{accession}-index.htm")
    resp = sec_get(index_url)
    if resp is None:
        return None

    soup = BeautifulSoup(resp.content, "html.parser")
    best_url, best_score = None, None
    # Index table columns: Seq | Description | Document | Type | Size
    for tr in soup.select("table.tableFile tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        description = cells[1].get_text(" ", strip=True).lower()
        link = cells[2].find("a")
        doc_type = cells[3].get_text(" ", strip=True).upper()
        if link is None or not link.get("href"):
            continue
        href = link["href"].replace("/ix?doc=", "")
        if not doc_type.startswith("EX-99"):
            continue
        if not href.lower().endswith((".htm", ".html")):
            continue

        score = 0
        if any(w in description for w in
               ("press release", "earnings release", "news release", "results")):
            score += 10
        if any(w in description for w in
               ("supplement", "presentation", "slides", "transcript")):
            score -= 8
        if doc_type in ("EX-99.1", "EX-99.01", "EX-99"):
            score += 5
        if best_score is None or score > best_score:
            best_url, best_score = urljoin(SEC_BASE, href), score

    if best_url is None:
        print(f"  WARNING: no EX-99 .htm press release found in {index_url}")
    return best_url


# -----------------------------------------------------------------------------
# Step 2: HTML -> plain text (tables kept as rows and " | " columns)
# -----------------------------------------------------------------------------
BLOCK_TAGS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]
DASHES = "‐‑‒–—―−"
TABLE_START, TABLE_END = "[TABLE]", "[/TABLE]"


def clean_whitespace(text):
    text = text.replace("\xa0", " ").replace("​", "")
    for d in DASHES:
        text = text.replace(d, "-")
    return re.sub(r"\s+", " ", text).strip()


def merge_cells(cells):
    """Glue '$' / '(' onto the next cell and ')' / '%' onto the previous one,
    so each table value ends up in exactly one cell. Empty cells are dropped."""
    out, pending = [], ""
    for cell in cells:
        if not cell:
            continue
        if cell in ("$", "(", "$(", "($"):
            pending += cell
            continue
        if out and re.fullmatch(r"[)%]+", cell):
            out[-1] += cell
            continue
        out.append(pending + cell)
        pending = ""
    return out


def html_to_text(html):
    """Plain text with readable spacing. Each table becomes:
        [TABLE]
        label | value | value ...
        [/TABLE]"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    # Line breaks inside the HTML source are not real line breaks.
    for piece in list(soup.find_all(string=True)):
        if type(piece) is not NavigableString:
            continue  # leave doctype / CDATA alone
        if "\n" in piece or "\r" in piece:
            piece.replace_with(re.sub(r"[\r\n]+", " ", str(piece)))

    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue  # nested tables are flattened into their outer table
        lines = []
        for tr in table.find_all("tr"):
            raw = [clean_whitespace(td.get_text(" ")).replace("|", "/")
                   for td in tr.find_all(["td", "th"], recursive=False)]
            cells = merge_cells(raw)
            if cells:
                lines.append(" | ".join(cells))
        block = "\n" + TABLE_START + "\n" + "\n".join(lines) + "\n" + TABLE_END + "\n"
        table.replace_with(NavigableString(block))

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(BLOCK_TAGS):
        block.append("\n")

    text = soup.get_text().replace("\xa0", " ").replace("​", "")
    for d in DASHES:
        text = text.replace(d, "-")

    lines, previous_blank = [], False
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
            previous_blank = False
        elif not previous_blank:
            lines.append("")
            previous_blank = True
    return "\n".join(lines).strip()


def split_blocks(text):
    """Separate the plain text into prose and table blocks. Each table keeps
    up to 3 short lines of prose right before it (titles / unit notes)."""
    prose, tables = [], []
    recent = deque(maxlen=3)
    in_table, rows, context = False, [], []
    for line in text.splitlines():
        if line == TABLE_START:
            in_table, rows = True, []
            context = [c for c in recent if len(c) <= 150]
            continue
        if line == TABLE_END:
            if rows:
                tables.append({"rows": rows, "context": context})
            in_table = False
            recent.clear()
            continue
        if in_table:
            if line:
                rows.append([c.strip() for c in line.split(" | ")])
        else:
            prose.append(line)
            if line:
                recent.append(line)
    return "\n".join(prose), tables


def flat(text):
    return re.sub(r"\s+", " ", text).strip()


# -----------------------------------------------------------------------------
# Step 3: the release's own reporting period
# -----------------------------------------------------------------------------
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth"}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}


def full_year(text):
    return int(text) if len(text) == 4 else 2000 + int(text[-2:])


def month_number(name):
    name = name.lower().rstrip(".")
    if name[:4] in MONTHS:
        return MONTHS[name[:4]]
    return MONTHS.get(name[:3])


def make_date(month_name, day, year):
    month = month_number(month_name)
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


# Each pattern -> (quarter, year, fiscal?)
PERIOD_PATTERNS = [
    # "third quarter fiscal 2025", "first quarter of fiscal year 2025", "third quarter FY25"
    (re.compile(r"\b(first|second|third|fourth)[ -]quarter(?: of)?(?: the)? "
                r"(?:fiscal(?: year)?|fy)\s*'?(\d{4}|\d{2})\b", re.I),
     lambda m: (QUARTER_WORDS[m.group(1).lower()], full_year(m.group(2)), True)),
    # "fiscal 2024 fourth quarter"
    (re.compile(r"\bfiscal(?: year)? (\d{4}) (first|second|third|fourth)[ -]quarter", re.I),
     lambda m: (QUARTER_WORDS[m.group(2).lower()], int(m.group(1)), True)),
    # "Q3 FY25", "Q3 fiscal 2025"
    (re.compile(r"\bQ([1-4])\s*(?:FY|fiscal(?: year)?)\s*'?(\d{2,4})\b", re.I),
     lambda m: (int(m.group(1)), full_year(m.group(2)), True)),
    # "FY25 Q3"
    (re.compile(r"\bFY\s*'?(\d{2,4})\s*Q([1-4])\b", re.I),
     lambda m: (int(m.group(2)), full_year(m.group(1)), True)),
    # "third-quarter 2024", "third quarter of 2024" (calendar year, e.g. JPM)
    (re.compile(r"\b(first|second|third|fourth)[ -]quarter(?: of)? ((?:19|20)\d{2})\b", re.I),
     lambda m: (QUARTER_WORDS[m.group(1).lower()], int(m.group(2)), False)),
    # "3Q24"
    (re.compile(r"\b([1-4])Q\s?'?(\d{2})\b"),
     lambda m: (int(m.group(1)), full_year(m.group(2)), False)),
]

END_DATE_RE = re.compile(
    r"\b(?:quarter|three months|thirteen weeks|13 weeks)(?: ended| ending)\s+(?:on )?"
    r"([A-Z][a-z]{2,8})\.? (\d{1,2}), ((?:19|20)\d{2})")


def find_periods(text):
    """All quarter/year mentions in text: list of (start, (q, y, fiscal))."""
    hits = []
    for order, (pattern, build) in enumerate(PERIOD_PATTERNS):
        for m in pattern.finditer(text):
            hits.append((m.start(), order, build(m)))
    hits.sort()
    return [(start, info) for start, _, info in hits]


def find_end_dates(text):
    return [d for d in (make_date(*m.groups()) for m in END_DATE_RE.finditer(text)) if d]


def within_lag(end, filing_date):
    return 0 <= (filing_date - end).days <= MAX_REPORT_LAG_DAYS


def identify_release(prose, filing_date, text=None, raw_tables=None):
    """Return (release, None) or (None, reason).
    release = {q, y, fiscal, end, display, key}

    1. Prose headline / lead paragraph (works for AAPL, MSFT, NVDA, JPM).
    2. Fallback when step 1 finds nothing: results-section headline plus
       results-table column headings (e.g. Walmart, whose headline and
       highlights sit inside table blocks). See results_table_period()."""
    release, reason = _prose_period(prose, filing_date)
    if release is not None or text is None:
        return release, reason

    period, why = results_table_period(text, raw_tables or [])
    if period is None:
        return None, f"{reason}; results-table fallback: {why}"
    q, y = period
    return {"q": q, "y": y, "fiscal": True, "end": None,
            "display": f"{ORDINALS[q]} quarter fiscal {y}",
            "key": ("q", q, y, True)}, None


# Results-section headline, e.g. "Walmart reports second quarter results"
RESULTS_HEADLINE_RE = re.compile(
    r"\b(?:reports?|announces?) (first|second|third|fourth)[ -]quarter"
    r"(?: (?:of )?fiscal(?: year)? (\d{4}))? results\b", re.I)
# A results-table column heading such as "Q2 FY27"
COLUMN_CODE_RE = re.compile(r"^Q([1-4])\s*FY\s*'?(\d{2}|\d{4})$", re.I)
# Guidance / outlook tables never define the current period
GUIDANCE_TABLE_RE = re.compile(r"guidance|outlook|expects?|expected|forecast|"
                               r"consolidated metric", re.I)


def results_table_period(text, raw_tables):
    """(quarter, fiscal year) from the results sections, or (None, reason).

    - Quarter: the results headline near the top ("reports second quarter
      results"), searched in the full text so table blocks are included.
    - Fiscal year: if the headline has none, results tables whose FIRST
      heading column is a quarter code for that same quarter ("Q2 FY27 |
      Q2 FY26 | Change"). The first column is the current period; the
      second is the prior-year comparison. Guidance/outlook tables are
      skipped. All qualifying tables must agree on one fiscal year."""
    m = RESULTS_HEADLINE_RE.search(flat(text)[:1500])
    if not m:
        return None, "no '<nth> quarter results' headline"
    q = QUARTER_WORDS[m.group(1).lower()]
    if m.group(2):
        return (q, int(m.group(2))), None

    years = set()
    for t in raw_tables:
        rows = t["rows"]
        first_data = next((i for i, r in enumerate(rows) if is_data_row(r)), len(rows))
        header = rows[:first_data]
        heading_text = " ".join(" ".join(r) for r in header) + " " + " ".join(t["context"])
        if not header or GUIDANCE_TABLE_RE.search(heading_text):
            continue
        for row in header:
            codes = [COLUMN_CODE_RE.match(c.strip()) for c in row]
            codes = [(int(c.group(1)), full_year(c.group(2))) for c in codes if c]
            if codes:
                if codes[0][0] == q:
                    years.add(codes[0][1])
                break  # only the first heading row with quarter codes counts
    if len(years) != 1:
        found = ", ".join(str(y) for y in sorted(years)) or "none"
        return None, f"results tables do not agree on one fiscal year (found: {found})"
    return (q, years.pop()), None


def _prose_period(prose, filing_date):
    lead = flat(prose)[:PERIOD_SEARCH_CHARS]
    periods = find_periods(lead)

    # Quarter-end date stated in the text, only if it fits the filing date.
    end = next((d for d in find_end_dates(lead) if within_lag(d, filing_date)), None)

    if periods:
        headline = {info[:2] for start, info in periods if start < HEADLINE_CHARS}
        if len(headline) > 1:
            return None, "headline mentions more than one quarter"
        q, y, fiscal = periods[0][1]
        display = f"{ORDINALS[q]} quarter {'fiscal ' if fiscal else ''}{y}"
        return {"q": q, "y": y, "fiscal": fiscal, "end": end,
                "display": display, "key": ("q", q, y, fiscal)}, None

    if end:
        display = f"quarter ended {end:%B} {end.day}, {end.year}"
        return {"q": None, "y": None, "fiscal": None, "end": end,
                "display": display, "key": ("end", end)}, None

    return None, "no quarter/year or quarter-end date found in the release heading"


# -----------------------------------------------------------------------------
# Step 4: table headings -> which column is the current quarter?
# -----------------------------------------------------------------------------
CHANGE_RE = re.compile(r"change|q/q|y/y|%|o/\(u\)|\bvs\.?\b|variance|increase|"
                       r"decrease|growth|\bbps\b|\bpts\b")
QUARTER_KIND_RE = re.compile(r"three months|thirteen weeks|13 weeks|\bquarters?\b|\bqtr\b")
OTHER_KIND_RE = re.compile(r"six months|nine months|twelve months|years? ended|"
                           r"fiscal years?|full[ -]year|year[ -]to[ -]date|\bytd\b|"
                           r"26 weeks|39 weeks|52 weeks|53 weeks")
FULL_DATE_RE = re.compile(r"\b([A-Z][a-z]{2,8})\.? (\d{1,2}),? ((?:19|20)\d{2})\b")
MONTH_DAY_RE = re.compile(r"\b([A-Z][a-z]{2,8})\.? (\d{1,2})\b")
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
GROUP_LINE_RE = re.compile(r"^(?:three|six|nine|twelve) months ended|"
                           r"^(?:quarter|year|fiscal years?) ended|^13 weeks ended", re.I)


def parse_header_cell(cell):
    """Describe one heading cell: its period kind, dates, year, quarter code."""
    tok = {"kind": None, "change": False, "end": None, "md": None,
           "year": None, "q": None, "y": None, "fiscal": None}
    low = cell.lower()
    if CHANGE_RE.search(low):
        tok["change"] = True
        return tok

    is_q, is_other = bool(QUARTER_KIND_RE.search(low)), bool(OTHER_KIND_RE.search(low))
    if is_q and not is_other:
        tok["kind"] = "quarter"
    elif is_other and not is_q:
        tok["kind"] = "other"

    periods = find_periods(cell)
    if periods:
        tok["q"], tok["y"], fiscal = periods[0][1]
        # A heading like "3Q24" or "Fourth Quarter 2024" does not say whether
        # the year is fiscal or calendar, so only an explicit "FY"/"fiscal" counts.
        tok["fiscal"] = True if fiscal else None
        tok["kind"] = "quarter"
    else:
        m = re.search(r"\b(first|second|third|fourth)[ -]quarter\b", low)
        if m:  # e.g. "Fourth Quarter" group heading with years below it
            tok["q"] = QUARTER_WORDS[m.group(1)]

    m = FULL_DATE_RE.search(cell)
    if m:
        tok["end"] = make_date(*m.groups())
    else:
        for m in MONTH_DAY_RE.finditer(cell):
            month = month_number(m.group(1))
            if month:
                tok["md"] = (month, int(m.group(2)))
                break

    years = YEAR_RE.findall(cell)
    if len(years) == 1 and tok["end"] is None:
        tok["year"] = int(years[0])
    return tok


def is_column(tok):
    return bool(tok["change"] or tok["end"] or tok["year"] or (tok["q"] and tok["y"]))


def is_group(tok):
    return not tok["change"] and not is_column(tok) and bool(tok["kind"] or tok["q"])


def attach_month_day(parsed):
    """Handle a month/day heading on its own row, e.g.

        Three Months Ended | Six Months Ended
        July 31,           | July 31,
        (Amounts in millions ...) | 2026 | 2025 | Percent Change | 2026 | ...

    If a row below the group headings contains ONLY month/day cells and has
    exactly as many cells as there are groups, each month/day is attached
    to its group by position. Any other layout is left alone (so an
    unclear heading still leads to NOT_FOUND rather than a guess)."""
    for gi, toks in enumerate(parsed):
        groups = [t for t in toks if is_group(t)]
        if not groups:
            continue
        for below in parsed[gi + 1:]:
            if any(is_column(t) for t in below):
                break  # reached the year / column row
            mds = [t["md"] for t in below if t["md"]]
            if mds and len(mds) == len(below) == len(groups):
                for group, md in zip(groups, mds):
                    group["md"] = group["md"] or md
                break
    return parsed


def resolve_columns(header_rows, context):
    """Build one descriptor per value column from the heading rows."""
    parsed = [[parse_header_cell(c) for c in row] for row in header_rows]
    attach_month_day(parsed)
    fine_index, fine_count = None, 0
    for i, toks in enumerate(parsed):
        count = sum(is_column(t) for t in toks)
        if count and count >= fine_count:
            fine_index, fine_count = i, count
    if fine_index is None:
        return []

    columns = [dict(t) for t in parsed[fine_index] if is_column(t)]

    # Group headings ("Three Months Ended | Nine Months Ended") above the columns
    groups = []
    for toks in reversed(parsed[:fine_index + 1]):
        found = [t for t in toks if is_group(t)]
        if found:
            groups = found
            break
    if not groups:
        for line in reversed(context):
            if GROUP_LINE_RE.search(line):
                groups = [parse_header_cell(line)]
                break

    needs_group = [i for i, c in enumerate(columns) if not c["change"] and c["kind"] is None]
    if needs_group and groups and len(needs_group) % len(groups) == 0:
        per_group = len(needs_group) // len(groups)
        for n, i in enumerate(needs_group):
            g = groups[n // per_group]
            columns[i]["kind"] = g["kind"] or ("quarter" if g["q"] else None)
            columns[i]["md"] = columns[i]["md"] or g["md"]
            columns[i]["q"] = columns[i]["q"] or g["q"]

    for c in columns:
        if c["end"] is None and c["md"] and c["year"]:
            try:
                c["end"] = date(c["year"], *c["md"])
            except ValueError:
                pass
        if c["q"] and not c["y"] and c["year"]:
            c["y"] = c["year"]
    return columns


def column_matches(col, release, filing_date):
    """True only for a three-month column that is the release's own quarter."""
    if col["change"] or col["kind"] != "quarter":
        return False
    if col["end"]:
        if release["end"]:
            return col["end"] == release["end"]
        return within_lag(col["end"], filing_date)
    if col["q"] and col["y"] and release["q"]:
        if (col["q"], col["y"]) != (release["q"], release["y"]):
            return False
        return col["fiscal"] is None or col["fiscal"] == release["fiscal"]
    return False


# -----------------------------------------------------------------------------
# Step 5: table rows
# -----------------------------------------------------------------------------
LETTER_RE = re.compile(r"[A-Za-z]")
VALUE_RE = re.compile(r"^\(?\$?\(?-?\d[\d,]*(?:\.\d+)?\)?%?\)?$")
PLACEHOLDERS = {"-", "--", "n/a", "na", "nm", "n.m."}

SCALE_PATTERNS = [
    (r"in millions|\$\s*mm\b|\$\s*millions|millions of (?:u\.s\. )?dollars", 1.0),
    (r"in thousands|\$\s*000s?\b|thousands of (?:u\.s\. )?dollars", 0.001),
    (r"in billions|\$\s*billions|billions of (?:u\.s\. )?dollars", 1000.0),
]

# Adjusted / non-GAAP / full-year / managed wording in a table title or heading
TABLE_EXCLUDE_RE = re.compile(r"non-gaap|adjusted|managed basis|excluding|pro forma")
# Same idea for a row label or the section label above it
ROW_EXCLUDE_RE = re.compile(r"adjusted|non-gaap|excluding|managed|pro forma|"
                            r"full[ -]year|twelve months|nine months|six months|"
                            r"year[ -]to[ -]date|annual")
EPS_SECTION_RE = re.compile(r"(?:earnings|income|eps)\b.*per (?:common )?share|\beps\b")
SHARE_COUNT_RE = re.compile(r"shares used|weighted|average|number of shares|"
                            r"shares outstanding|share count")
MANAGED_RE = re.compile(r"managed basis|managed revenue|managed net revenue|"
                        r"revenues?\s*-\s*managed")


def is_value_cell(cell):
    compact = cell.replace(" ", "").lower()
    return compact in PLACEHOLDERS or bool(VALUE_RE.match(compact))


def is_data_row(cells):
    if len(cells) < 2 or not LETTER_RE.search(cells[0]):
        return False
    return any(is_value_cell(c) and not YEAR_RE.fullmatch(c.strip())
               and c.strip() not in PLACEHOLDERS for c in cells[1:])


def parse_value(cell):
    """'$ 94,930' -> 94930.0, '(1,234)' -> -1234.0, '-' -> 0.0.
    Percentages and placeholders like 'n/a' -> None."""
    compact = cell.replace(" ", "")
    if compact in ("-", "--"):
        return 0.0
    if "%" in compact or compact.lower() in PLACEHOLDERS:
        return None
    digits = re.sub(r"[^\d.]", "", compact)
    if not digits or digits.count(".") > 1:
        return None
    value = float(digits)
    if "(" in compact or compact.lstrip("$").startswith("-"):
        value = -value
    return value


def detect_scale(header_text, context_lines):
    """Multiplier that converts the table's numbers to millions, or None if
    the units are not stated (then revenue/net income from it are not used).
    Looks at the table heading first, then the closest line above the table
    that states units, and uses the FIRST unit phrase in it, e.g.
    "(In millions, except shares, which are reflected in thousands)" -> millions."""
    for text in [header_text] + [line.lower() for line in reversed(context_lines)]:
        hits = []
        for pattern, scale in SCALE_PATTERNS:
            hits += [(m.start(), scale) for m in re.finditer(pattern, text)]
        if hits:
            return min(hits)[1]
    return None


def normalize_label(text):
    text = text.lower()
    text = re.sub(r"\((?:\d{1,2}|[a-z])\)|[*†‡]", "", text)  # footnotes
    text = text.replace("$", "")
    return re.sub(r"\s+", " ", text).strip(" :")


def analyze_table(raw, release, filing_date):
    rows = raw["rows"]
    first_data = next((i for i, r in enumerate(rows) if is_data_row(r)), len(rows))
    header_rows = rows[:first_data]
    header_text = " ".join(" ".join(r) for r in header_rows).lower()
    context_text = " ".join(raw["context"]).lower()

    columns = resolve_columns(header_rows, raw["context"])
    hits = [i for i, c in enumerate(columns) if column_matches(c, release, filing_date)]
    return {
        "data": rows[first_data:],
        "columns": columns,
        "target": hits[0] if len(hits) == 1 else None,   # 0 or 2+ matches = ambiguous
        "scale": detect_scale(header_text, raw["context"]),
        "excluded": bool(TABLE_EXCLUDE_RE.search(header_text + " " + context_text)),
        "heading": header_text + " " + context_text,
    }


# Row labels in priority order: (compiled regex, rule)
#   "any"          -> accepted as is
#   "generic_rev"  -> generic revenue label; in a managed/reported release it
#                     only counts if the table/section says "reported"
#   "eps_section"  -> bare "Diluted": only inside an earnings-per-share section
def _labels(patterns, rule):
    return [(re.compile(p), rule) for p in patterns]


LABELS = {
    "revenue": _labels([
        r"(?:total )?net revenues?\s*-\s*reported",
        r"(?:total )?revenues?\s*-\s*reported",
        r"reported (?:total )?(?:net )?revenues?",
        r"(?:total )?net revenues?\s*\(reported\)",
    ], "any") + _labels([
        r"total net sales",
        r"total revenues?",
        r"total net revenues?",
        r"net revenues?",
        r"revenues?",
        r"net sales",
    ], "generic_rev"),
    "net_income": _labels([
        r"(?:consolidated )?net income attributable to (?!noncontrolling)[a-z .,&']+",
        r"net income",
        r"net income \(loss\)",
        r"net earnings",
    ], "any"),
    "eps": _labels([
        r"diluted (?:net )?(?:earnings|income)(?: \(loss\))? per (?:common )?share"
        r"(?: attributable to [a-z .,&']+)?",
        r"(?:net )?(?:earnings|income)(?: \(loss\))? per (?:common )?share\s*-\s*diluted",
        r"(?:gaap )?diluted eps",
    ], "any") + _labels([r"diluted"], "eps_section"),
}


def from_tables(tables, field, doc_managed):
    for pattern, rule in LABELS[field]:
        for t in tables:
            if t["target"] is None or t["excluded"]:
                continue
            if field != "eps" and t["scale"] is None:
                continue
            section = ""
            for cells in t["data"]:
                label = normalize_label(cells[0]) if LETTER_RE.search(cells[0]) else ""
                values = [c for c in cells[1:] if is_value_cell(c)]
                if label and not values:
                    if len(cells) == 1:
                        section = label          # e.g. "Earnings per share:"
                    continue
                if not label or not pattern.fullmatch(label):
                    continue
                if ROW_EXCLUDE_RE.search(label) or ROW_EXCLUDE_RE.search(section):
                    continue
                if rule == "eps_section":
                    if not EPS_SECTION_RE.search(section) or SHARE_COUNT_RE.search(section):
                        continue
                if rule == "generic_rev" and doc_managed:
                    context = section + " " + t["heading"]
                    if "reported" not in context or "managed" in context:
                        continue
                if len(values) != len(t["columns"]):
                    continue                     # columns don't line up = ambiguous
                cell = values[t["target"]]
                value = parse_value(cell)
                if value is None:
                    continue
                if field == "eps":
                    if "." in cell and abs(value) < 1000:
                        return round(value, 2)
                    continue
                if field == "revenue" and value <= 0:
                    continue
                return round(value * t["scale"], 2)
    return None


# -----------------------------------------------------------------------------
# Step 6: narrative fallback (lead paragraphs only)
# -----------------------------------------------------------------------------
AMOUNT = r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million)"
UNIT_TO_MILLIONS = {"billion": 1000.0, "million": 1.0}
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"“])")
FULL_YEAR_RE = re.compile(r"full[ -]year|fiscal year|annual|twelve months|"
                          r"year[ -]to[ -]date|for the year|nine months|six months")
ADJUSTED_RE = re.compile(r"adjusted|non-gaap|excluding|excludes|pro forma")
GUIDANCE_RE = re.compile(r"outlook|guidance|expects?|expected|forecast|anticipates?")

NARRATIVE = {
    "revenue": [re.compile(
        r"(?:(?:reported|total|quarterly|consolidated|net|record) )*"
        r"(?:revenues?|net sales)"
        r"(?: for the (?:first|second|third|fourth)[ -]quarter"
        r"(?: of (?:fiscal )?\d{4})?(?: ended [A-Z][a-z]+\.? \d{1,2}, \d{4})?,?)?"
        r"(?: was| were| of| totaled| reached)?(?: a)?(?: record)?(?: of)?\s+" + AMOUNT,
        re.I)],
    "net_income": [re.compile(
        r"net income(?: attributable to [A-Za-z .,&']{1,40}?)?"
        r"(?: was| of| totaled)?\s+" + AMOUNT, re.I)],
    "eps": [
        re.compile(r"diluted (?:earnings|net income) per (?:common )?share"
                   r"(?: \(\"?eps\"?\))?(?: was| of)\s+\$(\d+\.\d{2})", re.I),
        re.compile(r"\$(\d+\.\d{2}) per diluted share", re.I),
        re.compile(r"(?:gaap )?diluted eps(?: was| of)\s+\$(\d+\.\d{2})", re.I),
    ],
}


def sentence_conflicts(sentence, release):
    """True if the sentence names a quarter or quarter-end date that is not
    the release's own period (or one that cannot be checked)."""
    for _, (q, y, _) in find_periods(sentence):
        if release["q"] is None or (q, y) != (release["q"], release["y"]):
            return True
    for d in find_end_dates(sentence):
        if release["end"] is None or d != release["end"]:
            return True
    return False


def from_narrative(prose, field, release, doc_managed):
    lead = flat(prose)[:LEAD_CHARS]
    for sentence in SENTENCE_SPLIT.split(lead):
        if GUIDANCE_RE.search(sentence.lower()) or sentence_conflicts(sentence, release):
            continue
        for pattern in NARRATIVE[field]:
            for m in pattern.finditer(sentence):
                matched = m.group(0).lower()
                before = sentence[max(0, m.start() - 80):m.start()].lower()
                after = sentence[m.end():m.end() + 30].lower()
                if FULL_YEAR_RE.search(before + " " + matched):
                    continue
                if ADJUSTED_RE.search(before + " " + matched) or ADJUSTED_RE.search(after):
                    continue
                if "noncontrolling" in matched:
                    continue
                if field == "revenue" and doc_managed:
                    near = before[-30:] + " " + matched
                    if "reported" not in near or "managed" in near:
                        continue
                number = float(m.group(1).replace(",", ""))
                if field == "eps":
                    return round(number, 2)
                return round(number * UNIT_TO_MILLIONS[m.group(2).lower()], 2)
    return None


# -----------------------------------------------------------------------------
# Step 7: one release -> one row
# -----------------------------------------------------------------------------
# "<Nth> Quarter Highlights" section (table blocks included), up to the end of
# its table block or the next blank line.
HIGHLIGHTS_RE = re.compile(
    r"\b(first|second|third|fourth) quarter highlights\b(.*?)(?=\[/TABLE\]|\n\s*\n|\Z)",
    re.I | re.S)
# A bullet that STARTS with the consolidated revenue figure, e.g.
# "Revenue of $187.9 billion, up 5.9%, or 5.1% (cc)". Growth-rate bullets
# ("Revenue growth of 5.9%"), "Membership fee revenue ..." and the (cc)
# percentages after the amount cannot match.
REVENUE_BULLET_RE = re.compile(
    r"^(?:total |consolidated )?revenues? of \$(\d{1,3}(?:,\d{3})*(?:\.(\d+))?) ?"
    r"(billion|million)\b", re.I)


def highlights_revenue(text, release, doc_managed):
    """(revenue in $ millions, rounding tolerance in $ millions) from the
    highlights section for the release's own quarter, or (None, None).

    Returns None when the release quarter is unknown, when the release
    reports managed vs. reported revenue (a plain "Revenue of" bullet does
    not say which), when the section is for a different quarter, or when
    the section has zero or several revenue bullets."""
    if release["q"] is None or doc_managed:
        return None, None
    for section in HIGHLIGHTS_RE.finditer(text):
        if QUARTER_WORDS[section.group(1).lower()] != release["q"]:
            continue
        hits = []
        for bullet in re.split(r"[•◦]", section.group(2)):
            m = REVENUE_BULLET_RE.match(bullet.strip())
            if m:
                multiplier = UNIT_TO_MILLIONS[m.group(3).lower()]
                decimals = len(m.group(2) or "")
                amount = float(m.group(1).replace(",", "")) * multiplier
                tolerance = 0.5 * (10 ** -decimals) * multiplier + 0.5
                hits.append((round(amount, 2), tolerance))
        return hits[0] if len(hits) == 1 else (None, None)
    return None, None


def tidy(value):
    """94930.0 -> 94930, 0.97 -> 0.97 (keeps the CSV clean)."""
    return int(value) if float(value).is_integer() else value


def extract_release(html, filing_date):
    """Return (release, fields) or (None, reason)."""
    return extract_from_text(html_to_text(html), filing_date)


def extract_from_text(text, filing_date):
    """Same as extract_release, starting from already-converted plain text
    (lets a saved release such as wmt_latest_release.txt be re-checked)."""
    prose, raw_tables = split_blocks(text)

    release, reason = identify_release(prose, filing_date, text, raw_tables)
    if release is None:
        return None, reason

    doc_managed = bool(MANAGED_RE.search(flat(text).lower()))
    tables = [analyze_table(t, release, filing_date) for t in raw_tables]

    fields = {"period": release["display"]}

    # Revenue: income statement first; "<Nth> Quarter Highlights" bullet is the
    # reasonableness check and the fallback; lead-paragraph narrative last.
    revenue = from_tables(tables, "revenue", doc_managed)
    highlight, tolerance = highlights_revenue(text, release, doc_managed)
    if revenue is not None and highlight is not None:
        if abs(revenue - highlight) > tolerance:
            # The two sources disagree, so neither can be trusted.
            print(f"  WARNING: statement revenue {revenue:,.0f}M does not match the "
                  f"highlights figure {highlight:,.0f}M (+/- {tolerance:,.0f}M rounding); "
                  f"revenue set to {NOT_FOUND}")
            revenue = None
    elif revenue is None and highlight is not None:
        print(f"  NOTE: revenue taken from the rounded highlights figure "
              f"(+/- {tolerance:,.0f}M)")
        revenue = highlight
    elif revenue is None:
        revenue = from_narrative(prose, "revenue", release, doc_managed)
    fields["revenue_reported"] = NOT_FOUND if revenue is None else tidy(revenue)

    for field, column in (("eps", "eps_diluted"), ("net_income", "net_income")):
        value = from_tables(tables, field, doc_managed)
        if value is None:
            value = from_narrative(prose, field, release, doc_managed)
        fields[column] = NOT_FOUND if value is None else tidy(value)
    return release, fields


def money(value):
    if value == NOT_FOUND:
        return NOT_FOUND
    return f"${value:,.0f}M" if float(value).is_integer() else f"${value:,.2f}M"


def eps_text(value):
    return NOT_FOUND if value == NOT_FOUND else f"${value:.2f}"


def process_company(company, ticker, cik):
    print(f"\n{ticker} ({company}, CIK {cik})")
    resp = sec_get(SUBMISSIONS_URL.format(cik=cik))
    if resp is None:
        print(f"  WARNING: could not download submissions for {ticker}; skipping company")
        return []
    try:
        submissions = resp.json()
    except ValueError:
        print(f"  WARNING: submissions for {ticker} were not valid JSON; skipping company")
        return []

    rows, seen = [], set()
    for filing in earnings_candidates(submissions):
        if len(rows) == QUARTERS_WANTED:
            break
        accession, filing_date = filing["accession"], filing["filing_date"]

        exhibit_url = find_press_release(cik, accession)
        if exhibit_url is None:
            print(f"  WARNING: skipping {accession} ({filing_date}): press release not found")
            continue
        resp = sec_get(exhibit_url)
        if resp is None:
            print(f"  WARNING: skipping {accession} ({filing_date}): press release download failed")
            continue

        try:
            release, fields = extract_release(resp.content, date.fromisoformat(filing_date))
        except Exception as exc:  # one malformed document should not stop the run
            print(f"  WARNING: skipping {accession} ({filing_date}): could not parse ({exc})")
            continue
        if release is None:
            print(f"  WARNING: skipping {accession} ({filing_date}): reporting period "
                  f"could not be identified ({fields})")
            continue
        if release["key"] in seen:
            print(f"  WARNING: skipping {accession} ({filing_date}): "
                  f"{release['display']} was already collected from a newer filing")
            continue
        seen.add(release["key"])

        row = {"company": company, "ticker": ticker, "cik": cik,
               "filing_date": filing_date}
        row.update(fields)
        print(f"{ticker} | {row['period']} | Revenue: {money(row['revenue_reported'])} | "
              f"EPS: {eps_text(row['eps_diluted'])} | "
              f"Net Income: {money(row['net_income'])}")
        rows.append(row)

    if len(rows) < QUARTERS_WANTED:
        print(f"  WARNING: only {len(rows)} distinct quarter(s) collected for {ticker}; "
              f"no more Item 2.02 candidates")
    return rows


def main():
    print("Revenue and Net Income are in millions of US dollars (M). "
          "EPS is GAAP diluted, in dollars per share.")
    all_rows = []
    for company, ticker, cik in COMPANIES:
        try:
            all_rows.extend(process_company(company, ticker, cik))
        except Exception as exc:  # one company failing should not stop the run
            print(f"  WARNING: unexpected error while processing {ticker} ({exc})")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nSaved {len(all_rows)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
