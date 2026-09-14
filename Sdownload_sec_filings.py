"""Map historical tickers and check which SEC annual reports existed by April 1."""

import csv
import os
import re
import time
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).parent
MEMBERSHIP = ROOT / "data/raw/sp500_membership/sp500_historical_components.csv"
ALIASES = ROOT / "data/raw/ticker_aliases.csv"
HISTORICAL_CIKS = ROOT / "data/raw/historical_ticker_cik.csv"
LISTINGS = ROOT / "data/raw/alpha_vantage/listing_status"
SEC_FOLDER = ROOT / "data/raw/sec_filings"
MAP_REPORT = ROOT / "data/processed/ticker_cik_map.csv"
COVERAGE_REPORT = ROOT / "data/processed/sec_filing_coverage.csv"
YEARS = range(2018, 2026)
SEC_WAIT = 0.2  # Five requests/second; the SEC permits no more than ten.


def read_csv(path, delimiter=","):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file, delimiter=delimiter))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def universe():
    rows = read_csv(MEMBERSHIP)
    yearly, tickers = {}, set()
    for year in YEARS:
        april = datetime(year, 4, 1)
        snapshot = [
            row for row in rows if datetime.strptime(row["date"], "%Y-%m-%d") <= april
        ][-1]
        yearly[year] = snapshot["tickers"].split(",")
        tickers.update(yearly[year])
    return yearly, sorted(tickers)


def normalize(name):
    name = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace("&", " AND "))
    remove = r"\b(THE|INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|PLC|LTD|LIMITED|DE)\b"
    return re.sub(r"\s+", " ", re.sub(remove, " ", name)).strip()


def download_listings(api_key):
    LISTINGS.mkdir(parents=True, exist_ok=True)
    names = {}
    for year in YEARS:
        path = LISTINGS / f"{year}.csv"
        if not path.exists():
            response = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "LISTING_STATUS",
                    "date": f"{year}-04-01",
                    "state": "active",
                    "apikey": api_key,
                },
                timeout=60,
            )
            response.raise_for_status()
            path.write_text(response.text, encoding="utf-8")
        for row in read_csv(path):
            names.setdefault(row["symbol"], row["name"])
    return names


def local_name_map():
    names = {}
    folder = ROOT / "data/raw/sec_sic/quarterly_submissions"
    for path in folder.glob("*_sub.txt"):
        for row in read_csv(path, "\t"):
            for name in (row.get("name", ""), row.get("former", "")):
                key = normalize(name)
                if key:
                    names.setdefault(key, set()).add(str(row["cik"]).zfill(10))
    return names


def build_mapping(tickers, listing_names, headers):
    current = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=headers,
        timeout=60,
    ).json()
    current = {
        row["ticker"]: str(row["cik_str"]).zfill(10)
        for row in current.values()
    }
    aliases = {
        row["historical_ticker"]: row["api_ticker"] for row in read_csv(ALIASES)
    }
    historical = {row["ticker"]: row["cik"] for row in read_csv(HISTORICAL_CIKS)}
    name_map = local_name_map()
    known_names = list(name_map)
    results = []

    for ticker in tickers:
        api_ticker = aliases.get(ticker, ticker)
        company_name = listing_names.get(ticker, "")
        cik, method = "", "unmatched"

        if company_name:
            matches = name_map.get(normalize(company_name), set())
            if len(matches) == 1:
                cik, method = next(iter(matches)), "exact historical name"

        if not cik:
            cik = current.get(api_ticker) or current.get(ticker)
            if cik:
                method = "current ticker"

        if not cik and company_name:
            close = get_close_matches(normalize(company_name), known_names, n=1, cutoff=0.96)
            matches = name_map.get(close[0], set()) if close else set()
            if len(matches) == 1:
                cik, method = next(iter(matches)), "close historical name"

        if not cik and ticker in historical:
            cik, method = historical[ticker], "verified historical CIK"

        results.append(
            {
                "ticker": ticker,
                "api_ticker": api_ticker,
                "company_name": company_name,
                "cik": cik or "",
                "match_method": method if cik else "unmatched",
            }
        )
    write_csv(MAP_REPORT, results)
    return results


def request_json(url, headers):
    for attempt in range(3):
        response = requests.get(url, headers=headers, timeout=60)
        if response.ok:
            time.sleep(SEC_WAIT)
            return response.json()
        time.sleep(2 ** attempt)
    raise RuntimeError(f"SEC request failed: {response.status_code}")


def download_filings(mapping, headers):
    SEC_FOLDER.mkdir(parents=True, exist_ok=True)
    for number, cik in enumerate(sorted({row["cik"] for row in mapping if row["cik"]}), 1):
        path = SEC_FOLDER / f"CIK{cik}.csv"
        old_rows = read_csv(path) if path.exists() else []
        old_reports = {
            row["report_date"]
            for row in old_rows
            if row["filing_date"] < "2018-04-01"
        }
        if len(old_reports) >= 5:
            continue
        data = request_json(f"https://data.sec.gov/submissions/CIK{cik}.json", headers)
        rows = []

        filing_sets = [data["filings"]["recent"]]
        for old_file in data["filings"]["files"]:
            filing_sets.append(
                request_json(
                    f"https://data.sec.gov/submissions/{old_file['name']}", headers
                )
            )

        for filings in filing_sets:
            for index, form in enumerate(filings["form"]):
                if form in {"10-K", "10-K/A"}:
                    rows.append(
                        {
                            "cik": cik,
                            "company": data["name"],
                            "form": form,
                            "report_date": filings["reportDate"][index],
                            "filing_date": filings["filingDate"][index],
                            "accession_number": filings["accessionNumber"][index],
                            "primary_document": filings["primaryDocument"][index],
                        }
                    )
        write_csv(path, rows)
        print(f"{number}: downloaded SEC filings for {data['name']}")


def check_coverage(yearly, mapping):
    ciks = {row["ticker"]: row["cik"] for row in mapping}
    report = []
    for year, tickers in yearly.items():
        april = datetime(year, 4, 1)
        for ticker in tickers:
            cik = ciks.get(ticker, "")
            path = SEC_FOLDER / f"CIK{cik}.csv"
            filings = read_csv(path) if cik and path.exists() else []
            available = {
                row["report_date"]
                for row in filings
                if row["report_date"]
                and datetime.strptime(row["filing_date"], "%Y-%m-%d") < april
            }
            report.append(
                {
                    "ticker": ticker,
                    "rebalance_date": f"{year}-04-01",
                    "cik": cik,
                    "annual_reports_available": len(available),
                    "five_year_lookback": "complete" if len(available) >= 5 else "incomplete",
                    "latest_allowed_report": max(available) if available else "",
                }
            )
    write_csv(COVERAGE_REPORT, report)


def main():
    load_dotenv(ROOT / "apikey.env")
    load_dotenv(ROOT / "sec.env")
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    email = os.getenv("SEC_CONTACT_EMAIL")
    if not api_key or not email:
        raise ValueError("API key or SEC contact email is missing.")

    headers = {"User-Agent": f"SukeshInvestmentProject/1.0 {email}"}
    yearly, tickers = universe()
    listing_names = download_listings(api_key)
    mapping = build_mapping(tickers, listing_names, headers)
    print(f"Mapped {sum(bool(row['cik']) for row in mapping)} of {len(mapping)} tickers.")
    download_filings(mapping, headers)
    check_coverage(yearly, mapping)
    print(f"Ticker map: {MAP_REPORT}")
    print(f"SEC coverage: {COVERAGE_REPORT}")


if __name__ == "__main__":
    main()
