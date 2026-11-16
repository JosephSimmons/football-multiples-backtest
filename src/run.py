"""Run every experiment and write results/ (tables.md, CSVs, charts).  Usage: python src/run.py"""
from __future__ import annotations

import itertools
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import backtest as bt

OUT = Path(__file__).resolve().parent.parent / "results"
OUT.mkdir(exist_ok=True)
FIRST_SEASON = 2005          # first season with over/under odds
TRAIN_END = 2017             # filters are discovered on seasons <= 2017, judged on 2018+
KS = {1: "single", 2: "double", 3: "treble"}
md: list[str] = []


def emit(title: str, df: pd.DataFrame, name: str, note: str = ""):
    df.to_csv(OUT / f"{name}.csv", index=False)
    md.append(f"## {title}\n\n{note}\n\n{df.to_markdown(index=False)}\n")
    print(f"\n=== {title}\n{df.to_string(index=False)}")


def row(label, sel, k, **extra):
    s = bt.backtest(sel, k)
    return {**extra, "set": label, "bet": KS[k], "legs": len(sel), "bets": s["bets"],
            "strike%": round(100 * s["strike"], 1), "profit_pts": round(s["profit"], 1),
            "ROI%": round(100 * s["roi"], 2),
            "ROI 95% CI": f"{100*s['roi_lo']:.1f} to {100*s['roi_hi']:.1f}",
            "1-per-round ROI%": round(100 * s["one_per_round_roi"], 2),
            "max_drawdown_pts": round(s["max_dd"], 1)}


def table(sets: dict[str, pd.DataFrame], ks=(1, 2, 3)) -> pd.DataFrame:
    return pd.DataFrame([row(lbl, s, k) for lbl, s in sets.items() for k in ks])


# ------------------------------------------------------------------ data
allm = bt.load_matches()
allm = allm[allm.season >= FIRST_SEASON]
epl = allm[allm.Division == "E0"]
sel = bt.selections(epl)
sel_all = bt.selections(allm)
m = bt.implied_margin(epl).mean()
md.append(f"# Results tables\n\nPremier League matches: {len(epl):,} (seasons {epl.season.min()}-{epl.season.max()}), "
          f"legs priced 1.40-1.60: {len(sel):,}. All leagues: {len(allm):,} matches, {len(sel_all):,} legs.\n\n"
          f"Average 1X2 bookmaker margin (PL): {100*m:.1f}%. "
          f"Theory if legs were priced fairly before margin: single {100*(1/(1+m)-1):.1f}%, "
          f"double {100*((1/(1+m))**2-1):.1f}%, treble {100*((1/(1+m))**3-1):.1f}%.\n")

# ------------------------------------------------------------------ 1. headline
emit("1. Headline: every possible bet, Premier League, legs 1.40-1.60",
     table({"PL all markets": sel}), "01_headline",
     "1pt on every single / every possible double / every possible treble within each Tue-Mon round. "
     "'1-per-round ROI' weights each round equally (one random multiple a week).")

# ------------------------------------------------------------------ 2. by market
sets = {mk: bt.selections(epl, markets=(mk,)) for mk in bt.MARKETS}
sets["match result only"] = bt.selections(epl, markets=("home", "away"))
sets["goals only"] = bt.selections(epl, markets=("over", "under"))
emit("2. By market (PL)", table(sets, ks=(1, 2)), "02_by_market")

# ------------------------------------------------------------------ 3. odds bands
bands = [(1.2, 1.3), (1.3, 1.4), (1.4, 1.5), (1.5, 1.6), (1.6, 1.7), (1.7, 1.85), (1.85, 2.1)]
emit("3. By odds band (PL)", table({f"{lo:.2f}-{hi:.2f}": bt.selections(epl, lo, hi, target=(lo+hi)/2)
                                    for lo, hi in bands}, ks=(1, 2)), "03_odds_bands")
emit("3b. By odds band (all leagues)",
     table({f"{lo:.2f}-{hi:.2f}": bt.selections(allm, lo, hi, target=(lo+hi)/2) for lo, hi in bands}, ks=(1, 2)),
     "03b_odds_bands_all")

# ------------------------------------------------------------------ 4. by season
rt = bt.round_table(sel, 2)
by = rt.groupby("season").agg(bets=("bets", "sum"), profit_pts=("profit", "sum")).reset_index()
by["ROI%"] = (100 * by.profit_pts / by.bets).round(1)
by["profit_pts"] = by.profit_pts.round(1)
emit("4. Doubles by season (PL)", by, "04_by_season",
     f"Profitable seasons: {(by.profit_pts > 0).sum()} of {len(by)}.")

