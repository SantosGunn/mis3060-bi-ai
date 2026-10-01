"""
=============================================================================
Script:     hw03_executives.py
Purpose:    Collect executive and director departures and appointments
            (Form 8-K, Item 5.02) filed in the past 12 months for five
            companies from SEC EDGAR.
Author:     Santos Gunningham
Generated:  2026-09-30

Run from the repository's main folder:
    python hw03/hw03_executives.py

Output:
    hw03/executive_events.csv   (headers are written even with zero rows)

How it works:
    1. Filings: Form 8-K filings whose items include 5.02 and whose filing
       date is within the past 12 months (counted back from the day the
       script runs). If the "recent" list in the submissions JSON does not
       reach back that far, the older submissions files it references are
       downloaded too.
    2. Text: the primary 8-K document is converted to plain text, and only
       the Item 5.02 section is used (from the "Item 5.02" heading to the
       next "Item X.XX" heading or the signature block).
    3. Sentences: the section is split into sentences. A person counts only
       when a departure word (retire, resign, step down, ...) or an
       appointment word (appointed, elected, named, will become, ...) is in
       the same part of the sentence as their name. People mentioned as
       objects ("will report to X", "succeeding X", "thanked X") are ignored.
       Later references such as "Mr. Smith" are linked back to the full name.
    4. One row per distinct event. Different appointments for the same person
       (e.g. CEO and director, or a January role and a March role) are
       separate rows. "both" is used only for one person's single combined
       change stated in one clause: "transition from his role as X to Y",
       "will step down as X and will become Y", "current X ... will become Y",
       or "continue to serve as X until <date>, at which time he will
       transition to Y". A shorter name ("Ms. Nora Johnson") is merged with a
       longer one ("Suzanne Nora Johnson") only when exactly one longer name
       in the filing matches it.
    5. Effective dates come only from the clause that describes the event:
       "effective October 1, 2026", "effective on the close of business on
       ...", a defined term such as "effective on the Transition Date"
       (looked up from '... (the "Transition Date")'), "effective upon the
       commencement of his employment ... on May 4, 2026", "will become ...
       on March 1, 2026", or "On August 5, 2026, X resigned ... effective
       immediately". Conditional or anticipated dates ("effective upon ...,
       which is anticipated to be on ...") stay NOT_FOUND and are printed as
       REVIEW notes. The filing date is never used as an effective date.
    6. Filings with no departure or appointment (for example compensation
       only) print an explanation and add no rows. Any field that cannot be
       extracted for a real event is saved as NOT_FOUND.
=============================================================================
"""

import csv
import re
import time
from datetime import date
from pathlib import Path

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

NOT_FOUND = "NOT_FOUND"
SEC_BASE = "https://www.sec.gov"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"

