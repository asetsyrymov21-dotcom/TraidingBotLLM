# ============================================================
#  Smart Adaptive Trading System — market_analyzer.py
#  Индикаторы: RSI(14), MACD(12,26,9), Bollinger Bands(20)
#  ADX / EMA / ATR удалены — режим рынка не определяется.
# ============================================================

import numpy as np
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from config import MarketAnalyzerConfig

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """Срез рынка: цена + RSI/MACD/BB + объём + ATR"""
    close: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    rsi: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    volume: float = 0.0       # Объём последней свечи
    avg_volume: float = 0.0   # Средний объём за N свечей
    atr: Optional[float] = None       # Average True Range (14)
    atr_pct: Optional[float] = None   # ATR / цена (волатильность в %)


class MarketAnalyzer:
    """
    Считает RSI, MACD, Bollinger Bands по OHLCV-данным.
    Режим рынка (TREND/FLAT) больше не определяется —
    переключение торговли управляется через SL/Win-Loss систему.
    """

    def __init__(self, cfg: MarketAnalyzerConfig, label: str = ""):
        self.cfg = cfg
        self.label = label

    # ──────────────────────────────────────────
    #  Публичный интерфейс
    # ──────────────────────────────────────────

    def analyze(self, ohlcv: List) -> Optional[MarketSnapshot]:
        """
        Принимает список свечей OHLCV (от CCXT).
        Каждая свеча: [timestamp, open, high, low, close, volume]
        """
        prefix = f"[{self.label}] " if self.label else ""
        if len(ohlcv) < 40:
            logger.warning(f"{prefix}Not enough candles: {len(ohlcv)} < 40")
            return None

        opens   = np.array([c[1] for c in ohlcv], dtype=float)
        highs   = np.array([c[2] for c in ohlcv], dtype=float)
        lows    = np.array([c[3] for c in ohlcv], dtype=float)
        closes  = np.array([c[4] for c in ohlcv], dtype=float)
        volumes = np.array([c[5] for c in ohlcv], dtype=float)

        rsi  = self._rsi(closes, 14)[-1]
        macd_line, macd_signal, _ = self._macd(closes)
        bb_upper, bb_mid, bb_lower = self._bollinger(closes)
        ema_fast = self._ema(closes, 9)[-1]
        ema_slow = self._ema(closes, 21)[-1]

        open_ = opens[-1]
        high = highs[-1]
        low = lows[-1]
        close = closes[-1]

        # ATR (волатильность)
        atr_val = self._atr(ohlcv, period=14)
        atr_pct = (atr_val / close) if close > 0 else 0.0

        # Объём текущей свечи и средний объём
        current_volume = float(volumes[-1])
        vol_period = self.cfg.volume_filter_period
        avg_vol_window = volumes[-(vol_period + 1):-1] if len(volumes) > vol_period else volumes[:-1]
        avg_volume = float(np.mean(avg_vol_window)) if len(avg_vol_window) > 0 else 0.0

        snapshot = MarketSnapshot(
            open=open_,
            high=high,
            low=low,
            close=close,
            rsi=rsi,
            macd_line=macd_line[-1] if macd_line is not None else None,
            macd_signal=macd_signal[-1] if macd_signal is not None else None,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            bb_upper=bb_upper,
            bb_mid=bb_mid,
            bb_lower=bb_lower,
            volume=current_volume,
            avg_volume=avg_volume,
            atr=atr_val,
            atr_pct=atr_pct,
        )
        logger.info(
            f"{prefix}OHLC={open_:.4f}/{high:.4f}/{low:.4f}/{close:.4f} | RSI={rsi:.1f} | "
            f"MACD={snapshot.macd_line:.6f} Sig={snapshot.macd_signal:.6f} | "
            f"EMA9={ema_fast:.4f} EMA21={ema_slow:.4f} | "
            f"BB [{bb_lower:.4f} / {bb_mid:.4f} / {bb_upper:.4f}] | "
            f"ATR={atr_val:.4f} ({atr_pct*100:.3f}%) | "
            f"Vol={current_volume:.0f} AvgVol={avg_volume:.0f}"
        )
        return snapshot

    # ──────────────────────────────────────────
    #  Индикаторы
    # ──────────────────────────────────────────

    @staticmethod
    def _ema(closes: np.ndarray, period: int) -> np.ndarray:
        """EMA"""
        ema = np.zeros_like(closes)
        ema[0] = closes[0]
        k = 2.0 / (period + 1)
        for i in range(1, len(closes)):
            ema[i] = closes[i] * k + ema[i - 1] * (1 - k)
        return ema

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
        """RSI"""
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.zeros(len(closes))
        avg_loss = np.zeros(len(closes))

        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])

        for i in range(period + 1, len(closes)):
            avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period

        with np.errstate(divide="ignore", invalid="ignore"):
            rs = np.where(
                avg_loss == 0, np.inf,
                np.divide(avg_gain, avg_loss, where=avg_loss != 0, out=np.zeros_like(avg_gain))
            )
        rsi = np.where(rs == np.inf, 100.0, 100 - (100 / (1 + rs)))
        rsi[:period] = 50.0
        return rsi

    @staticmethod
    def _macd(closes: np.ndarray, fast=12, slow=26, signal=9) -> Tuple:
        """MACD линия, сигнальная линия, гистограмма"""
        k_fast = 2.0 / (fast + 1)
        k_slow = 2.0 / (slow + 1)
        k_sig  = 2.0 / (signal + 1)

        ema_f = np.zeros_like(closes)
        ema_s = np.zeros_like(closes)
        ema_f[0] = ema_s[0] = closes[0]

        for i in range(1, len(closes)):
            ema_f[i] = closes[i] * k_fast + ema_f[i-1] * (1 - k_fast)
            ema_s[i] = closes[i] * k_slow + ema_s[i-1] * (1 - k_slow)

        macd_line = ema_f - ema_s
        sig = np.zeros_like(macd_line)
        sig[0] = macd_line[0]
        for i in range(1, len(macd_line)):
            sig[i] = macd_line[i] * k_sig + sig[i-1] * (1 - k_sig)

        hist = macd_line - sig
        return macd_line, sig, hist

    @staticmethod
    def _atr(ohlcv: List, period: int = 14) -> float:
        """Average True Range (Wilder's smoothing)"""
        if len(ohlcv) < period + 1:
            return 0.0
        highs  = [c[2] for c in ohlcv]
        lows   = [c[3] for c in ohlcv]
        closes = [c[4] for c in ohlcv]
        tr_list = []
        for i in range(1, len(ohlcv)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i]  - closes[i - 1]),
            )
            tr_list.append(tr)
        if len(tr_list) < period:
            return float(np.mean(tr_list)) if tr_list else 0.0
        atr = float(np.mean(tr_list[:period]))
        k = 1.0 / period
        for tr in tr_list[period:]:
            atr = tr * k + atr * (1 - k)
        return atr

    @staticmethod
    def _bollinger(closes: np.ndarray, period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
        """Bollinger Bands — верхняя, средняя, нижняя"""
        if len(closes) < period:
            c = closes[-1]
            return c, c, c
        window = closes[-period:]
        mid    = float(np.mean(window))
        std    = float(np.std(window))
        return mid + std_mult * std, mid, mid - std_mult * std
