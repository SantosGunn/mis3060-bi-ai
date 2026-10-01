"""
Diagnostic only (does not change hw03_executives.py or executive_events.csv).
Re-downloads every Item 5.02 8-K from the past 12 months with the same
User-Agent and code as the pipeline, and saves what the extractor sees:

    hw03/debug_502/<TICKER>_<filing date>_<accession>.txt

Each file holds the primary-document URL, the Item 5.02 section text, the
sentence split, and the events the current code extracts from it.

Run from the repository's main folder:
    python hw03/debug_executive_filings.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw03_executives as x  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "debug_502"


def main():
    OUT_DIR.mkdir(exist_ok=True)
    end = date.today()
    start = x.one_year_before(end)
    saved = 0
    for company, ticker, cik in x.COMPANIES:
        subs = x.get_json(x.SUBMISSIONS_URL.format(cik=cik))
        if subs is None:
            continue
        filings, _ = x.matching_filings(subs, start, end)
        for f in filings:
            url = (f"{x.SEC_BASE}/Archives/edgar/data/{int(cik)}/"
                   f"{f['accessionNumber'].replace('-', '')}/{f['primaryDocument']}")
            resp = x.sec_get(url)
            if resp is None:
                continue
            section = x.item_502_section(x.html_to_text(resp.content)) or "(Item 5.02 section not found)"
            events, notes = x.extract_events(section)
            lines = [f"URL: {url}", f"Filed: {f['filingDate']}", "",
                     "===== ITEM 5.02 SECTION =====", section, "",
                     "===== SENTENCES =====",
                     *[f"[{i}] {s}" for i, s in enumerate(x.split_sentences(section))], "",
                     "===== EXTRACTED EVENTS =====", *[str(e) for e in events],
                     "", "===== REVIEW NOTES =====", *notes]
            name = f"{ticker}_{f['filingDate']}_{f['accessionNumber']}.txt"
            (OUT_DIR / name).write_text("\n".join(lines), encoding="utf-8")
            saved += 1
            print(f"saved {name}")
    print(f"\n{saved} file(s) saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