OUT_PATH = Path(__file__).resolve().parent / "executive_events.csv"
COLUMNS = [
    "company", "ticker", "cik", "filing_date", "event_type",
    "person_name", "title", "effective_date",
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


def get_json(url):
    resp = sec_get(url)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        print(f"  WARNING: response from {url} was not valid JSON")
        return None


# -----------------------------------------------------------------------------
# Step 1: matching filings in the 12-month window
# -----------------------------------------------------------------------------
def one_year_before(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:            # February 29
        return day.replace(year=day.year - 1, day=28)


def filing_rows(block):
    """Turn the column arrays of a submissions block into a list of dicts."""
    keys = ("accessionNumber", "filingDate", "form", "items", "primaryDocument")
    columns = [block.get(k, []) for k in keys]
    return [dict(zip(keys, values)) for values in zip(*columns)]


def matching_filings(submissions, start, end):
    """Return (filings, complete). `complete` is False if an older
    submissions file that was needed could not be downloaded."""
    recent = submissions.get("filings", {}).get("recent", {})
    rows = filing_rows(recent)
    complete = True

    start_text, end_text = start.isoformat(), end.isoformat()
    oldest_recent = min((r["filingDate"] for r in rows), default=None)
    if oldest_recent is None or oldest_recent >= start_text:
        # The recent list may not reach back 12 months: load older files.
        for extra in submissions.get("filings", {}).get("files", []):
            if extra.get("filingTo", "") < start_text:
                continue
            data = get_json(SUBMISSIONS_FILE_URL.format(name=extra.get("name", "")))
            if data is None:
                print(f"  WARNING: could not load older submissions file {extra.get('name')}")
                complete = False
                continue
            rows += filing_rows(data)

    seen, matches = set(), []
    for r in rows:
        if r["form"] != "8-K":
            continue
        if "5.02" not in [i.strip() for i in (r["items"] or "").split(",")]:
            continue
        if not (start_text <= r["filingDate"] <= end_text):
            continue
        if r["accessionNumber"] in seen:
            continue
        seen.add(r["accessionNumber"])
        matches.append(r)
    matches.sort(key=lambda r: r["filingDate"], reverse=True)
    return matches, complete


# -----------------------------------------------------------------------------
# Step 2: HTML -> plain text -> Item 5.02 section
# -----------------------------------------------------------------------------
BLOCK_TAGS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table"]
CHAR_FIXES = {"\xa0": " ", "​": "", "’": "'", "‘": "'",
              "“": '"', "”": '"', "–": "-", "—": "-",
              "‐": "-", "‑": "-", "−": "-"}


def fix_chars(text):
    for bad, good in CHAR_FIXES.items():
        text = text.replace(bad, good)
    return text


def html_to_text(html):
    """Plain text with readable spacing: each block element is one line,
    table cells are separated by ' | ', blank-line runs are collapsed."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for piece in list(soup.find_all(string=True)):
        if type(piece) is NavigableString and ("\n" in piece or "\r" in piece):
            piece.replace_with(re.sub(r"[\r\n]+", " ", str(piece)))
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.append(" | ")
    for block in soup.find_all(BLOCK_TAGS):
        block.append("\n")

    lines, previous_blank = [], False
    for line in fix_chars(soup.get_text()).splitlines():
        line = re.sub(r"[ \t]+", " ", line)
        line = re.sub(r"(?:\s*\|\s*)+$", "", line)          # trailing cell bars
        line = re.sub(r"^(?:\s*\|\s*)+", "", line).strip()   # leading cell bars
        if line:
            lines.append(line)
            previous_blank = False
        elif not previous_blank:
            lines.append("")
            previous_blank = True
    return "\n".join(lines).strip()


ITEM_502_START = re.compile(r"(?im)^\s*item\s*5\.02\b")
SECTION_END = re.compile(r"(?im)^\s*(?:item\s*\d{1,2}\.\d{2}\b|signatures?\b)")
ITEM_502_TITLE = re.compile(
    r"item\s*5\.02\.?\s*(?:\|\s*)?"
    r"(?:departure of directors or (?:certain )?(?:principal )?officers;?\s*"
    r"election of directors;?\s*appointment of (?:certain )?(?:principal )?officers;?\s*"
    r"(?:and\s*)?compensatory arrangements of certain officers\.?)?", re.I)


HEADING_LEFTOVER = re.compile(r"^[\W\d]*(?:departure|election|appointment|compensatory)\b"
                              r"[^.]*(?:officers?|directors?|arrangements)\W*$", re.I)


def item_502_section(text):
    """The Item 5.02 section without its heading, or None if not found.
    If the heading appears more than once (e.g. an index), the longest
    section is used."""
    sections = []
    for m in ITEM_502_START.finditer(text):
        rest = text[m.start():]
        end = SECTION_END.search(rest, pos=len(m.group(0)))
        sections.append(rest[:end.start()] if end else rest)
    if not sections:
        # Fallback: "Item 5.02" mentioned mid-line
        m = re.search(r"item\s*5\.02\b", text, re.I)
        if not m:
            return None
        rest = text[m.start():]
        end = re.search(r"(?i)\bitem\s*\d{1,2}\.\d{2}\b|\bsignatures?\b", rest[len(m.group(0)):])
        sections.append(rest[:len(m.group(0)) + end.start()] if end else rest)
    section = ITEM_502_TITLE.sub("", max(sections, key=len), count=1).strip()
    return clean_section(section)


# The standard Item 5.02 heading text, wherever it is repeated inside the
# section (JPMorgan repeats it after each "(b)" / "(e)" subsection label).
REPEATED_HEADING = re.compile(
    r"departure of directors or (?:certain )?(?:principal )?officers;?\s*"
    r"election of directors;?\s*appointment of (?:certain )?(?:principal )?officers;?\s*"
    r"(?:and\s*)?compensatory arrangements of certain officers\.?", re.I)


def clean_section(section):
    """Remove repeated heading text, bare subsection labels like "(b)", and a
    shortened heading line such as "Departure of Directors or Certain Officers"."""
    section = REPEATED_HEADING.sub("", section)
    lines = []
    for line in section.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"\(?[a-z]\)?\s*\.?", stripped):
            continue
        if len(stripped) < 250 and HEADING_LEFTOVER.match(stripped) and not re.search(r"\d{4}", stripped):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# -----------------------------------------------------------------------------
# Step 3: sentences, names, keywords
# -----------------------------------------------------------------------------
ABBREVIATIONS = ["Mr.", "Ms.", "Mrs.", "Dr.", "Jr.", "Sr.", "Inc.", "Co.", "Corp.",
                 "Ltd.", "No.", "U.S.", "N.A.", "St.", "Jan.", "Feb.", "Mar.", "Apr.",
                 "Jun.", "Jul.", "Aug.", "Sep.", "Sept.", "Oct.", "Nov.", "Dec.", "vs.",
                 "Messrs."]
DOT = "․"   # placeholder so abbreviations don't end a sentence


def split_sentences(section):
    sentences = []
    for paragraph in section.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # A footnote number glued to a period ("effective immediately.1 In
        # addition ...") would otherwise hide the sentence break.
        paragraph = re.sub(r"\.(\d{1,2})(?=\s+[A-Z])", ".", paragraph)
        for abbr in ABBREVIATIONS:
            paragraph = paragraph.replace(abbr, abbr.replace(".", DOT))
        paragraph = re.sub(r"\b([A-Z])\.(?=\s+[A-Z])", r"\1" + DOT, paragraph)  # initials
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", paragraph):
            piece = piece.replace(DOT, ".").strip()
            if piece:
                sentences.append(piece)
    return sentences


# Name tokens: "Kevan", "McMillon", "O'Brien", "Smith-Jones", or an initial "M."
NAME_TOKEN = re.compile(r"[A-Z][a-z]+(?:[A-Z][a-z]+)?(?:[-'][A-Z][a-z]+)?|[A-Z]\.")
NAME_RUN = re.compile(r"(?:[A-Z][a-z]+(?:[A-Z][a-z]+)?(?:[-'][A-Z][a-z]+)?|[A-Z]\.)"
                      r"(?:\s+(?:[A-Z][a-z]+(?:[A-Z][a-z]+)?(?:[-'][A-Z][a-z]+)?|[A-Z]\.))+")
HONORIFIC = re.compile(r"\b(Mr|Ms|Mrs|Dr)\.\s+([A-Z][A-Za-z'-]*[A-Za-z])")

# Capitalized words that are never part of a person's name
STOP_WORDS = set("""
the on in as at by for of and or to a an also effective pursuant there following upon
during under our his her their its new this that these such each any all no item form
section exhibit exhibits signature signatures date dated report current act exchange
securities commission rule regulation board directors director company corporation inc
co corp ltd llc llp plc group holdings bank chase jpmorgan jpmorganchase firm apple
microsoft nvidia walmart sam club america american united states u.s n.a global
international national chief officer officers executive president vice senior
financial operating technology legal general counsel chair chairman chairwoman
chairperson lead independent committee committees audit compensation nominating
governance corporate risk human capital resources people talent culture annual meeting
shareholders stockholders agreement agreements plan plans stock incentive award awards
equity restricted performance units non employee deferred retirement severance letter
offer treasurer controller secretary accounting principal head interim acting emeritus
advisor adviser strategic operations products marketing sales worldwide field strategy
development engineering software hardware platform research data center cloud business
division segment services retail consumer community banking asset wealth management
commercial investment markets payments digital commerce ecommerce supply chain finance
investor relations communications affairs policy government public partner partners
fellow member members forward looking statements press release departure departures
election elections appointment appointments certain compensatory arrangements monday
tuesday wednesday thursday friday saturday sunday january february march april may june
july august september october november december mr ms mrs dr messrs new york delaware
california washington arkansas redmond cupertino santa clara bentonville seattle
unaudited table contents transition separation position role
""".split())

TITLE_WORDS = re.compile(
    r"\b(?:Chief|Officers?|Presidents?|Chairs?|Chairman|Chairwoman|Chairperson|"
    r"Directors?|Treasurer|Controller|Secretary|Counsel|Head|Executive|CEOs?|CFO|COO|"
    r"CTO|CAO|CLO|CIO|CHRO|VP|SVP|EVP|Partner|Member|Advisor|Adviser|Fellow|Leader)\b")

DEPARTURE_RE = re.compile(
    r"\b(?:retir(?:e|es|ed|ing|ement)(?! (?:plan|benefit|savings|eligib|age|program|account))|"
    r"resign(?:s|ed|ing|ation)?|step(?:s|ped|ping)? down|stepping down|"
    r"depart(?:s|ed|ing|ure)?|"
    r"termination of (?:his|her|their) (?:employment|service)|"
    r"employment (?:will |was |has been )?terminat\w*|"
    r"separat(?:e|es|ed|ing|ion) from|separation|"
    r"(?:will not|not to|decided not to|elected not to) (?:stand|seek|run) for re-?election|"
    r"will leave|leaving the company|ceas(?:e|es|ed|ing) to (?:serve|be)|"
    r"transition(?:s|ed|ing)? from|"
    r"end(?:ed|ing)? (?:his|her|their) (?:employment|service))\b", re.I)

APPOINTMENT_RE = re.compile(
    r"\b(?:appoint(?:ed|s|ing|ment)?|(?<!re-)(?<!re)elect(?:ed|s|ing|ion)?|"
    r"named(?! executive officers?)|promot(?:ed|es|ion)|hired|"
    r"will (?:become|join|assume)|to (?:become|join)|"
    r"(?<!continue to )serve as|(?<!continue to )will serve as|"
    r"assume the (?:role|position|title)|has joined|"
    r"transition(?:s|ed|ing)? to (?:the |a |an )?(?:new )?(?:role|position|title)s?)\b", re.I)
# "appoint a successor", "a search for a successor": not an appointment of the person
SUCCESSOR_AFTER = re.compile(r"^\s*(?:a |his |her |their )?(?:new |permanent )?successor", re.I)

# Contract terms describing what WOULD happen ("if Mr. X is terminated",
# "for two years following termination") are not departures.
HYPOTHETICAL_RE = re.compile(r"\bif\b|in the event|covenant|non-?compet|for a period of|"
                             r"following (?:his |her |their )?termination|"
                             r"upon (?:his |her |their )?termination", re.I)

# A name right after these words is an object, not the person changing roles.
OBJECT_PREFIX = re.compile(
    r"(?:report(?:s|ing)? (?:directly )?to(?:\s+(?:the\s+)?[A-Z][\w&.]*)*|by|with|"
    r"thank(?:s|ed)?|succeed(?:s|ed|ing)?|replac(?:e|es|ed|ing)|successor to|alongside|"
    r"under|previously held by)\s*$")

# Names joined only by ", " / "and", optionally with ages: "Doug Petno, 61, and Troy ..."
CONJUNCTION_ONLY = re.compile(r"^\s*(?:,\s*(?:age\s+)?\d{1,3}\s*)?(?:,|,?\s*and|&)\s*$", re.I)
CLAUSE_BREAK = re.compile(r",|;| and | while |\(|\)")


def is_stop(token):
    if re.fullmatch(r"[A-Z]\.", token):
        return False  # a middle initial such as "A." is part of a name
    return token.lower().rstrip(".") in STOP_WORDS


def full_name_mentions(sentence):
    """Runs of 2+ capitalized name tokens with no stop words."""
    mentions = []
    for run in NAME_RUN.finditer(sentence):
        tokens = [(t.start() + run.start(), t.end() + run.start(), t.group(0))
                  for t in NAME_TOKEN.finditer(run.group(0))]
        group = []
        for tok in tokens + [None]:
            if tok is not None and not is_stop(tok[2]):
                group.append(tok)
                continue
            real = [g for g in group if not re.fullmatch(r"[A-Z]\.", g[2])]
            if len(real) >= 2 and not re.fullmatch(r"[A-Z]\.", group[-1][2]):
                start, end = group[0][0], group[-1][1]
                mentions.append({"start": start, "end": end,
                                 "name": sentence[start:end], "surname": group[-1][2]})
            group = []
    return mentions


def honorific_mentions(sentence, taken):
    out = []
    for m in HONORIFIC.finditer(sentence):
        if any(t["start"] <= m.start(2) < t["end"] for t in taken):
            continue  # "Mr. John Smith" is already a full-name mention
        surname = re.sub(r"'s$", "", m.group(2))
        out.append({"start": m.start(), "end": m.end(), "name": None, "surname": surname})
    return out


def same_person(short, long):
    """True if `short` unambiguously refers to `long`: it is the end of the
    longer name ("Nora Johnson" / "Suzanne Nora Johnson"), or the longer name
    only adds middle initials ("John Furner" / "John R. Furner")."""
    a, b = short.split(), long.split()
    if len(a) >= len(b):
        return False
    if b[-len(a):] == a:
        return True
    extra = [t for t in b if t not in a]
    return (a[0] == b[0] and a[-1] == b[-1]
            and all(re.fullmatch(r"[A-Z]\.", t) for t in extra))


def build_name_index(sentences):
    """canonical: name -> full name; surname_map: surname -> full name.
    A shorter form is merged only if exactly one longer name matches it."""
    names = []
    for s in sentences:
        for m in full_name_mentions(s):
            if m["name"] not in names:
                names.append(m["name"])
    canonical = {}
    for n in names:
        longer = [o for o in names if o != n and same_person(n, o)]
        canonical[n] = longer[0] if len(longer) == 1 else n
    by_surname = {}
    for n in dict.fromkeys(canonical.values()):
        last = [t for t in n.split() if t.rstrip(".") not in ("Jr", "Sr")][-1]
        by_surname.setdefault(last, set()).add(n)
    surname_map = {s: next(iter(v)) for s, v in by_surname.items() if len(v) == 1}
    return canonical, surname_map


# -----------------------------------------------------------------------------
# Step 4: titles and effective dates
# -----------------------------------------------------------------------------
MONTH_WORDS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
               "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
DATE_PATTERN = (r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
                r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
                r"\.?\s+\d{1,2},?\s+\d{4}|\b\d{1,2}/\d{1,2}/\d{4}")
DEFINED_TERM = r"[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\s+Date"
# "September 1, 2026 (the "Transition Date")"
DEFINITION_RE = re.compile(r"(" + DATE_PATTERN + r")\s*\(\s*(?:the\s+)?\"(" + DEFINED_TERM + r")\"\s*\)")
DATE_OR_TERM = r"(?:(?P<date>" + DATE_PATTERN + r")|the\s+\"?(?P<term>" + DEFINED_TERM + r")\b)"

# Effective-date phrases, tried in order on the text that starts at "effective"
EFFECTIVE_DATE_RE = re.compile(
    r"^effective\s+(?:as\s+of\s+|on\s+|at\s+)?(?:the\s+close\s+of\s+business\s+(?:on\s+)?)?"
    + DATE_OR_TERM, re.I)
EFFECTIVE_START_ON_RE = re.compile(
    r"^effective\s+upon\s+the\s+commencement\s+of\s+(?:his|her|their)\s+employment"
    r"(?:\s+with\s+the\s+Company)?\s+on\s+" + DATE_OR_TERM, re.I)
EFFECTIVE_IMMEDIATELY_RE = re.compile(r"^effective\s+immediately", re.I)
EFFECTIVE_CONDITION_RE = re.compile(r"^effective\s+(?:upon|following|after|as of the conclusion|"
                                    r"at the (?:conclusion|time))", re.I)
ANTICIPATED_RE = re.compile(r"(?:anticipated|expected|scheduled)\s+to\s+(?:be|occur)\s+(?:on\s+)?("
                            + DATE_PATTERN + ")", re.I)
# No "effective" wording: "will become general counsel on March 1, 2026",
# "was elected to the Board on November 13, 2025"
VERB_ON_DATE_RE = re.compile(
    r"\b(?:become|becomes|retire[sd]?|resign(?:s|ed)?|step(?:s|ped)? down|depart(?:s|ed)?|"
    r"leave|separate|join|assume|begin|start|elected|appointed|named)\b"
    r"(?:\s+[\w'&.-]+){0,8}?\s+(?:on|as of)\s+" + DATE_OR_TERM, re.I)
ON_DATE_START = re.compile(r"^\s*(?:\([a-z]\)\s*)?(?:Also\s+)?On\s+(" + DATE_PATTERN + r")\s*,", re.I)
PAST_EVENT = re.compile(r"\b(?:resigned|retired|stepped down|departed|was appointed|"
                        r"were appointed|appointed|was elected|were elected|elected|"
                        r"was named|named|was promoted|promoted|ceased to serve)\b", re.I)
FUTURE_WORDS = re.compile(r"\b(?:will|intends?|intention|decision to|plans? to|expects? to|"
                          r"notified|informed|advised)\b", re.I)
# "will continue to serve as X until ... January 31, 2026, at which time he will
# transition to the role of Y" / "will transition from his role as X to Y"
CONTINUE_THEN_TRANSITION_RE = re.compile(
    r"continue to serve as (?P<from>[^;]+?) until (?:the close of business on )?(?P<date>"
    + DATE_PATTERN + r"),? at which time (?:he|she|they) will transition to (?:the role of )?(?P<to>[^;]+)")
TRANSITION_FROM_TO_RE = re.compile(
    r"(?i:transition(?:s|ed|ing)?\s+from\s+(?:his|her|their)\s+(?:current\s+)?(?:role|position)s?"
    r"\s+(?:as\s+)?)(?P<from>[^;]+?)\s+to\s+(?:the\s+(?:role|position)\s+of\s+)?(?P<to>[A-Z][^;]*)")
ROLE_END_RE = re.compile(
    r"remain in (?:his|her|their) current (?:position|role)\b[^.;]*?\b(" + DATE_PATTERN + ")", re.I)

TITLE_TRIGGER = re.compile(
    r"\b(?:as|become|becoming|be named|named|appointed|elected|promoted to|"
    r"assume the (?:role|position|title) of|to the (?:newly created )?(?:position|role|office) of|"
    r"(?:position|role|office|title)s? of)\s+", re.I)
LEADING_WORDS = re.compile(
    r"^(?:(?:the|its|our|a|an|new|newly created|current|currently|sole|serving as)\s+|"
    r"(?:[A-Z][\w.&-]*\s+)*?[A-Z][\w.&-]*'s\s+)+")
COMPANY_WORDS = (r"(?:Company|Corporation|Firm|Apple|Microsoft|NVIDIA|JPMorgan(?:Chase)?|"
                 r"Walmart(?: Inc\.?)?|Bank)")
COMPANY_TAIL = re.compile(r"\s+(?:of|for)\s+(?:the\s+)?" + COMPANY_WORDS + r"\b(?!'s Board).*$")
BOARD_OF = re.compile(r"\bof [A-Z][\w&.]*'s Board(?: of Directors)?")
COMPANY_SEGMENT = re.compile(r"\b(?:Inc|Corporation|Corp|Company|Co|LLC|Ltd|PLC|Firm)\b")
DIRECTOR_HINT = re.compile(
    r"\b(?:to|from|on|of) (?:the |its |our |[A-Z][\w&.]*'s )?board\b(?!'s)|"
    r"\bas (?:a |an )?(?:independent |non-employee )?(?:member of the board|directors?)\b|"
    r"\bdirectors?\b", re.I)
AND_DIRECTOR = re.compile(r"^[^;]{0,40}?\band (?:as )?(?:a |an )?(?:member of (?:the|its|our) "
                          r"Board|director)\b", re.I)

# Lowercase titles ("president and chief executive officer", "general counsel")
_LT = (r"(?:(?:executive|senior)\s+vice\s+president|vice\s+president|president|"
       r"chief\s+[a-z]+(?:\s+[a-z]+)?\s+officer|general\s+counsel|(?:corporate\s+)?secretary|"
       r"treasurer|(?:corporate\s+)?controller|lead\s+independent\s+director|"
       r"chair(?:man|woman|person)?(?:\s+of\s+the\s+board)?)")
LOWER_TITLE_RE = re.compile(r"^" + _LT + r"(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s+)" + _LT + r")*")


def parse_date(text):
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    try:
        if m:
            month = MONTH_WORDS.get(m.group(1)[:3].lower())
            return date(int(m.group(3)), month, int(m.group(2))).isoformat() if month else None
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if m:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None
    return None


def defined_dates(section):
    """{"transition date": "2026-09-01", ...} from '(the "Transition Date")'.
    A term defined with two different dates is ambiguous and left out."""
    found = {}
    for m in DEFINITION_RE.finditer(re.sub(r"\s+", " ", section)):
        found.setdefault(m.group(2).lower(), set()).add(parse_date(m.group(1)))
    return {k: next(iter(v)) for k, v in found.items() if len(v) == 1 and None not in v}


def resolve(match, defined):
    if match.group("date"):
        return parse_date(match.group("date"))
    return defined.get(match.group("term").lower())


def tidy_title(title):
    title = BOARD_OF.sub("of the Board", title)
    title = COMPANY_TAIL.sub("", title).strip(" ,")
    title = re.sub(r"\b(Co-)?(President|Officer|Director|Chair|CEO)s\b", r"\1\2", title)
    return title or None


def lowercase_title(text):
    m = LOWER_TITLE_RE.match(text)
    if not m:
        return None
    small = {"and", "of", "the"}
    return re.sub(r"[A-Za-z]+", lambda w: w.group(0) if w.group(0) in small
                  else w.group(0).capitalize(), m.group(0).strip(" ,"))


def capture_title(text):
    """Title at the start of `text`, e.g. 'Executive Vice President, President
    and Chief Executive Officer, Walmart U.S., effective ...' ->
    'Executive Vice President, President and Chief Executive Officer, Walmart U.S.'
    One business-unit segment without title words (', Walmart U.S.',
    ', Worldwide Field Operations') may end the title, but never a segment
    that looks like a person's name or a company name. None if no title."""
    text = LEADING_WORDS.sub("", text.strip())
    if text[:1].islower():
        return lowercase_title(text)
    segments, current = [], []
    for word in re.findall(r"[A-Za-z][\w&'.-]*|,|\(|\)|&|\"", text):
        if word == ",":
            segments.append(current)
            current = []
            continue
        if word in ("(", ")", '"'):
            break
        if word[0].isupper() or word == "&" or (current and word in ("of", "and", "the", "for")):
            current.append(word)
        else:
            break
    segments.append(current)

    kept = []
    for i, seg in enumerate(segments):
        while seg and seg[-1] in ("of", "and", "the", "for", "&"):
            seg = seg[:-1]
        phrase = " ".join(seg)
        if not re.search(r"\b[A-Z]\.[A-Z]\.$", phrase):
            phrase = phrase.rstrip(".")
        if not phrase:
            break
        if TITLE_WORDS.search(phrase):
            if i > 0 and not is_stop(seg[0]) and not TITLE_WORDS.search(seg[0]):
                break  # e.g. ", Jane Doe will ..." - a name, not a title
            kept.append(phrase)
            continue
        unit = tidy_title(phrase) or ""
        if (i > 0 and kept and unit and len(unit.split()) <= 6
                and not COMPANY_SEGMENT.search(unit) and not full_name_mentions(unit)):
            kept.append(unit)  # business unit, always the last segment
        break
    if not kept:
        return None
    return tidy_title(", ".join(kept))


def titles_after(window, position):
    """Titles introduced by a trigger word at or after `position`. Returns a
    list: 'as Chief Executive Officer and a member of the Board' gives two."""
    for m in TITLE_TRIGGER.finditer(window, position):
        title = capture_title(window[m.end():])
        if title:
            titles = [title]
            rest = window[m.end():]
            if title != "Director" and AND_DIRECTOR.match(rest[len(title):] if rest.startswith(title)
                                                          else rest):
                titles.append("Director")
            return titles
    return []


def title_before_name(before):
    """'Chief Financial Officer John Smith' -> 'Chief Financial Officer'."""
    m = re.search(r"((?:[A-Z][\w&'-]*\s+(?:(?:of|and|the|for|&)\s+)*)+)(?:,\s*)?$", before)
    if m:
        title = capture_title(m.group(1))
        if title and title.split()[-1] == m.group(1).split()[-1].rstrip(","):
            return title
    return None


def appositive_title(after):
    """'John Smith, Chief Operating Officer, will retire' -> 'Chief Operating Officer'."""
    m = re.match(r"^\s*,\s*(?:(?:age\s+)?\d{1,3}\s*,\s*)?(?:the |our |its |[A-Z][\w&.]*'s )?", after)
    return capture_title(after[m.end():]) if m else None


def current_title(after):
    """'Art Levinson, current Chair of the Board, ...' -> 'Chair of the Board'."""
    m = re.match(r"^\s*,\s*(?:the Company's |its |our |[A-Z][\w&.]*'s )?current(?:ly)?\s+"
                 r"(?:serving as\s+)?", after)
    return capture_title(after[m.end():]) if m else None


def served_as_title(after):
    """'Kate Adams, who has served as Apple's general counsel since 2017'."""
    m = re.match(r"^\s*,\s*who (?:has |had )?(?:served|serves|currently serves) as\s+", after)
    return capture_title(after[m.end():]) if m else None


SUB_CLAUSE_BREAK = re.compile(r",\s+and\s+|;\s+|,\s+at which time\s+")


def sub_clause(window, position):
    """The part of `window` around `position`, split at ', and' / ';'."""
    starts = [0] + [m.end() for m in SUB_CLAUSE_BREAK.finditer(window) if m.end() <= position]
    ends = [m.start() for m in SUB_CLAUSE_BREAK.finditer(window) if m.start() > position]
    return window[max(starts):(min(ends) if ends else len(window))]


def clause_date(before, after, sentence, defined):
    """Effective date for the event described in this clause.
    Returns (YYYY-MM-DD or None, note or None). Only dates tied to the
    clause's own 'effective ...' phrase or event verb are used."""
    for text in (after, before):
        m = re.search(r"\beffective\b", text, re.I)
        if not m:
            continue
        phrase = text[m.start():]
        for pattern in (EFFECTIVE_DATE_RE, EFFECTIVE_START_ON_RE):
            hit = pattern.match(phrase)
            if hit:
                value = resolve(hit, defined)
                if value:
                    return value, None
                return None, f"defined date '{hit.group('term')}' not found in the filing"
        if EFFECTIVE_IMMEDIATELY_RE.match(phrase):
            start = ON_DATE_START.match(sentence)
            if start:
                return parse_date(start.group(1)), None
            return None, "'effective immediately' with no stated date"
        snippet = re.split(r";|\.\s", phrase)[0][:160]
        note = f"effective date not stated ('{snippet}')"
        if EFFECTIVE_CONDITION_RE.match(phrase):
            anticipated = ANTICIPATED_RE.search(phrase)
            if anticipated:
                note += f"; anticipated date {parse_date(anticipated.group(1))}"
        return None, note

    window = before + " " + after
    for text in (after, before):
        hit = VERB_ON_DATE_RE.search(text)
        if hit:
            value = resolve(hit, defined)
            if value:
                return value, None
    start = ON_DATE_START.match(sentence)
    if start and PAST_EVENT.search(window) and not FUTURE_WORDS.search(window):
        return parse_date(start.group(1)), None
    return None, None


# -----------------------------------------------------------------------------
# Step 5: events
# -----------------------------------------------------------------------------
def group_mentions(sentence, mentions):
    """Group names joined only by ',' / 'and' (ages allowed) so they share the
    verb before the first name and the words after the last one."""
    groups = []
    for m in mentions:
        if groups and CONJUNCTION_ONLY.match(sentence[groups[-1][-1]["end"]:m["start"]]):
            groups[-1].append(m)
        else:
            groups.append([m])
    return groups


def event(kind, title=None, date_=None, note=None, from_title=None):
    return {"type": kind, "title": title, "from_title": from_title, "date": date_, "note": note}


def clause_events(before, after, sentence, defined, single):
    """Events for the person(s) in one clause, plus their known current title."""
    window = before + " ◆ " + after
    known = (current_title(after) or appositive_title(after) or served_as_title(after)) if single else None
    when, note = clause_date(before, after, sentence, defined)

    def date_for(hits):
        """Date from the sub-clause that holds the event word, so in "will
        remain in her current position effective January 31, ..., and will
        separate from employment ... on April 30" the separation gets April 30."""
        if not hits:
            return when, note
        part = sub_clause(window, hits[0].start())
        b, _, a = part.partition("◆") if "◆" in part else ("", "", part)
        value, why = clause_date(b, a, sentence, defined)
        if value is None and why is None:
            return when, note
        return value, why

    # Explicit combined changes for one person -> "both"
    m = CONTINUE_THEN_TRANSITION_RE.search(after)
    if m and single:
        return [event("both", capture_title(m.group("to")), parse_date(m.group("date")),
                      None, capture_title(m.group("from")))], known
    m = TRANSITION_FROM_TO_RE.search(after)
    if m and single:
        return [event("both", capture_title(m.group("to")), when, note,
                      capture_title(m.group("from")))], known

    dep_hits = [] if HYPOTHETICAL_RE.search(sentence) else list(DEPARTURE_RE.finditer(window))
    app_hits = [h for h in APPOINTMENT_RE.finditer(window)
                if not SUCCESSOR_AFTER.match(window[h.end():])]

    def find_titles(hits):
        for hit in hits:
            found = titles_after(window, hit.start())
            if found:
                return found
        return []

    events = []
    dep_title = None
    if dep_hits:
        found = find_titles(dep_hits)
        dep_title = (found[0] if found else None) or \
            ((current_title(after) or appositive_title(after) or title_before_name(before))
             if single else None)
        if dep_title is None and DIRECTOR_HINT.search(after):
            dep_title = "Director"
    app_titles = find_titles(app_hits) if app_hits else []
    if app_hits and not app_titles and DIRECTOR_HINT.search(after):
        app_titles = ["Director"]

    current = current_title(after) if single else None
    dep_when, dep_note = date_for(dep_hits)
    app_when, app_note = date_for(app_hits)
    if dep_hits and app_hits and single:
        # "will step down as CEO and will become Executive Chair"
        both_when = app_when or dep_when
        events.append(event("both", app_titles[0] if app_titles else None, both_when,
                            None if both_when else (app_note or dep_note), dep_title))
        events += [event("appointment", t, app_when, app_note) for t in app_titles[1:]]
    elif app_hits and current and single and app_titles and current not in app_titles:
        # "Art Levinson, current Chair of the Board, will become Lead Independent Director"
        events.append(event("both", app_titles[0], app_when, app_note, current))
        events += [event("appointment", t, app_when, app_note) for t in app_titles[1:]]
    else:
        if dep_hits:
            events.append(event("departure", dep_title, dep_when, dep_note))
        if app_hits:
            events += [event("appointment", t, app_when, app_note) for t in (app_titles or [None])]
    return events, known


def analyze_sentence(sentence, canonical, surname_map, defined):
    """Return (findings, unattributed). findings: list of
    {key, name, surname, events, known, notes}."""
    full = full_name_mentions(sentence)
    for m in full:
        m["name"] = canonical.get(m["name"], m["name"])
    mentions = sorted(full + honorific_mentions(sentence, full), key=lambda m: m["start"])
    if not mentions:
        return [], False

    groups = group_mentions(sentence, mentions)
    findings, object_spans = [], []
    for gi, group in enumerate(groups):
        first, last = group[0], group[-1]
        prev_end = groups[gi - 1][-1]["end"] if gi > 0 else 0
        next_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else len(sentence)

        prefix = re.sub(r"(?:Mr|Ms|Mrs|Dr)\.\s*$", "",
                        sentence[max(0, first["start"] - 40):first["start"]])
        if OBJECT_PREFIX.search(prefix):
            object_spans.append((first["start"] - 40, next_start))
            continue

        # The clause for this person: from the last clause break before the
        # name to the last clause break before the next name.
        before = sentence[prev_end:first["start"]]
        if gi > 0:
            breaks = list(CLAUSE_BREAK.finditer(before))
            if breaks:
                before = before[breaks[-1].end():]
        after = sentence[last["end"]:next_start]
        if gi + 1 < len(groups):
            breaks = list(CLAUSE_BREAK.finditer(after))
            if breaks:
                after = after[:breaks[-1].start()]

        events, known = clause_events(before, after, sentence, defined, len(group) == 1)
        role_end = ROLE_END_RE.search(after)
        for m in group:
            name = m["name"] or surname_map.get(m["surname"])
            notes = []
            if role_end:
                notes.append(f"current role ends {parse_date(role_end.group(1))} "
                             f"('remain in ... current position'); not used as the event date")
            if events or known or notes:
                findings.append({"key": (name or "~" + m["surname"]).lower(), "name": name,
                                 "surname": m["surname"], "known": known, "notes": notes,
                                 "events": [dict(e) for e in events]})

    keyword_spots = [k.start() for k in DEPARTURE_RE.finditer(sentence)] + \
                    [k.start() for k in APPOINTMENT_RE.finditer(sentence)]
    unattributed = (not any(f["events"] for f in findings)
                    and any(not any(a <= p < b for a, b in object_spans) for p in keyword_spots))
    return findings, unattributed


def norm(title):
    return (title or "").lower()


def add_event(person, new):
    """Merge a new clause event into a person's events for this filing.
    - same type and same title (or no title): fill in a missing date/title
    - a different title: a separate, distinct event (its own row)"""
    kinds = {"departure": ("departure", "both"), "appointment": ("appointment", "both"),
             "both": ("both",)}[new["type"]]
    candidates = [e for e in person["events"] if e["type"] in kinds]

    def title_of(e):
        if e["type"] == "both" and new["type"] == "departure":
            return e["from_title"]
        return e["title"]

    if new["title"] is None and new["type"] != "both":
        if candidates:
            target = candidates[0]
            if target["date"] is None and new["date"]:
                target["date"], target["note"] = new["date"], None
            elif target["date"] is None and target["note"] is None:
                target["note"] = new["note"]
            return
    else:
        for e in candidates:
            if norm(title_of(e)) == norm(new["title"]) or title_of(e) is None:
                if title_of(e) is None:
                    e["title"] = new["title"]
                if e["date"] is None and new["date"]:
                    e["date"], e["note"] = new["date"], None
                return
    person["events"].append(new)


def extract_events(section):
    """Return (events, review_notes). Each event is a dict with
    event_type, person_name, title, effective_date."""
    sentences = split_sentences(section)
    canonical, surname_map = build_name_index(sentences)
    defined = defined_dates(section)

    people, order, notes = {}, [], []
    for s in sentences:
        findings, unattributed = analyze_sentence(s, canonical, surname_map, defined)
        if unattributed and re.search(r"\b(?:Mr|Ms|Mrs|Dr)\.|[A-Z][a-z]+ [A-Z][a-z]+", s):
            notes.append(f"event wording but no person identified: {s[:160]}")
        for f in findings:
            if f["key"] not in people:
                people[f["key"]] = {"name": f["name"], "surname": f["surname"],
                                    "events": [], "known": [], "notes": []}
                order.append(f["key"])
            person = people[f["key"]]
            person["name"] = person["name"] or f["name"]
            if f["known"] and f["known"] not in person["known"]:
                person["known"].append(f["known"])
            person["notes"] += [n for n in f["notes"] if n not in person["notes"]]
            for e in f["events"]:
                add_event(person, e)

    events = []
    for key in order:
        person = people[key]
        if not person["events"]:
            continue
        name = person["name"]
        label = name or f"Mr./Ms. {person['surname']}"
        if name is None:
            notes.append(f"could not find a full name for '{label}'")
        for n in person["notes"]:
            notes.append(f"{label}: {n}")
        for e in person["events"]:
            if e["type"] == "both":
                dep = e["from_title"] or (person["known"][0] if person["known"] else None)
                title = f"{dep} -> {e['title']}" if dep and e["title"] and dep != e["title"] \
                    else (e["title"] or dep)
            elif e["type"] == "departure":
                title = e["title"] or (person["known"][0] if person["known"] else None)
            else:
                title = e["title"]
            if e["date"] is None and e["note"]:
                notes.append(f"{label} ({e['type']}): {e['note']}")
            events.append({
                "event_type": e["type"],
                "person_name": name or NOT_FOUND,
                "title": title or NOT_FOUND,
                "effective_date": e["date"] or NOT_FOUND,
            })
    return events, notes


COMPENSATION_RE = re.compile(r"compensat|salary|bonus|equity|award|incentive|severance|"
                             r"retention|agreement|plan\b|stock|vesting", re.I)


# -----------------------------------------------------------------------------
# Step 6: per-company processing
# -----------------------------------------------------------------------------
def process_filing(company, ticker, cik, filing):
    """Return (rows, ok). ok=False means the filing could not be checked."""
    accession, filing_date = filing["accessionNumber"], filing["filingDate"]
    url = (f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/"
           f"{accession.replace('-', '')}/{filing['primaryDocument']}")
    resp = sec_get(url)
    if resp is None:
        print(f"  WARNING: {ticker} {filing_date} ({accession}): primary document "
              f"could not be downloaded; filing skipped")
        return [], False
    try:
        section = item_502_section(html_to_text(resp.content))
        if section is None:
            print(f"  WARNING: {ticker} {filing_date} ({accession}): Item 5.02 section "
                  f"not found in {url}; filing skipped")
            return [], False
        events, notes = extract_events(section)
    except Exception as exc:  # one malformed document should not stop the run
        print(f"  WARNING: {ticker} {filing_date} ({accession}): could not parse ({exc})")
        return [], False

    for note in notes:
        print(f"  REVIEW: {ticker} {filing_date}: {note}")
    if not events:
        reason = ("compensation or plan matters only"
                  if COMPENSATION_RE.search(section) else "no departure or appointment identified")
        print(f"  {ticker} | {filing_date}: Item 5.02 filing has no executive event "
              f"({reason}); no row added")
        return [], True

    rows = []
    for event in events:
        row = {"company": company, "ticker": ticker, "cik": cik, "filing_date": filing_date}
        row.update(event)
        print(f"{ticker} | {filing_date} | {row['event_type']} | "
              f"{row['person_name']} | {row['title']}")
        rows.append(row)
    return rows, True


def process_company(company, ticker, cik, start, end):
    print(f"\n{ticker} ({company}, CIK {cik})")
    submissions = get_json(SUBMISSIONS_URL.format(cik=cik))
    if submissions is None:
        print(f"  WARNING: {ticker}: submissions could not be downloaded; "
              f"executive events were NOT checked for this company")
        return []

    filings, complete = matching_filings(submissions, start, end)
    if not filings:
        if complete:
            print(f"{ticker}: No executive events in past 12 months")
        else:
            print(f"  WARNING: {ticker}: no matching filings found, but part of the filing "
                  f"history could not be downloaded, so the search is incomplete")
        return []

    print(f"  {len(filings)} Item 5.02 filing(s) between {start} and {end}")
    rows, all_checked = [], complete
    for filing in filings:
        filing_rows_, ok = process_filing(company, ticker, cik, filing)
        rows += filing_rows_
        all_checked = all_checked and ok

    if not all_checked:
        print(f"  WARNING: {ticker}: some filings could not be checked; "
              f"results for this company may be incomplete")
    elif not rows:
        print(f"  {ticker}: Item 5.02 filings were found, but none described a "
              f"departure or appointment")
    return rows


def main():
    end = date.today()
    start = one_year_before(end)
    print(f"Looking for Form 8-K Item 5.02 filings dated {start} to {end}.")

    all_rows = []
    for company, ticker, cik in COMPANIES:
        try:
            all_rows.extend(process_company(company, ticker, cik, start, end))
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
