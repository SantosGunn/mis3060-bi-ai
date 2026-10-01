"""
Diagnostic only (does not change hw03_earnings.py or earnings_history.csv).
Downloads Walmart's most recent Item 2.02 earnings press release with the
same SEC User-Agent and conversion code the pipeline uses, then shows:
  1. the exhibit URL
  2. the first 3,000 characters of the converted plain text (tables included)
  3. the prose-only text identify_release() actually searches
  4. every quarter/period-looking phrase in the full text vs. the prose

Run from the repository's main folder:
    python hw03/debug_wmt_release.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw03_earnings as h  # noqa: E402  (reuses HEADERS, sec_get, html_to_text, ...)

CIK, TICKER = "0000104169", "WMT"
OUT_TEXT = Path(__file__).resolve().parent / "wmt_latest_release.txt"


def main():
    print(f"User-Agent: {h.HEADERS['User-Agent']}")
    resp = h.sec_get(h.SUBMISSIONS_URL.format(cik=CIK))
    if resp is None:
        return
    candidates = h.earnings_candidates(resp.json())
    if not candidates:
        print("No Item 2.02 8-K filings found.")
        return
    filing = candidates[0]
    print(f"Most recent Item 2.02 8-K: {filing['accession']} filed {filing['filing_date']}")

    url = h.find_press_release(CIK, filing["accession"])
    print(f"Exhibit URL: {url}")
    if url is None:
        return
    exhibit = h.sec_get(url)
    if exhibit is None:
        return

    text = h.html_to_text(exhibit.content)
    OUT_TEXT.write_text(text, encoding="utf-8")

    print("\n" + "=" * 30 + " FIRST 3,000 CHARACTERS (full text, tables included) " + "=" * 30)
    print(text[:3000])

    prose, tables = h.split_blocks(text)
    lead = h.flat(prose)[:h.PERIOD_SEARCH_CHARS]
    print("\n" + "=" * 30 + " WHAT identify_release() SEARCHES (prose only, flattened, "
          f"first {h.PERIOD_SEARCH_CHARS} chars) " + "=" * 30)
    print(lead)

    print("\n" + "=" * 30 + " PERIOD CHECKS " + "=" * 30)
    print(f"Tables found: {len(tables)}")
    print(f"find_periods() hits in prose lead : {h.find_periods(lead)}")
    print(f"find_periods() hits in full text  : {h.find_periods(h.flat(text))[:10]}")
    print(f"END_DATE_RE hits in prose lead    : {h.find_end_dates(lead)}")
    loose = re.compile(r"[^\n]{0,40}(?:\bQ[1-4]\b|\bFY\s?'?\d{2,4}\b|quarter|"
                       r"three months|weeks ended)[^\n]{0,40}", re.I)
    print("\nAny line fragment mentioning Q1-Q4 / FY / quarter / three months "
          "(first 25, full text):")
    for m in list(loose.finditer(text))[:25]:
        print(f"  {m.group(0)!r}")

    print(f"\nFull converted text saved to {OUT_TEXT}")


if __name__ == "__main__":
    main()
