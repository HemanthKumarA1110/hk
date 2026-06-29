"""Scalping engine for NIFTY/BANKNIFTY options with multi-confirmation scoring."""

from __future__ import annotations

from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.scoring import SCALPING_MIN_SCORE, confidence_from_score, score_confirmations
from trading_shared.strategies.ta import add_common_indicators, opening_range
from trading_shared.strategies.types import Confirmation, EngineType, SignalSide, StrategySignalCandidate


class ScalpingEngine:
    TIMEFRAMES = ("1m", "3m", "5m")

    def __init__(self, data: StrategyDataProvider):
        self.data = data

    def evaluate(self) -> list[StrategySignalCandidate]:
        candidates: list[StrategySignalCandidate] = []
        for underlying in ("NIFTY", "BANKNIFTY"):
            chain = self.data.option_chain(underlying) or {}
            indices = self.data.index_tokens()
            if underlying not in indices:
                continue
            token, symbol = indices[underlying]
            for timeframe in self.TIMEFRAMES:
                signal = self._evaluate_underlying(underlying, token, symbol, timeframe, chain)
                if signal:
                    candidates.append(signal)
        return [c for c in candidates if c.score >= SCALPING_MIN_SCORE]

    def _evaluate_underlying(
        self,
        underlying: str,
        token: str,
        symbol: str,
        timeframe: str,
        chain: dict,
    ) -> StrategySignalCandidate | None:
        df = add_common_indicators(self.data.build_intraday_frame(token, symbol, bars=30))
        if len(df) < 5:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]
        or_high, or_low = opening_range(df, bars=min(15, len(df)))
        spot = float(row["close"])
        chain_rows = chain.get("rows") or []
        if isinstance(chain_rows, dict):
            chain_rows = list(chain_rows.values())

        confirmations: list[Confirmation] = [
            Confirmation("orb_breakout", spot > or_high or spot < or_low, 12, f"OR {or_low:.0f}-{or_high:.0f}"),
            Confirmation("vwap_bounce", (row["close"] > row["vwap"] and prev["close"] <= prev["vwap"]) or (row["close"] < row["vwap"] and prev["close"] >= prev["vwap"]), 10),
            Confirmation("vwap_breakout", abs(row["close"] - row["vwap"]) / max(row["vwap"], 1) > 0.001, 8),
            Confirmation("ema_momentum", row["ema9"] > row["ema20"] or row["ema9"] < row["ema20"], 10),
            Confirmation("volume_spike", bool(row.get("vol_spike", False)), 12),
            Confirmation("oi_shift", self._oi_shift(chain_rows, underlying), 14),
            Confirmation("pcr_bias", self._pcr_bias(chain), 8),
            Confirmation("gamma_momentum", self._gamma_momentum(chain_rows), 10),
            Confirmation("liquidity_ok", row["volume"] > 0, 8),
            Confirmation("fake_breakout_filter", not self._fake_breakout(row, prev), 8),
        ]

        score = score_confirmations(confirmations)
        if score < SCALPING_MIN_SCORE:
            return None

        side = SignalSide.BUY if row["ema9"] >= row["ema20"] else SignalSide.SELL
        option_symbol = self._pick_option(chain_rows, underlying, side, spot)
        points = 25 if underlying == "NIFTY" else 40
        if side == SignalSide.BUY:
            stoploss = spot - 12
            target = spot + points
            trail = spot - 8
        else:
            stoploss = spot + 12
            target = spot - points
            trail = spot + 8

        return StrategySignalCandidate(
            engine=EngineType.SCALPING,
            strategy_name="multi_confirmation_scalp",
            symbol=option_symbol or f"{underlying}-OPT",
            token=token,
            side=side,
            entry=round(spot, 2),
            stoploss=round(stoploss, 2),
            targets=[round(target, 2)],
            trailing_stop=round(trail, 2),
            timeframe=timeframe,
            score=score,
            confidence=confidence_from_score(score, confirmations),
            risk_reward=round(abs(target - spot) / max(abs(spot - stoploss), 1), 2),
            confirmations=confirmations,
            metadata={"underlying": underlying, "option_symbol": option_symbol, "points_target": points},
        )

    @staticmethod
    def _oi_shift(rows: list, underlying: str) -> bool:
        if not rows:
            return False
        oi_values = [float(r.get("oi", 0)) for r in rows if r.get("oi")]
        return max(oi_values, default=0) > 0 and len(oi_values) >= 3

    @staticmethod
    def _pcr_bias(chain: dict) -> bool:
        pcr = chain.get("pcr")
        if pcr is None:
            return False
        return pcr > 0.7 or pcr < 1.3

    @staticmethod
    def _gamma_momentum(rows: list) -> bool:
        if len(rows) < 2:
            return False
        return any(float(r.get("volume", 0)) > 0 and float(r.get("oi", 0)) > 0 for r in rows)

    @staticmethod
    def _fake_breakout(row, prev) -> bool:
        return float(row["high"]) > float(prev["high"]) and float(row["close"]) < float(prev["close"])

    @staticmethod
    def _pick_option(rows: list, underlying: str, side: SignalSide, spot: float) -> str | None:
        suffix = "CE" if side == SignalSide.BUY else "PE"
        candidates = [r for r in rows if str(r.get("symbol", "")).endswith(suffix)]
        if not candidates:
            return None
        candidates.sort(key=lambda r: abs(float(r.get("strike", spot)) - spot) if r.get("strike") else 99999)
        best = candidates[0]
        return str(best.get("symbol") or f"{underlying}{suffix}")
