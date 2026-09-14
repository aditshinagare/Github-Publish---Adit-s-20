import pandas as pd
from pathlib import Path

winners = pd.read_csv("data/processed/winners_sector.csv")

price_files = Path("data/raw/alpha_vantage/prices").glob("*.csv")
prices = pd.concat(
    (pd.read_csv(file).assign(Ticker=file.stem) for file in price_files),
    ignore_index=True
)
prices["timestamp"] = pd.to_datetime(prices["timestamp"])

prices["adjusted_close"] = pd.to_numeric(
    prices["adjusted_close"], errors="coerce"
)

winners["Buy Date"] = pd.to_datetime(
    winners["Year"].astype(str) + "-04-01"
)

winners["Sell Date"] = winners["Buy Date"] + pd.DateOffset(years=1)

april_prices = prices[
    (prices["timestamp"].dt.month == 4)
    & (prices["timestamp"].dt.day <= 7)
].sort_values("timestamp")

april_prices["Year"] = april_prices["timestamp"].dt.year
april_prices = april_prices.groupby(["Ticker", "Year"])["adjusted_close"].first().reset_index()

winners = winners.merge(
    april_prices.rename(columns={"adjusted_close": "Buy Price"}),
    on=["Ticker", "Year"], how="left"
)

benchmark = april_prices[april_prices["Ticker"] == "SPY"].copy()
benchmark["S&P 500 Return"] = benchmark["adjusted_close"].shift(-1) / benchmark["adjusted_close"] - 1

april_prices["Year"] = april_prices["Year"] - 1

winners = winners.merge(
    april_prices.rename(columns={"adjusted_close": "Sell Price"}),
    on=["Ticker", "Year"], how="left"
)

winners["Stock Return"] = (
    winners["Sell Price"] / winners["Buy Price"] - 1
)

yearly_returns = winners.groupby("Year")["Stock Return"].mean().reset_index()
yearly_returns = yearly_returns.rename(
    columns={"Stock Return": "Strategy Return"}
)

yearly_returns["Strategy Growth"] = (
    1 + yearly_returns["Strategy Return"]
).cumprod()

yearly_returns = yearly_returns.merge(
    benchmark[["Year", "S&P 500 Return"]], on="Year"
)
yearly_returns["S&P 500 Growth"] = (
    1 + yearly_returns["S&P 500 Return"]
).cumprod()

missing = winners[winners[["Buy Price", "Sell Price"]].isna().any(axis=1)]

#calculate daily portfolio returns
spy = prices[prices["Ticker"] == "SPY"].set_index("timestamp")["adjusted_close"].sort_index()
april_dates = spy[(spy.index.month == 4) & (spy.index.day <= 7)].groupby(spy[(spy.index.month == 4) & (spy.index.day <= 7)].index.year).apply(lambda x: x.index[0])
daily_returns = []
for year in winners["Year"].unique():
    tickers = winners.loc[winners["Year"] == year, "Ticker"]
    buy_prices = winners[winners["Year"] == year].set_index("Ticker")["Buy Price"]
    period = prices[
        prices["Ticker"].isin(tickers)
        & prices["timestamp"].between(april_dates[year], april_dates[year + 1])
    ].pivot(index="timestamp", columns="Ticker", values="adjusted_close")
    period = period.reindex(spy.loc[april_dates[year]:april_dates[year + 1]].index).ffill()
    daily_returns.append(period.div(buy_prices).fillna(1).mean(axis=1).pct_change().dropna())

strategy_daily = pd.concat(daily_returns).rename("Strategy Return")
spy_daily = spy.pct_change().loc[strategy_daily.index.min():strategy_daily.index.max()].rename("S&P 500 Return")
daily = pd.concat([strategy_daily, spy_daily], axis=1).dropna()
strategy_growth = (1 + daily["Strategy Return"]).cumprod()
spy_growth = (1 + daily["S&P 500 Return"]).cumprod()

years = len(yearly_returns)
summary = pd.DataFrame({
    "Strategy Total Return": [yearly_returns["Strategy Growth"].iloc[-1] - 1],
    "S&P 500 Total Return": [yearly_returns["S&P 500 Growth"].iloc[-1] - 1],
    "Strategy Annual Return": [yearly_returns["Strategy Growth"].iloc[-1] ** (1 / years) - 1],
    "S&P 500 Annual Return": [yearly_returns["S&P 500 Growth"].iloc[-1] ** (1 / years) - 1],
    "Strategy Volatility": [daily["Strategy Return"].std() * 252 ** 0.5],
    "S&P 500 Volatility": [daily["S&P 500 Return"].std() * 252 ** 0.5],
    "Strategy Sharpe": [daily["Strategy Return"].mean() / daily["Strategy Return"].std() * 252 ** 0.5],
    "S&P 500 Sharpe": [daily["S&P 500 Return"].mean() / daily["S&P 500 Return"].std() * 252 ** 0.5],
    "Strategy Max Drawdown": [(strategy_growth / strategy_growth.cummax() - 1).min()],
    "S&P 500 Max Drawdown": [(spy_growth / spy_growth.cummax() - 1).min()]
})

winners.to_csv("data/processed/backtest_sector_stocks.csv", index=False)
missing.to_csv("data/processed/backtest_sector_missing.csv", index=False)
yearly_returns.to_csv("data/processed/backtest_sector_yearly.csv", index=False)
daily.to_csv("data/processed/backtest_sector_daily.csv")
summary.to_csv("data/processed/backtest_sector_summary.csv", index=False)

print(yearly_returns)
print(summary)
print("Missing price rows:", len(missing))

print(
    winners[winners["Year"] == 2020][
        ["Ticker", "Buy Price", "Sell Price", "Stock Return"]
    ].sort_values("Stock Return", ascending=False)
)
