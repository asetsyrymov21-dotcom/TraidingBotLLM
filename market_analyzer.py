# ============================================================
#  Smart Adaptive Trading System — market_analyzer.py
#  Ядро: определение состояния рынка (TREND / FLAT)
#  Индикаторы: EMA50/200, ADX(14), ATR(14)
# ============================================================

import numpy as np
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from config import MarketAnalyzerConfig

logger = logging.getLogger(__name__)


class MarketState(Enum):
    TREND_UP = "TREND_UP"     # Восходящий тренд
    TREND_DOWN = "TREND_DOWN" # Нисходящий тренд
    FLAT = "FLAT"             # Флэт / консолидация
    UNKNOWN = "UNKNOWN"       # Недостаточно данных


@dataclass
class MarketSnapshot:
    """Полный срез состояния рынка"""
    state: MarketState
    close: float
    ema_fast: float           # EMA50
    ema_slow: float           # EMA200
    adx: float
    plus_di: float            # +DI: давление покупателей
    minus_di: float           # -DI: давление продавцов
    atr: float
    atr_pct: float            # ATR в % от цены
    trend_direction: int      # +1 лонг, -1 шорт, 0 нейтрально
    high_volatility: bool     # ATR аномально высокий
    rsi: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    volume: float = 0.0                # Объём последней свечи
    avg_volume: float = 0.0            # Средний объём за N свечей (из конфига)


