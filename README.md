# football-multiples-backtest

Backtests the "combine 2-3 short-priced (~1.5) outcomes into a double/treble" theory on the Premier
League and 37 other leagues, 2005-2026. Verdict and numbers: [REPORT.md](REPORT.md).

## Run

```
pip install -r requirements.txt
./fetch_data.sh          # 45 MB CSV into data/
python -m pytest -q tests
python src/run.py        # ~20s; writes results/tables.md, CSVs and charts
```

## Layout

- `src/backtest.py`: loading, leg selection, exact settlement of every k-fold per round, block-bootstrap CIs, punter simulation.
- `src/run.py`: all experiments (headline, markets, odds bands, seasons, best price, all leagues, punter simulation, train/test filter study).
- `tests/`: settlement maths checked by hand and by brute force; simulated fair/margined books recover the known ROI.

## Method notes

- Level stakes, 1pt per bet. ROI = profit / points staked.
- Legs: home, away, over 2.5, under 2.5 priced in a band (default 1.40-1.60), one per match.
- Rounds run Tuesday to Monday. All k-folds within a round are settled exactly using elementary
  symmetric polynomials rather than enumerated, which is what makes 44m trebles instant.
- Confidence intervals resample whole rounds, because multiples in a round share legs.
- To test a new idea, add a mask in `filters()` in `src/run.py`; it is automatically judged out-of-sample.

Data: github.com/xgabora/Club-Football-Match-Data-2000-2025 (from football-data.co.uk).