# ------------------------------------------------------------------ 5. best price
emit("5. Standard price vs best price in the market",
     table({"PL standard price": sel, "PL best available price": bt.selections(epl, price="max"),
            "ALL leagues standard price": sel_all,
            "ALL leagues best available price": bt.selections(allm, price="max")}), "05_best_price",
     "Best price = highest odds across all tracked bookmakers. An upper bound: you rarely get it on every leg, "
     "and winning accounts get limited.")

# ------------------------------------------------------------------ 6. scale: all leagues
sets = {"ALL leagues": sel_all}
big = allm.Division.value_counts()
for dv in ["E0", "E1", "SP1", "D1", "I1", "F1", "N1", "P1", "SC0"]:
    if dv in big.index:
        sets[dv] = sel_all[sel_all.Division == dv]
emit("6. Industrial scale: all leagues in the dataset", table(sets, ks=(1, 2)), "06_all_leagues",
     "Rows per league form multiples only within that league. 'ALL leagues' forms every cross-league multiple.")
emit("6b. All leagues, singles/doubles/trebles", table({"ALL leagues": sel_all}), "06b_all_leagues_k")

# ------------------------------------------------------------------ 7. the realistic punter
rows = []
paths = {}
for k in (1, 2, 3):
    p = bt.punter_paths(sel, k, n_paths=3000, n_bets=500)
    paths[k] = p
    for n in (10, 20, 50, 100, 200, 500):
        c = p[:, n - 1]
        rows.append({"bet": KS[k], "after_n_bets": n, "chance_in_profit%": round(100 * (c > 0).mean(), 1),
                     "median_pts": round(float(np.median(c)), 1),
                     "5th_pct": round(float(np.quantile(c, .05)), 1),
                     "95th_pct": round(float(np.quantile(c, .95)), 1)})
emit("7. One random bet per round at 1pt (PL, 3,000 simulated punters)", pd.DataFrame(rows), "07_punter",
     "Each simulated punter draws random rounds from PL history and one random bet in each. "
     "Shows how often you would be 'up' after n bets even though the long-run expectation is negative.")

# ------------------------------------------------------------------ 8. contextual filters (train / test)
def add_context(s: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    sign = np.where(s.market == "home", 1, np.where(s.market == "away", -1, np.nan))
    s["elo_gap"] = sign * (s.HomeElo - s.AwayElo)          # favourite's Elo lead (match-result legs)
    s["form_gap"] = sign * (s.Form5Home - s.Form5Away)     # favourite's 5-game form lead
    s["month"] = s.MatchDate.dt.month
    return s


def filters(s: pd.DataFrame) -> dict[str, pd.Series]:
    f = {"(none)": pd.Series(True, index=s.index)}
    for mk in bt.MARKETS:
        f[f"market={mk}"] = s.market == mk
    f["odds 1.40-1.50"] = s.band_odds < 1.50
    f["odds 1.50-1.60"] = s.band_odds >= 1.50
    f["elo lead <150"] = s.elo_gap < 150
    f["elo lead 150-300"] = s.elo_gap.between(150, 300)
    f["elo lead >300"] = s.elo_gap > 300
    f["fav in better form (+3)"] = s.form_gap >= 3
    f["fav in worse form (<=0)"] = s.form_gap <= 0
    f["Aug-Oct"] = s.month.isin([8, 9, 10])
    f["Nov-Jan"] = s.month.isin([11, 12, 1])
    f["Feb-May"] = s.month.isin([2, 3, 4, 5])
    return f


def filter_study(s: pd.DataFrame, label: str, min_legs: int):
    s = add_context(s)
    f = filters(s)
    names = list(f)
    combos = [(a,) for a in names] + [c for c in itertools.combinations(names[1:], 2)]
    rows = []
    for c in combos:
        mask = np.logical_and.reduce([f[n].to_numpy(bool) for n in c])
        tr, te = s[mask & (s.season <= TRAIN_END)], s[mask & (s.season > TRAIN_END)]
        if len(tr) < min_legs or len(te) < min_legs // 2:
            continue
        a, b = bt.backtest(tr, 2, n_boot=300), bt.backtest(te, 2, n_boot=1500)
        rows.append({"filter": " & ".join(c), "train_legs": len(tr), "train_single_ROI%": round(100*(tr.ret.mean()-1), 1),
                     "train_double_ROI%": round(100*a["roi"], 1), "test_legs": len(te),
                     "test_single_ROI%": round(100*(te.ret.mean()-1), 1),
                     "test_double_ROI%": round(100*b["roi"], 1),
                     "test 95% CI": f"{100*b['roi_lo']:.0f} to {100*b['roi_hi']:.0f}"})
    r = pd.DataFrame(rows).sort_values("train_double_ROI%", ascending=False)
    top = r.head(10)
    corr = np.corrcoef(r["train_double_ROI%"], r["test_double_ROI%"])[0, 1]
    emit(f"8. Contextual filters, {label}: top 10 on train (<= {TRAIN_END}) and how they did on test ({TRAIN_END+1}+)",
         top, f"08_filters_{label.replace(' ', '_')}",
         f"{len(r)} filters tried. Positive on train: {(r['train_double_ROI%']>0).sum()}. "
         f"Positive on BOTH train and test: {((r['train_double_ROI%']>0)&(r['test_double_ROI%']>0)).sum()}. "
         f"Train/test ROI correlation across filters: {corr:.2f}. "
         f"Mean test double ROI of the train top 10: {top['test_double_ROI%'].mean():.1f}%.")
    r.to_csv(OUT / f"08_filters_{label.replace(' ', '_')}_all.csv", index=False)
    return r


fr_pl = filter_study(sel, "PL", 80)
fr_all = filter_study(sel_all, "all leagues", 1500)

# ------------------------------------------------------------------ charts
plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9})
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
for k, c in zip((1, 2, 3), ("#4c72b0", "#c44e52", "#8172b2")):
    t = bt.round_table(sel, k)
    ax[0].plot(pd.PeriodIndex(t["round"].str[:10], freq="D").to_timestamp(), t.profit.cumsum(), color=c,
               label=f"every {KS[k]} ({int(t.bets.sum()):,} bets)")
