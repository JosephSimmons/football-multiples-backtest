"""Backtester for short-odds multiples (doubles / trebles) on football data.

Staking convention: LEVEL STAKES, 1 point per bet. ROI ("yield") = profit / points staked.
A £20 double is simply a 1-point bet where 1 point = £20; ROI is independent of point size.

Data: Matches.csv from github.com/xgabora/Club-Football-Match-Data-2000-2025
(derived from football-data.co.uk). Odds are pre-match decimal odds.
"""
from __future__ import annotations

from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data" / "Matches.csv"

# (name, odds column at standard price, odds column at best market price, win function)
MARKETS = {
    "home": ("OddHome", "MaxHome"),
    "away": ("OddAway", "MaxAway"),
    "over": ("Over25", "MaxOver25"),
    "under": ("Under25", "MaxUnder25"),
}


def load_matches(path: Path = DATA, divisions: list[str] | None = None) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    d["MatchDate"] = pd.to_datetime(d["MatchDate"])
    d = d.dropna(subset=["FTHome", "FTAway", "FTResult"]).copy()
    if divisions:
        d = d[d["Division"].isin(divisions)].copy()
    d["match_id"] = np.arange(len(d))
    # Season label = year the season started (July cut-over).
    d["season"] = d["MatchDate"].dt.year - (d["MatchDate"].dt.month < 7).astype(int)
    # Betting "round": Tuesday-to-Monday week, so a Fri-Mon weekend stays together.
    d["round"] = (d["MatchDate"] - pd.Timedelta(days=1)).dt.to_period("W-MON").astype(str)
    goals = d["FTHome"] + d["FTAway"]
    d["win_home"] = (d["FTResult"] == "H").astype(int)
    d["win_away"] = (d["FTResult"] == "A").astype(int)
    d["win_over"] = (goals > 2.5).astype(int)
    d["win_under"] = (goals < 2.5).astype(int)
    return d.sort_values("MatchDate").reset_index(drop=True)


def selections(d: pd.DataFrame, lo: float = 1.40, hi: float = 1.60,
               markets: tuple[str, ...] = ("home", "away", "over", "under"),
               price: str = "std", target: float = 1.50) -> pd.DataFrame:
    """Every outcome priced in [lo, hi]. At most ONE selection per match (the one closest
    to `target`), because legs of a multiple must come from different matches.
    price='std' uses the standard bookmaker price, 'max' the best price in the market."""
    frames = []
    for m in markets:
        std, mx = MARKETS[m]
        col = std if price == "std" else mx
        s = d[d[std].between(lo, hi) & d[col].notna()]  # band always defined on std price
        f = s[["match_id", "Division", "MatchDate", "season", "round", "HomeTeam", "AwayTeam",
               "HomeElo", "AwayElo", "Form5Home", "Form5Away"]].copy()
        f["market"] = m
        f["odds"] = s[col].values
        f["band_odds"] = s[std].values
        f["won"] = s[f"win_{m}"].values
        frames.append(f)
    sel = pd.concat(frames, ignore_index=True)
    sel["dist"] = (sel["band_odds"] - target).abs()
    sel = sel.sort_values(["match_id", "dist", "market"]).drop_duplicates("match_id")
    sel["ret"] = sel["odds"] * sel["won"]  # return per 1pt single, stake included
    return sel.drop(columns="dist").sort_values("MatchDate").reset_index(drop=True)


def _esym(r: np.ndarray, k: int) -> float:
    """Elementary symmetric polynomial e_k(r): the summed return of ALL k-fold multiples
    that can be formed from legs with single-returns r (1pt on each multiple)."""
    p1, p2, p3 = r.sum(), (r ** 2).sum(), (r ** 3).sum()
    if k == 1:
        return p1
    if k == 2:
        return (p1 ** 2 - p2) / 2
    if k == 3:
        return (p1 ** 3 - 3 * p1 * p2 + 2 * p3) / 6
    raise ValueError(k)


