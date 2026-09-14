import pandas as pd
from pathlib import Path


mapping = pd.read_csv("data/processed/ticker_cik_map.csv", dtype={"cik": str})
files = Path("data/raw/sec_sic/quarterly_submissions").glob("*_sub.txt")
sic = pd.concat(
    (
        pd.read_csv(file, sep="\t", usecols=["cik", "sic"], dtype=str)
        .assign(Period=file.stem[:6])
        for file in files
    ),
    ignore_index=True
)
sic["cik"] = sic["cik"].str.zfill(10)
sic["sic"] = pd.to_numeric(sic["sic"], errors="coerce")
sic = sic.dropna().sort_values("Period").drop_duplicates("cik", keep="last")
mapping = mapping.merge(sic[["cik", "sic"]], on="cik", how="left")


def sector(code):
    if pd.isna(code):
        return "Unclassified"
    code = int(code)
    if 6500 <= code <= 6599 or code == 6798:
        return "Real Estate"
    if 6000 <= code <= 6799:
        return "Financials"
    if 4900 <= code <= 4999:
        return "Utilities"
    if 1300 <= code <= 1399 or 2900 <= code <= 2999 or code in {3533, 4612, 5171, 5172}:
        return "Energy"
    if 2830 <= code <= 2836 or 3840 <= code <= 3851 or code in {5047, 5122} or 8000 <= code <= 8099 or code == 8731:
        return "Healthcare"
    if 2710 <= code <= 2749 or 4810 <= code <= 4899 or 7310 <= code <= 7319 or 7810 <= code <= 7849:
        return "Communications"
    if 3570 <= code <= 3579 or 3660 <= code <= 3699 or 3810 <= code <= 3829 or 7370 <= code <= 7379:
        return "Technology"
    if 1000 <= code <= 1299 or 2400 <= code <= 2499 or 2600 <= code <= 2699 or 2800 <= code <= 2899 or 3000 <= code <= 3099 or 3200 <= code <= 3399:
        return "Materials"
    if code < 1000 or 2000 <= code <= 2399 or 2500 <= code <= 2599 or 3100 <= code <= 3199 or 3710 <= code <= 3719 or 5000 <= code <= 5999 or 7000 <= code <= 7299 or 7500 <= code <= 7999:
        return "Consumer"
    return "Industrials"


mapping["Sector"] = mapping["sic"].apply(sector)

overrides = {
    "GOOG": "Communications", "GOOGL": "Communications", "META": "Communications",
    "FB": "Communications", "NFLX": "Communications", "DIS": "Communications",
    "CMCSA": "Communications", "CHTR": "Communications", "T": "Communications",
    "VZ": "Communications", "TMUS": "Communications", "PARA": "Communications",
    "CBS": "Communications", "VIAB": "Communications", "DISCA": "Communications",
    "DISCK": "Communications", "WBD": "Communications", "FOX": "Communications",
    "FOXA": "Communications", "NWS": "Communications", "NWSA": "Communications",
    "EA": "Communications", "TTWO": "Communications", "ATVI": "Communications",
    "MTCH": "Communications", "OMC": "Communications", "IPG": "Communications",
    "V": "Financials", "MA": "Financials", "PYPL": "Financials",
    "FIS": "Financials", "FI": "Financials", "FISV": "Financials",
    "GPN": "Financials", "FRC": "Financials", "SBNY": "Financials",
    "AMZN": "Consumer", "TSLA": "Consumer"
}
mapping["Method"] = "SEC SIC"
for ticker, value in overrides.items():
    mapping.loc[mapping["ticker"] == ticker, ["Sector", "Method"]] = [value, "Broad business override"]

mapping = mapping.rename(columns={
    "ticker": "Ticker", "company_name": "Company", "cik": "CIK", "sic": "SIC"
})
mapping[["Ticker", "Company", "CIK", "SIC", "Sector", "Method"]].to_csv(
    "data/processed/ticker_sectors.csv", index=False
)