ax[0].axhline(0, color="k", lw=.6); ax[0].legend(frameon=False)
ax[0].set_title("Premier League: cumulative profit, 1pt on every possible bet"); ax[0].set_ylabel("points")
p = paths[2]
x = np.arange(1, p.shape[1] + 1)
for q, a in ((0.05, .15), (0.25, .3)):
    ax[1].fill_between(x, np.quantile(p, q, 0), np.quantile(p, 1 - q, 0), color="#c44e52", alpha=a, lw=0)
ax[1].plot(x, np.median(p, 0), color="#c44e52", label="median punter")
for i in range(4):
    ax[1].plot(x, p[i], color="grey", lw=.5, alpha=.7)
ax[1].axhline(0, color="k", lw=.6); ax[1].legend(frameon=False)
ax[1].set_title("One random double per round at 1pt (3,000 simulated punters)")
ax[1].set_xlabel("doubles placed"); ax[1].set_ylabel("points")
fig.tight_layout(); fig.savefig(OUT / "chart_cumulative.png"); plt.close(fig)

fig, ax = plt.subplots(1, 2, figsize=(11, 4))
b3 = pd.read_csv(OUT / "03b_odds_bands_all.csv")
for bet, c in (("single", "#4c72b0"), ("double", "#c44e52")):
    g = b3[b3.bet == bet]
    ax[0].bar(np.arange(len(g)) + (0.2 if bet == "double" else -0.2), g["ROI%"], 0.4, color=c, label=bet)
ax[0].set_xticks(range(len(g))); ax[0].set_xticklabels(g["set"], rotation=30)
ax[0].axhline(0, color="k", lw=.6); ax[0].legend(frameon=False)
ax[0].set_title("ROI by leg odds band, all leagues"); ax[0].set_ylabel("ROI %")
ax[1].scatter(fr_all["train_double_ROI%"], fr_all["test_double_ROI%"], s=12, color="#4c72b0", label="all leagues")
ax[1].scatter(fr_pl["train_double_ROI%"], fr_pl["test_double_ROI%"], s=12, color="#dd8452", alpha=.6, label="PL only")
ax[1].axhline(0, color="k", lw=.6); ax[1].axvline(0, color="k", lw=.6); ax[1].legend(frameon=False)
ax[1].set_title("Filters: doubles ROI when discovered vs afterwards")
ax[1].set_xlabel(f"train ROI % (<= {TRAIN_END})"); ax[1].set_ylabel(f"test ROI % ({TRAIN_END+1}+)")
fig.tight_layout(); fig.savefig(OUT / "chart_bands_filters.png"); plt.close(fig)

(OUT / "tables.md").write_text("\n".join(md))
print("\nwritten:", sorted(x.name for x in OUT.iterdir()))