def round_table(sel: pd.DataFrame, k: int) -> pd.DataFrame:
    """Per betting round: number of k-fold bets available and their total return,
    when 1pt is placed on EVERY possible k-fold within that round."""
    rows = []
    for rnd, g in sel.groupby("round", sort=True):
        n = len(g)
        if n < k:
            continue
        r = g["ret"].to_numpy(float)
        won = g["won"].to_numpy(float)
        rows.append((rnd, g["season"].iloc[0], n, comb(n, k), _esym(r, k), _esym(won, k)))
    t = pd.DataFrame(rows, columns=["round", "season", "legs", "bets", "returned", "wins"])
    t["profit"] = t["returned"] - t["bets"]
    t["round_roi"] = t["profit"] / t["bets"]  # = expected ROI of ONE random k-fold that round
    return t


def summarise(t: pd.DataFrame, n_boot: int = 4000, seed: int = 1) -> dict:
    """Headline numbers + bootstrap 95% CI. Rounds are resampled as blocks because
    multiples inside one round share legs and are not independent."""
    if len(t) == 0:
        return dict(rounds=0, bets=0, strike=np.nan, profit=0.0, roi=np.nan,
                    roi_lo=np.nan, roi_hi=np.nan, p_profit=np.nan,
                    one_per_round_roi=np.nan, opr_lo=np.nan, opr_hi=np.nan, max_dd=np.nan)
    rng = np.random.default_rng(seed)
    b, p, rr = t["bets"].to_numpy(float), t["profit"].to_numpy(float), t["round_roi"].to_numpy(float)
    idx = rng.integers(0, len(t), size=(n_boot, len(t)))
    boot = p[idx].sum(1) / b[idx].sum(1)
    boot_opr = rr[idx].mean(1)
    cum = np.cumsum(p)
    return dict(
        rounds=len(t), bets=int(b.sum()), strike=t["wins"].sum() / b.sum(),
        profit=p.sum(), roi=p.sum() / b.sum(),
        roi_lo=np.quantile(boot, 0.025), roi_hi=np.quantile(boot, 0.975),
        p_profit=(boot > 0).mean(),
        one_per_round_roi=rr.mean(),
        opr_lo=np.quantile(boot_opr, 0.025), opr_hi=np.quantile(boot_opr, 0.975),
        max_dd=(np.maximum.accumulate(cum) - cum).max(),
    )


def backtest(sel: pd.DataFrame, k: int, **kw) -> dict:
    return summarise(round_table(sel, k), **kw)


def punter_paths(sel: pd.DataFrame, k: int, n_paths: int = 5000, n_bets: int | None = None,
                 shuffle: bool = True, seed: int = 7) -> np.ndarray:
    """Realistic punter: ONE random k-fold per round at 1pt. Returns array (n_paths, n_bets)
    of cumulative profit in points. shuffle=True draws each punter's rounds at random from
    history (with replacement), so "after n bets" is not tied to how one particular season
    started; shuffle=False replays history in order."""
    rng = np.random.default_rng(seed)
    groups = [g["ret"].to_numpy(float) for _, g in sel.groupby("round", sort=True) if len(g) >= k]
    width = max(len(g) for g in groups)
    R = np.full((len(groups), width), np.nan)
    for i, g in enumerate(groups):
        R[i, :len(g)] = g
    n_bets = n_bets or len(groups)
    if shuffle:
        which = rng.integers(0, len(groups), size=(n_paths, n_bets))
    else:
        which = np.tile(np.arange(len(groups))[:n_bets], (n_paths, 1))
    key = rng.random((n_paths, n_bets, width))
    rows = R[which]                                   # (paths, bets, width)
    key[np.isnan(rows)] = 2.0                         # never pick padding
    picks = np.argsort(key, axis=2)[:, :, :k]
    legs = np.take_along_axis(rows, picks, axis=2)
    return (legs.prod(2) - 1.0).cumsum(1)


def implied_margin(d: pd.DataFrame) -> pd.Series:
    """Bookmaker overround on the 1X2 market per match."""
    return 1 / d["OddHome"] + 1 / d["OddDraw"] + 1 / d["OddAway"] - 1
