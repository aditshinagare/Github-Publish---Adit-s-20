# Adit's 20

Adit's 20 is a rule-based stock-selection model that annually ranks eligible S&P 500 companies using fundamental, valuation, growth, financial-safety, and volatility metrics. The project compares three versions of the strategy to study the effects of sector bias.

## Strategy Versions

- `Sversion1_baseline.py`: Ranks companies across the full eligible S&P 500 universe.
- `Sversion2_sector_relative.py`: Ranks each metric within broad sectors.
- `Sversion3_revised_rubric.py`: Uses sector-relative rankings and a redesigned rubric.
- `Sdownload_data.py`: Downloads the required Alpha Vantage data.
- `Sdownload_sec_filings.py`: Downloads and checks SEC filing dates.
- `Sbuild_sector_map.py`: Assigns companies to the project's broad sector groups.
- `Sbacktest.py`: Backtests the selected annual portfolios against SPY.

## Backtest Period

The strategies were tested over eight annual holding periods from April 2018 through April 2026.

## Important Note

An Alpha Vantage API key and separately downloaded data are required to reproduce the complete analysis. Raw Alpha Vantage data are not included in this repository.

## Author

Adit Shinagare