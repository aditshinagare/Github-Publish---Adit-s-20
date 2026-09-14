import pandas as pd
from pathlib import Path

#pull data
income_files = Path("data/raw/alpha_vantage/income").glob("*.csv")
balance_sheet_files = Path("data/raw/alpha_vantage/balance_sheet").glob("*.csv")
cash_flow_files = Path("data/raw/alpha_vantage/cash_flow").glob("*.csv")
prices_files = Path("data/raw/alpha_vantage/prices").glob("*.csv")

income = pd.concat((pd.read_csv(file).assign(Ticker=file.stem) for file in income_files), ignore_index=True)
balance_sheet = pd.concat((pd.read_csv(file).assign(Ticker=file.stem) for file in balance_sheet_files), ignore_index=True)
cash_flow = pd.concat((pd.read_csv(file).assign(Ticker=file.stem) for file in cash_flow_files), ignore_index=True)
prices = pd.concat((pd.read_csv(file).assign(Ticker=file.stem) for file in prices_files), ignore_index=True)

income = income[["Ticker", "fiscalDateEnding", "grossProfit", "totalRevenue", "operatingIncome", "incomeBeforeTax", "incomeTaxExpense", "netIncome", "ebit", "ebitda"]]
balance_sheet = balance_sheet[["Ticker", "fiscalDateEnding", "totalAssets", "cashAndCashEquivalentsAtCarryingValue", "shortLongTermDebtTotal", "totalShareholderEquity", "commonStockSharesOutstanding"]]
cash_flow = cash_flow[["Ticker", "fiscalDateEnding", "operatingCashflow", "capitalExpenditures"]]
data = income.merge(balance_sheet).merge(cash_flow)

#use only reports filed before each April 1
ticker_map = pd.read_csv("data/processed/ticker_cik_map.csv", dtype={"cik": str})
filing_files = Path("data/raw/sec_filings").glob("*.csv")
filings = pd.concat((pd.read_csv(file, dtype={"cik": str}) for file in filing_files), ignore_index=True)
filings = filings[filings["form"] == "10-K"].merge(ticker_map[["ticker", "cik"]], on="cik")
filings["Report Year"] = pd.to_datetime(filings["report_date"]).dt.year
filings["filing_date"] = pd.to_datetime(filings["filing_date"])
filings = filings.sort_values("filing_date").drop_duplicates(["ticker", "Report Year"])

data["Report Year"] = pd.to_datetime(data["fiscalDateEnding"]).dt.year
data = data.merge(filings[["ticker", "Report Year", "filing_date"]], left_on=["Ticker", "Report Year"], right_on=["ticker", "Report Year"])
data = data.drop(columns="ticker")
data["Year"] = data["filing_date"].dt.year + (data["filing_date"].dt.month >= 4)
data = data.sort_values("filing_date").drop_duplicates(["Ticker", "Year"], keep="last")

#rename the downloaded fields to match the formulas
data = data.rename(columns={
    "grossProfit": "Gross Profit", "totalRevenue": "Revenue", "operatingIncome": "Operating Income",
    "incomeBeforeTax": "Income Before Tax", "incomeTaxExpense": "Income Tax Expense",
    "netIncome": "Net Income", "ebit": "EBIT", "ebitda": "EBITDA",
    "totalAssets": "Total Assets", "cashAndCashEquivalentsAtCarryingValue": "Cash",
    "shortLongTermDebtTotal": "Total Debt", "totalShareholderEquity": "Total Equity",
    "commonStockSharesOutstanding": "Shares Outstanding",
    "operatingCashflow": "Operating Cash Flow", "capitalExpenditures": "Capital Expenditures"
})
numbers = data.columns.difference(["Ticker", "ticker", "fiscalDateEnding", "filing_date"])
data[numbers] = data[numbers].apply(pd.to_numeric, errors="coerce")

#prepare the last March price and the previous year's volatility
prices["Date"] = pd.to_datetime(prices["timestamp"])
prices["Adjusted Close"] = pd.to_numeric(prices["adjusted_close"], errors="coerce")
prices = prices.sort_values(["Ticker", "Date"])
prices["Daily Return"] = prices.groupby("Ticker")["Adjusted Close"].pct_change()
prices["Year"] = prices["Date"].dt.year + (prices["Date"].dt.month >= 4)
volatility = (prices.groupby(["Ticker", "Year"])["Daily Return"].std() * 252 ** 0.5).rename("volatility")
march = prices[(prices["Date"].dt.month == 3) & (prices["Date"].dt.day >= 25)].copy()
march["Year"] = march["Date"].dt.year
march_prices = march.groupby(["Ticker", "Year"])["Adjusted Close"].last().rename("Price")
data = data.merge(volatility, on=["Ticker", "Year"]).merge(march_prices, on=["Ticker", "Year"])

#sort before calculating each company's lookback periods
data = data.sort_values(["Ticker", "Year"])
company = data.groupby("Ticker")

