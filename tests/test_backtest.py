import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import backtest as bt  # noqa: E402


def _sel(rets, rnd="r1"):
    rets = np.asarray(rets, float)
    return pd.DataFrame({"round": rnd, "season": 2020, "ret": rets, "won": (rets > 0).astype(int)})


def test_esym_matches_brute_force():
    rng = np.random.default_rng(0)
    r = rng.choice([0, 1.45, 1.5, 1.57], size=9)
    for k in (1, 2, 3):
        brute = sum(np.prod(c) for c in itertools.combinations(r, k))
        assert abs(bt._esym(r, k) - brute) < 1e-9


def test_double_settlement_by_hand():
    # legs: 1.5 win, 1.6 win, 1.4 lose -> doubles: 2.4 win, 0, 0 -> returned 2.4 on 3pts
    t = bt.round_table(_sel([1.5, 1.6, 0.0]), 2)
    assert t.bets.iloc[0] == 3 and abs(t.returned.iloc[0] - 2.4) < 1e-12
    assert abs(t.profit.iloc[0] - (-0.6)) < 1e-12 and t.wins.iloc[0] == 1


def test_treble_and_short_rounds():
    t = bt.round_table(_sel([1.5, 1.5, 1.5]), 3)
    assert t.bets.iloc[0] == 1 and abs(t.returned.iloc[0] - 3.375) < 1e-12
    assert len(bt.round_table(_sel([1.5, 1.5]), 3)) == 0


def test_fair_odds_give_zero_roi_and_margin_compounds():
    # Simulate: true p = 1/1.5 ; fair odds 1.5 -> ROI ~ 0 ; odds 1.5*0.95 -> double ROI ~ 0.95^2-1
    rng = np.random.default_rng(3)
    frames = []
    for i in range(4000):
        won = rng.random(6) < 1 / 1.5
        frames.append(pd.DataFrame({"round": f"r{i}", "season": 2020, "won": won.astype(int)}))
    s = pd.concat(frames)
    s["ret"] = 1.5 * s.won
    assert abs(bt.backtest(s, 2, n_boot=200)["roi"]) < 0.02
    s["ret"] = 1.5 * 0.95 * s.won
    assert abs(bt.backtest(s, 2, n_boot=200)["roi"] - (0.95 ** 2 - 1)) < 0.02
    assert abs(bt.backtest(s, 3, n_boot=200)["roi"] - (0.95 ** 3 - 1)) < 0.025


def test_one_selection_per_match_and_band():
    d = bt.load_matches(divisions=["E0"])
    s = bt.selections(d)
    assert s.match_id.is_unique
    assert s.band_odds.between(1.40, 1.60).all()
    # settlement cross-check on raw data
    m = d.set_index("match_id")
    h = s[s.market == "home"]
    assert (h.won.values == (m.loc[h.match_id, "FTResult"] == "H").values).all()
    o = s[s.market == "over"]
    assert (o.won.values == ((m.loc[o.match_id, "FTHome"] + m.loc[o.match_id, "FTAway"]) >= 3).values).all()


def test_punter_paths_mean_matches_exact():
    d = bt.load_matches(divisions=["E0"])
    s = bt.selections(d)
    exact = bt.round_table(s, 2)["round_roi"].sum()
    mc = bt.punter_paths(s, 2, n_paths=4000, shuffle=False)[:, -1].mean()
    assert abs(mc - exact) < 3.0  # points, over ~700 rounds
    sh = bt.punter_paths(s, 2, n_paths=4000, n_bets=50)
    assert sh.shape == (4000, 50) and np.isfinite(sh).all()
