"""Download the raw Alpha Vantage data for the 2018-2026 backtest.

Before running, put the paid key in apikey.env:
ALPHA_VANTAGE_API_KEY=your_paid_key

Alpha Vantage does not give a dependable original filing date. We will check
SEC filing dates in a later step before calculating each April 1 ranking.
"""

import csv
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).parent
MEMBERSHIP_FILE = ROOT / "data/raw/sp500_membership/sp500_historical_components.csv"
OUTPUT_FOLDER = ROOT / "data/raw/alpha_vantage"
STATUS_FILE = ROOT / "data/processed/alpha_vantage_download_status.csv"
REPORT_FILE = ROOT / "data/processed/alpha_vantage_coverage.csv"
ALIASES_FILE = ROOT / "data/raw/ticker_aliases.csv"
YEARS = range(2018, 2026)  # Eight portfolios: April 2018 through April 2026
WAIT_SECONDS = 60 / 70  # Stay below the paid plan's 75 requests per minute

ENDPOINTS = {
    "prices": "TIME_SERIES_DAILY_ADJUSTED",
    "income": "INCOME_STATEMENT",
    "balance_sheet": "BALANCE_SHEET",
    "cash_flow": "CASH_FLOW",
    "shares": "SHARES_OUTSTANDING",
}


def get_api_key():
    load_dotenv(ROOT / "apikey.env")
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        raise ValueError("Add ALPHA_VANTAGE_API_KEY to apikey.env.")
    return key


def get_tickers():
    """Return every ticker present at an April 1 rebalance."""
    with MEMBERSHIP_FILE.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    tickers = set()
    for year in YEARS:
        april_1 = datetime(year, 4, 1)
        available_rows = [
            row for row in rows if datetime.strptime(row["date"], "%Y-%m-%d") <= april_1
        ]
        snapshot = available_rows[-1]
        tickers.update(snapshot["tickers"].split(","))

    return sorted(tickers)


def get_aliases():
    """Read manually verified old-ticker replacements, if the file exists."""
    if not ALIASES_FILE.exists():
        return {}
    with ALIASES_FILE.open(encoding="utf-8-sig", newline="") as file:
        return {
            row["historical_ticker"]: row["api_ticker"]
            for row in csv.DictReader(file)
            if row["historical_ticker"] and row["api_ticker"]
        }


def save_json_reports(data, path):
    """Save annual reports; shares are quarterly because no annual list exists."""
    reports = data.get("annualReports", [])
    if not reports:
        reports = next((value for value in data.values() if isinstance(value, list)), [])

    if not reports:
        raise ValueError(data.get("Information") or data.get("Error Message") or data)

    columns = list(dict.fromkeys(key for report in reports for key in report))
    temporary = path.with_suffix(".part")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(reports)
    temporary.replace(path)


def valid_file(path):
    """A completed CSV must have data below its header."""
    if not path.exists():
        return False
    with path.open(encoding="utf-8-sig", errors="ignore") as file:
        return len(file.readlines()) > 1


def download(ticker, api_ticker, folder, function, api_key):
    path = OUTPUT_FOLDER / folder / f"{ticker}.csv"
    if valid_file(path):
        return "already downloaded", False
    path.unlink(missing_ok=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    parameters = {"function": function, "symbol": api_ticker, "apikey": api_key}

    if function == "TIME_SERIES_DAILY_ADJUSTED":
        parameters.update({"datatype": "csv", "outputsize": "full"})

    response = requests.get(
        "https://www.alphavantage.co/query", params=parameters, timeout=60
    )
    response.raise_for_status()

    if function == "TIME_SERIES_DAILY_ADJUSTED":
        if response.text.lstrip().startswith("{"):
            raise ValueError(response.json())
        temporary = path.with_suffix(".part")
        temporary.write_text(response.text, encoding="utf-8")
        temporary.replace(path)
    else:
        save_json_reports(response.json(), path)

    return "downloaded", True


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def make_coverage_report(tickers):
    """Check the exact five fiscal years needed before every rebalance."""
    report = []
    for ticker in tickers:
        for year in YEARS:
            needed_years = {str(value) for value in range(year - 5, year)}
            row = {"ticker": ticker, "rebalance_year": year}
            for folder in ENDPOINTS:
                path = OUTPUT_FOLDER / folder / f"{ticker}.csv"
                if not valid_file(path):
                    row[folder] = "missing"
                elif folder in {"prices", "shares"}:
                    row[folder] = "available"
                else:
                    with path.open(encoding="utf-8-sig", newline="") as file:
                        available = {
                            item.get("fiscalDateEnding", "")[:4]
                            for item in csv.DictReader(file)
                        }
                    missing = sorted(needed_years - available)
                    row[folder] = "complete" if not missing else f"missing {','.join(missing)}"
            report.append(row)
    write_csv(REPORT_FILE, report)


def main():
    api_key = get_api_key()
    tickers = get_tickers()
    aliases = get_aliases()
    total = len(tickers) * len(ENDPOINTS)
    print(f"{len(tickers)} tickers and up to {total} requests.")
    print(f"Estimated minimum time: {total / 70:.0f} minutes.")
    input("Press Enter to begin, or close the program to cancel.")

    number = 0
    status = []
    for ticker in tickers:
        for folder, function in ENDPOINTS.items():
            number += 1
            api_ticker = aliases.get(ticker, ticker)
            try:
                result, requested = download(
                    ticker, api_ticker, folder, function, api_key
                )
                print(f"{number}/{total}: {ticker} {folder} — {result}")
            except Exception as error:
                result, requested = f"FAILED: {error}", True
                print(f"{number}/{total}: {ticker} {folder} — {result}")
            status.append(
                {
                    "historical_ticker": ticker,
                    "api_ticker": api_ticker,
                    "dataset": folder,
                    "result": result,
                }
            )
            write_csv(STATUS_FILE, status)
            if requested:
                time.sleep(WAIT_SECONDS)

    make_coverage_report(tickers)
    print(f"Download report: {STATUS_FILE}")
    print(f"Five-year coverage report: {REPORT_FILE}")


if __name__ == "__main__":
    main()