#calculate metrics
tax_rate = (data["Income Tax Expense"] / data["Income Before Tax"]).clip(0, 1)
net_debt = data["Total Debt"] - data["Cash"]
invested_capital = data["Total Debt"] + data["Total Equity"] - data["Cash"]
average_invested_capital = (invested_capital + invested_capital.groupby(data["Ticker"]).shift(1)) / 2
market_cap = data["Price"] * data["Shares Outstanding"]
enterprise_value = market_cap + net_debt
free_cash_flow = data["Operating Cash Flow"] - data["Capital Expenditures"]

roic = data["Operating Income"] * (1 - tax_rate) / average_invested_capital
data["median_roic_5y"] = roic.groupby(data["Ticker"]).transform(lambda x: x.rolling(5).median())

average_assets = (data["Total Assets"] + company["Total Assets"].shift(1)) / 2
data["gross_profitability"] = data["Gross Profit"] / average_assets
accrual_ratio = (data["Net Income"] - data["Operating Cash Flow"]) / average_assets
data["accrual_ratio_3y"] = accrual_ratio.groupby(data["Ticker"]).transform(lambda x: x.rolling(3).mean())

old_revenue = company["Revenue"].shift(3)
data["revenue_cagr_3y"] = (data["Revenue"] / old_revenue) ** (1 / 3) - 1
operating_margin = data["Operating Income"] / data["Revenue"]
data["operating_margin_change_3y"] = operating_margin - operating_margin.groupby(data["Ticker"]).shift(3)

data["net_debt_to_ebitda"] = (net_debt / data["EBITDA"]).where(data["EBITDA"] > 0, float("inf")).where(data["EBITDA"].notna())
data["ebit_yield"] = data["EBIT"] / enterprise_value
data["fcf_yield"] = free_cash_flow / market_cap

#keep companies that were actually in the S&P 500
membership = pd.read_csv("data/raw/sp500_membership/sp500_historical_components.csv")
membership["date"] = pd.to_datetime(membership["date"])
members = []
for year in range(2018, 2026):
    tickers = membership.loc[membership["date"] <= f"{year}-04-01", "tickers"].iloc[-1].split(",")
    members += [(ticker, year) for ticker in tickers]
data = data.merge(pd.DataFrame(members, columns=["Ticker", "Year"]))

sectors = pd.read_csv("data/processed/ticker_sectors.csv")
data = data.merge(sectors[["Ticker", "Sector"]], on="Ticker")

#rank companies on each metric (some metrics higher is better, some lower is better)
data["Score1"] = data.groupby(["Year", "Sector"])["median_roic_5y"].rank(pct=True)
data["Score2"] = data.groupby(["Year", "Sector"])["gross_profitability"].rank(pct=True)
data["Score3"] = data.groupby(["Year", "Sector"])["accrual_ratio_3y"].rank(pct=True, ascending=False)
data["Score4"] = data.groupby(["Year", "Sector"])["revenue_cagr_3y"].rank(pct=True)
data["Score5"] = data.groupby(["Year", "Sector"])["operating_margin_change_3y"].rank(pct=True)
data["Score6"] = data.groupby(["Year", "Sector"])["net_debt_to_ebitda"].rank(pct=True, ascending=False)
data["Score7"] = data.groupby(["Year", "Sector"])["ebit_yield"].rank(pct=True)
data["Score8"] = data.groupby(["Year", "Sector"])["fcf_yield"].rank(pct=True)
data["Score9"] = data.groupby(["Year", "Sector"])["volatility"].rank(pct=True, ascending=False)

#turn ranks into percentiles, multiply by each metric's weight, then add them
data["Ticker_Score"] = (
    data["Score1"] * 0.15
    + data["Score2"] * 0.10
    + data["Score3"] * 0.10
    + data["Score4"] * 0.10
    + data["Score5"] * 0.10
    + data["Score6"] * 0.15
    + data["Score7"] * 0.125
    + data["Score8"] * 0.125
    + data["Score9"] * 0.05
)

#rank total scores -> pick top 20 to invest in
data["Ticker_Rank"] = data.groupby("Year")["Ticker_Score"].rank(ascending=False)
companies = pd.read_csv("data/processed/ticker_sectors.csv", dtype={"CIK": str}).drop_duplicates("Ticker").set_index("Ticker")["CIK"]
company = data["Ticker"].map(companies).fillna(data["Ticker"])
top_20 = data.assign(Company=company).sort_values(["Year", "Ticker_Rank"]).drop_duplicates(["Year", "Company"]).groupby("Year").head(20).index
data["Top_20"]=data.index.isin(top_20)
print(data[["Ticker", "Year", "Sector", "Ticker_Score", "Ticker_Rank", "Top_20"]].sort_values(["Year", "Ticker_Rank"]))
    #what is printed is not rlly important

#save to csv
winners = data[data["Top_20"]].sort_values(["Year", "Ticker_Rank"])
winners.to_csv("data/processed/winners_sector.csv", index=False)

#TIPS: 
    # One step at a time, 
    # I write most of the code myself, 
    # Less lines is better
