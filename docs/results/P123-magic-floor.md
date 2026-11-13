# P123 — Magic Formula as a buy floor (S103)

**Decision.** The user adopted the Magic Formula on 2026-11-13 (phase Q rule 2, S103) as an
`exclusion`: an IDN candidate in the bottom fifth of the combined EY + ROC rank gets no new
money. It blocks buys only: never a trim or a sell of a held name, never the thesis or
take-profit. Lynch (board replay t 4.56) was **not** adopted, because its replay reads today's
IDX-IC industries on past dates (look-ahead in its cyclical class).

**Replay check.** The dividend_value replay, as the screen runs it (`replay_panel` with the S88
bank F floor), before and after taking out the names that the Magic Formula's own
`replay_panel` puts in its bottom fifth at that quarter end (point in time: `LAG_DAYS` 120
fundamentals, gates on that date, delisted names included). Financials are never in the Magic
universe, so they are never taken out. idx-method store as of 2026-11-13.

| | t | p | control t | scored quarters | mean pool (min–max) | verdict |
|---|---|---|---|---|---|---|
| before | 3.00 | 0.003 | 0.06 | 37 | 67.4 (37–100) | passed |
| after the floor | **3.31** | 0.002 | 0.03 | 37 | 66.5 (36–98) | passed |

33 of 2,492 name-quarters are taken out. The edge gets slightly stronger and the control stays
clean, so the floor does not fit noise in the screen it guards.

**Method** (run once with `ASSIST_SIBLINGS_ROOT` pointing at the siblings, about 18 s):

```python
ctx = framework_board.LiveContext(day)
data = ctx.dividend_data
banks = {s for s, r in ctx.table.items() if r.get("car")}
panel = dv.replay_panel(data.bars, data.quarters, data.dividends, banks,
                        bank_f=dv.replay_bank_f(data, banks))
qends = [q for q, _ in panel]
liq = mf.history_liquidity(ctx.stocks.history(), qends)
mpanel = mf.replay_panel(data.bars, data.quarters, data.dividends, ctx.universe, qends,
                         banks=sorted(banks), liquidity=liq)
bottom = {q: {x["symbol"] for x in recs if x["position"] > len(recs) - len(recs) // 5}
          for q, recs in mpanel}
after = [(q, [r for r in recs if r["symbol"] not in bottom[q]]) for q, recs in panel]
dv.evaluate_replay(panel), dv.evaluate_replay(after)
```

**Live today.** Main's last `out/candidates/IDN.json` has 7 candidate names: 2 top, 1 middle,
4 n/a (BBNI, BBRI, BFIN, BMRI, financials), none in the bottom fifth. Nothing is blocked today.