class MarketAnalyzer:
    """
    Анализирует OHLCV-данные и определяет состояние рынка.
    Возвращает MarketSnapshot с полным набором индикаторов.
    """

    def __init__(self, cfg: MarketAnalyzerConfig, label: str = ""):
        self.cfg = cfg
        # Метка для логов — "alice:BTC/USDT". Позволяет различать логи
        # разных пар в мультипарном режиме.
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
        if len(ohlcv) < self.cfg.ema_slow + 10:
            logger.warning(f"{prefix}Not enough candles: {len(ohlcv)} < {self.cfg.ema_slow + 10}")
            return None

        closes  = np.array([c[4] for c in ohlcv], dtype=float)
        highs   = np.array([c[2] for c in ohlcv], dtype=float)
        lows    = np.array([c[3] for c in ohlcv], dtype=float)
        volumes = np.array([c[5] for c in ohlcv], dtype=float)

        ema_fast_arr = self._ema(closes, self.cfg.ema_fast)
        ema_slow_arr = self._ema(closes, self.cfg.ema_slow)
        ema_fast = ema_fast_arr[-1]
        ema_slow = ema_slow_arr[-1]

        adx_arr, pdi_arr, mdi_arr = self._adx(highs, lows, closes, self.cfg.adx_period)
        adx     = adx_arr[-1]
        plus_di = pdi_arr[-1]
        minus_di = mdi_arr[-1]

        atr_series = self._atr(highs, lows, closes, self.cfg.atr_period)
        atr  = atr_series[-1]
        rsi  = self._rsi(closes, 14)[-1]

        macd_line, macd_signal, _ = self._macd(closes)
        bb_upper, bb_mid, bb_lower = self._bollinger(closes)

        close = closes[-1]
        atr_pct = atr / close

        # Объём последней свечи и средний объём за volume_filter_period свечей
        current_volume = float(volumes[-1])
        vol_period = self.cfg.volume_filter_period
        # Среднее считаем по предыдущим свечам (исключаем текущую, чтобы не было look-ahead)
        avg_vol_window = volumes[-(vol_period + 1):-1] if len(volumes) > vol_period else volumes[:-1]
        avg_volume = float(np.mean(avg_vol_window)) if len(avg_vol_window) > 0 else 0.0

        # Наклон EMA50 за последние 5 свечей (в % от цены)
        ema_fast_slope = (ema_fast_arr[-1] - ema_fast_arr[-6]) / close if len(ema_fast_arr) >= 6 else 0.0

        # ── Определение состояния ──
        state = self._classify_market(
            ema_fast, ema_slow, adx, plus_di, minus_di, ema_fast_slope, close
        )
        trend_dir = 0
        if state == MarketState.TREND_UP:
            trend_dir = 1
        elif state == MarketState.TREND_DOWN:
            trend_dir = -1

        # Аномальная волатильность: ATR > среднего ATR * atr_high_volatility_multiplier
        avg_atr = np.mean(atr_series[-50:]) if len(atr_series) >= 50 else atr
        high_volatility = atr > avg_atr * self.cfg.atr_high_volatility_multiplier

        snapshot = MarketSnapshot(
            state=state,
            close=close,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            adx=adx,
            plus_di=plus_di,
            minus_di=minus_di,
            atr=atr,
            atr_pct=atr_pct,
            trend_direction=trend_dir,
            high_volatility=high_volatility,
            rsi=rsi,
            macd_line=macd_line[-1] if macd_line is not None else None,
            macd_signal=macd_signal[-1] if macd_signal is not None else None,
            bb_upper=bb_upper,
            bb_mid=bb_mid,
            bb_lower=bb_lower,
            volume=current_volume,
            avg_volume=avg_volume,
        )
        logger.info(
            f"{prefix}Market: {state.value} | Close={close:.4f} | "
            f"EMA9={ema_fast:.2f} EMA21={ema_slow:.2f} | "
            f"ADX={adx:.1f} +DI={plus_di:.1f} -DI={minus_di:.1f} | "
            f"ATR={atr:.4f} ({atr_pct*100:.2f}%) | RSI={rsi:.1f} | "
            f"Vol={current_volume:.0f} AvgVol={avg_volume:.0f}"
        )
        return snapshot

    # ──────────────────────────────────────────
    #  Классификация состояния рынка
    # ──────────────────────────────────────────

    def _classify_market(
        self,
        ema_fast: float,
        ema_slow: float,
        adx: float,
        plus_di: float,
        minus_di: float,
        ema_fast_slope: float,
        close: float,
    ) -> MarketState:
        """
        Определяет режим рынка: TREND_UP / TREND_DOWN / FLAT.

        Логика (быстрая, для 15m таймфрейма):
        1. ADX — минимальный фильтр шума (< 15 → FLAT, не торгуем)
        2. EMA9 vs EMA21 crossover — основной сигнал направления.
           Быстро реагирует (9/21 свечи), в отличие от EMA50/200.
        3. Наклон EMA9 — подтверждение что движение реальное, не флуктуация.

        ADX не используется как жёсткий порог тренда — на 15m он часто
        запаздывает. EMA crossover реагирует на 3-5 свечей раньше.
        """
        cfg = self.cfg

        # ── 1. ADX: фильтр минимального шума ──
        # Только отсекаем полный боковик, не требуем "сильный тренд"
        if adx < cfg.adx_flat_threshold:
            return MarketState.FLAT

        # ── 2. EMA9 vs EMA21: основной сигнал ──
        ema_bullish = ema_fast > ema_slow   # EMA9 выше EMA21 → бычий импульс
        ema_bearish = ema_fast < ema_slow   # EMA9 ниже EMA21 → медвежий импульс

        # ── 3. Наклон EMA9 за последние ~5 свечей (подтверждение) ──
        slope_up   = ema_fast_slope >  0.00005   # ослаблен порог для 15m
        slope_down = ema_fast_slope < -0.00005

        # ── 4. Финальное решение ──
        if ema_bullish and slope_up:
            return MarketState.TREND_UP

        if ema_bearish and slope_down:
            return MarketState.TREND_DOWN

        # EMA перекрещены, но наклон не подтверждает — нейтраль
        return MarketState.FLAT

    # ──────────────────────────────────────────
    #  Индикаторы
    # ──────────────────────────────────────────

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        """Экспоненциальная скользящая средняя"""
        result = np.zeros_like(data)
        k = 2.0 / (period + 1)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = data[i] * k + result[i - 1] * (1 - k)
        return result

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
            rs  = np.where(avg_loss == 0, np.inf, np.divide(avg_gain, avg_loss, where=avg_loss != 0, out=np.zeros_like(avg_gain)))
        rsi = np.where(rs == np.inf, 100.0, 100 - (100 / (1 + rs)))
        rsi[:period] = 50.0
        return rsi

    @staticmethod
    def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Average True Range"""
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:]  - closes[:-1]),
            )
        )
        atr = np.zeros(len(closes))
        if len(tr) < period:
            return atr
        atr[period] = np.mean(tr[:period])
        for i in range(period + 1, len(closes)):
            atr[i] = (atr[i-1] * (period - 1) + tr[i-1]) / period
        return atr

    @staticmethod
    def _adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Average Directional Index.
        Возвращает кортеж (adx, +DI, -DI).
        +DI > -DI → преобладают покупатели (up-pressure).
        -DI > +DI → преобладают продавцы  (down-pressure).
        """
        n = len(closes)
        plus_dm  = np.zeros(n)
        minus_dm = np.zeros(n)
        tr       = np.zeros(n)

        for i in range(1, n):
            move_up   = highs[i]  - highs[i-1]
            move_down = lows[i-1] - lows[i]
            plus_dm[i]  = move_up   if move_up > move_down and move_up > 0   else 0
            minus_dm[i] = move_down if move_down > move_up and move_down > 0 else 0
            tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))

        smoothed_plus  = np.zeros(n)
        smoothed_minus = np.zeros(n)
        smoothed_tr    = np.zeros(n)

        smoothed_plus[period]  = np.sum(plus_dm[1:period+1])
        smoothed_minus[period] = np.sum(minus_dm[1:period+1])
        smoothed_tr[period]    = np.sum(tr[1:period+1])

        for i in range(period + 1, n):
            smoothed_plus[i]  = smoothed_plus[i-1]  - smoothed_plus[i-1]/period  + plus_dm[i]
            smoothed_minus[i] = smoothed_minus[i-1] - smoothed_minus[i-1]/period + minus_dm[i]
            smoothed_tr[i]    = smoothed_tr[i-1]    - smoothed_tr[i-1]/period    + tr[i]

        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = np.where(smoothed_tr != 0, 100 * smoothed_plus  / smoothed_tr, 0)
            mdi = np.where(smoothed_tr != 0, 100 * smoothed_minus / smoothed_tr, 0)
            dx  = np.where((pdi + mdi) != 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0)

        adx = np.zeros(n)
        if n > period * 2:
            adx[period*2] = np.mean(dx[period:period*2])
            for i in range(period*2 + 1, n):
                adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period

        return adx, pdi, mdi

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
    def _bollinger(closes: np.ndarray, period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
        """Bollinger Bands — верхняя, средняя, нижняя"""
        if len(closes) < period:
            c = closes[-1]
            return c, c, c
        window = closes[-period:]
        mid    = float(np.mean(window))
        std    = float(np.std(window))
        return mid + std_mult * std, mid, mid - std_mult * std
