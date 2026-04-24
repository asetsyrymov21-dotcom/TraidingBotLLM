# ============================================================
#  Smart Adaptive Trading System — entry_strategy.py
#  Бот умного входа: RSI + MACD + Bollinger Bands
#
#  Логика:
#  1. ПЕРВЫЙ ВХОД — только при 2/3 или 3/3 совпадении индикаторов
#     (RSI > 50, MACD выше сигнала, цена выше BB midband)
#  2. ПОСЛЕ WIN — продолжаем в том же направлении (немедленно)
#  3. ПОСЛЕ LOSS — переворот в противоположную сторону (немедленно)
#  4. Экстренный стоп при -15% против позиции (если SL не сработал)
# ============================================================

import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict

from typing import TYPE_CHECKING

from config import EntryBotConfig
from exchange import ExchangeConnector
from market_analyzer import MarketSnapshot, MarketState

if TYPE_CHECKING:
    from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


@dataclass
class EntrySignal:
    side: str
    rsi_signal: bool
    macd_signal: bool
    bb_signal: bool
    confidence: int  # Количество совпавших сигналов (0–3)
    reason: str


@dataclass
class EntryPosition:
    side: str
    entry_price: float
    amount: float
    tp_price: float
    sl_price: float


class EntryStrategy:
    """
    Бот умного входа с Win/Loss системой.

    Первый вход — только по 3 индикаторам (RSI + MACD + BB).
    После WIN → та же сторона (немедленно).
    После LOSS → переворот (немедленно).
    Экстренное закрытие при -15% против позиции.
    """

    def __init__(self, exchange: ExchangeConnector, cfg: EntryBotConfig,
                 notifier: Optional['TelegramNotifier'] = None, user_id: str = "",
                 symbol: str = ""):
        self.exchange = exchange
        self.cfg = cfg
        self.symbol = symbol
        self._tag = f"[ENTRY:{symbol}]" if symbol else "[ENTRY]"
        self.position: Optional[EntryPosition] = None
        self._prev_macd_diff: Optional[float] = None
        self.notifier = notifier
        self.user_id = user_id

        # Win/Loss система
        self.last_side: str = ""          # Сторона последней завершённой сделки
        self.last_result: str = "NONE"    # "NONE" | "WIN" | "LOSS"
        self.win_streak: int = 0
        self.loss_streak: int = 0
        self.pause_candles_left: int = 0  # Задержка после убытка (в тиках)
        self.paused_until: float = 0.0    # Пауза при серии убытков

        # Статистика
        self.total_pnl: float = 0.0
        self.trade_count: int = 0
        self.win_count: int = 0

    # ──────────────────────────────────────────
    #  Основной цикл
    # ──────────────────────────────────────────

    def tick(self, snapshot: MarketSnapshot) -> Dict:
        result = {"action": "none", "side": None, "pnl": 0.0, "reason": ""}

        logger.info(
            f"{self._tag} tick | price={snapshot.close:.4f} "
            f"state={getattr(snapshot.state, 'value', snapshot.state)} "
            f"has_position={self.position is not None} "
            f"last_result={self.last_result}"
        )

        # ── Управление открытой позицией ──
        if self.position:
            return self._manage_position(snapshot)

        # ── Пауза при серии убытков (10+) ──
        if self.paused_until > time.time():
            remaining = int(self.paused_until - time.time())
            result["reason"] = f"pause_active ({remaining}s left)"
            logger.info(f"{self._tag} skip | {result['reason']}")
            return result

        # ── Задержка 1 тик после убытка ──
        if self.pause_candles_left > 0:
            self.pause_candles_left -= 1
            result["reason"] = f"delay_after_loss ({self.pause_candles_left} left)"
            logger.info(f"{self._tag} skip | {result['reason']}")
            return result

        # ── ПЕРВЫЙ ВХОД: по 3 индикаторам, только в тренде ──
        if self.last_result == "NONE":
            if snapshot.state not in (MarketState.TREND_UP, MarketState.TREND_DOWN):
                result["reason"] = "not_trending (first_entry_requires_trend)"
                logger.info(f"{self._tag} skip | {result['reason']}")
                return result

            signal = self._analyze_signal(snapshot)
            logger.info(
                f"{self._tag} first_entry signal | side={signal.side} "
                f"conf={signal.confidence} reason={signal.reason}"
            )

            if signal.confidence < 2:
                result["reason"] = f"signal_weak ({signal.confidence}/3): {signal.reason}"
                logger.info(f"{self._tag} skip | {result['reason']}")
                return result

            return self._open_position(snapshot, signal)

        # ── WIN → продолжаем в том же направлении ──
        if self.last_result == "WIN":
            if snapshot.state not in (MarketState.TREND_UP, MarketState.TREND_DOWN):
                result["reason"] = "not_trending (win_continue_requires_trend)"
                logger.info(f"{self._tag} skip | {result['reason']}")
                return result
            direction = self.last_side
            logger.info(f"{self._tag} WIN continuation → {direction.upper()}")
            return self._open_in_direction(snapshot, direction, "win_continue")

        # ── LOSS → переворот ──
        if snapshot.state not in (MarketState.TREND_UP, MarketState.TREND_DOWN):
            result["reason"] = "not_trending (loss_reverse_requires_trend)"
            logger.info(f"{self._tag} skip | {result['reason']}")
            return result
        direction = "short" if self.last_side == "long" else "long"
        logger.info(f"{self._tag} LOSS reversal → {direction.upper()} (was {self.last_side})")
        return self._open_in_direction(snapshot, direction, "loss_reverse")

    # ──────────────────────────────────────────
    #  Управление позицией
    # ──────────────────────────────────────────

    def _manage_position(self, snapshot: MarketSnapshot) -> Dict:
        pos = self.position
        price = snapshot.close

        # ── Экстренный сквиз -15% (если SL не сработал) ──
        emergency_pct = getattr(self.cfg, 'emergency_squeeze_pct', 0.15)
        if pos.side == "long":
            drop = (pos.entry_price - price) / pos.entry_price
            if drop >= emergency_pct:
                logger.warning(
                    f"{self._tag} EMERGENCY SQUEEZE! LONG drop={drop*100:.1f}% >= {emergency_pct*100:.0f}%"
                )
                return self._do_close(price, "emergency_squeeze")
        else:
            rise = (price - pos.entry_price) / pos.entry_price
            if rise >= emergency_pct:
                logger.warning(
                    f"{self._tag} EMERGENCY SQUEEZE! SHORT rise={rise*100:.1f}% >= {emergency_pct*100:.0f}%"
                )
                return self._do_close(price, "emergency_squeeze")

        # ── TP ──
        hit_tp = (pos.side == "long" and price >= pos.tp_price) or (
            pos.side == "short" and price <= pos.tp_price
        )
        if hit_tp:
            return self._do_close(price, "tp")

        # ── SL ──
        hit_sl = (pos.side == "long" and price <= pos.sl_price) or (
            pos.side == "short" and price >= pos.sl_price
        )
        if hit_sl:
            return self._do_close(price, "sl")

        return {"action": "hold", "side": pos.side, "pnl": 0.0, "reason": ""}

    def _do_close(self, price: float, reason: str) -> Dict:
        """Закрывает позицию и обновляет Win/Loss состояние."""
        pos = self.position
        close_side = "sell" if pos.side == "long" else "buy"
        self.exchange.place_market_order(close_side, pos.amount, reduce_only=True)

        # Расчёт PnL
        if pos.side == "long":
            pnl = (price - pos.entry_price) * pos.amount
        else:
            pnl = (pos.entry_price - price) * pos.amount

        self.total_pnl += pnl
        is_win = pnl > 0

        # ── Обновление Win/Loss состояния ──
        self.last_side = pos.side
        if reason == "tp" or (reason not in ("sl", "emergency_squeeze") and is_win):
            self.last_result = "WIN"
            self.win_streak += 1
            self.loss_streak = 0
            if is_win:
                self.win_count += 1
        else:
            self.last_result = "LOSS"
            self.loss_streak += 1
            self.win_streak = 0
            self.pause_candles_left = 1  # Пауза 1 тик после убытка

            # Серия 10+ убытков → пауза 20 минут
            if self.loss_streak >= 10:
                pause_secs = 20 * 60
                self.paused_until = time.time() + pause_secs
                logger.warning(
                    f"{self._tag} Loss streak {self.loss_streak}! "
                    f"Pausing {pause_secs // 60} minutes."
                )

        logger.info(
            f"{self._tag} CLOSE {pos.side.upper()} @ {price:.4f} | "
            f"PnL={pnl:+.4f} | Reason={reason} | "
            f"WinStreak={self.win_streak} LossStreak={self.loss_streak}"
        )

        # Telegram: позиция закрыта
        if self.notifier:
            self.notifier.notify_entry_close(
                self.user_id, pos.side, pos.entry_price, price, pnl, reason,
                win_streak=self.win_streak,
                loss_streak=self.loss_streak,
                symbol=self.symbol,
            )

        self.position = None
        return {"action": f"close_{reason}", "pnl": pnl, "reason": reason, "side": pos.side}

    def _open_in_direction(self, snapshot: MarketSnapshot, direction: str, reason: str) -> Dict:
        """
        Открывает позицию в заданном направлении без проверки индикаторов.
        Используется для win/loss продолжения/переворота.
        """
        price = snapshot.close
        amount = self.exchange.calc_position_size(self.cfg.position_pct, price)

        if amount <= 0:
            logger.warning(f"{self._tag} skip open | reason=insufficient_balance")
            return {"action": "none", "reason": "insufficient_balance", "pnl": 0.0}

        order = self.exchange.place_market_order(direction, amount)
        if not order:
            logger.warning(f"{self._tag} skip open | reason=order_failed ({reason})")
            if self.notifier:
                self.notifier.notify_order_failed(
                    self.user_id, "WIN/LOSS", direction, price,
                    "place_market_order вернул None — проверь API-ключи и баланс"
                )
            return {"action": "none", "reason": "order_failed", "pnl": 0.0}

        if direction == "long":
            tp = price * (1 + self.cfg.tp_pct)
            sl = price * (1 - self.cfg.sl_pct)
        else:
            tp = price * (1 - self.cfg.tp_pct)
            sl = price * (1 + self.cfg.sl_pct)

        self.position = EntryPosition(
            side=direction,
            entry_price=price,
            amount=amount,
            tp_price=tp,
            sl_price=sl,
        )
        self.trade_count += 1

        logger.info(
            f"{self._tag} OPEN {direction.upper()} @ {price:.4f} | "
            f"TP={tp:.4f} SL={sl:.4f} | Reason={reason} | "
            f"Amount={amount}"
        )

        # Telegram: открыта позиция (win/loss)
        if self.notifier:
            self.notifier.notify_winloss_open(
                self.user_id, direction, price, amount, tp, sl,
                reason=reason,
                win_streak=self.win_streak,
                loss_streak=self.loss_streak,
                symbol=self.symbol,
            )

        return {
            "action": f"open_{direction}",
            "side": direction,
            "pnl": 0.0,
            "reason": reason,
        }

    # ──────────────────────────────────────────
    #  Анализ сигналов (для первого входа)
    # ──────────────────────────────────────────

    def _analyze_signal(self, snapshot: MarketSnapshot) -> EntrySignal:
        """
        Проверяет все 3 индикатора и возвращает EntrySignal.
        Используется только для первого входа.
        """
        price = snapshot.close
        rsi = snapshot.rsi or 50.0
        macd = snapshot.macd_line
        macd_sig = snapshot.macd_signal

        reasons = []

        # ──────────── RSI сигнал ────────────
        if rsi > self.cfg.rsi_long_threshold:
            rsi_side = "long"
            rsi_signal = True
            reasons.append(f"RSI={rsi:.1f}>50→LONG")
        elif rsi < self.cfg.rsi_short_threshold:
            rsi_side = "short"
            rsi_signal = True
            reasons.append(f"RSI={rsi:.1f}<50→SHORT")
        else:
            rsi_side = "neutral"
            rsi_signal = False
            reasons.append(f"RSI={rsi:.1f} нейтральный")

        # ──────────── MACD сигнал ────────────
        macd_signal = False
        macd_side = "neutral"

        if macd is not None and macd_sig is not None:
            macd_diff = macd - macd_sig
            logger.info(
                f"{self._tag} MACD | macd={macd:.6f} signal={macd_sig:.6f} "
                f"diff={macd_diff:.6f} prev={self._prev_macd_diff}"
            )

            if self._prev_macd_diff is not None:
                if self._prev_macd_diff < 0 and macd_diff > 0:
                    macd_side = "long"
                    macd_signal = True
                    reasons.append("MACD пересечение вверх→LONG")
                elif self._prev_macd_diff > 0 and macd_diff < 0:
                    macd_side = "short"
                    macd_signal = True
                    reasons.append("MACD пересечение вниз→SHORT")
                elif macd_diff > 0:
                    macd_side = "long"
                    macd_signal = True
                    reasons.append("MACD выше сигнала→LONG")
                elif macd_diff < 0:
                    macd_side = "short"
                    macd_signal = True
                    reasons.append("MACD ниже сигнала→SHORT")
                else:
                    reasons.append("MACD нейтральный")
            else:
                reasons.append("MACD первый тик")

            self._prev_macd_diff = macd_diff
        else:
            reasons.append("MACD нет данных")

        # ──────────── Bollinger Bands (трендовая логика) ────────────
        bb_signal = False
        bb_side = "neutral"
        bb_mid = snapshot.bb_mid
        bb_upper = snapshot.bb_upper
        bb_lower = snapshot.bb_lower

        if bb_mid and bb_upper and bb_lower:
            bb_range = bb_upper - bb_lower
            bb_squeeze = bb_range / bb_mid < 0.005  # BB сжатие < 0.5%

            if bb_squeeze:
                bb_side = "neutral"
                bb_signal = False
                reasons.append("BB сжатие→нейтрально")
            elif price > bb_mid:
                bb_side = "long"
                bb_signal = True
                reasons.append(f"Цена выше BB mid→LONG")
            elif price < bb_mid:
                bb_side = "short"
                bb_signal = True
                reasons.append(f"Цена ниже BB mid→SHORT")
            else:
                reasons.append("BB нейтрально")
        else:
            reasons.append("BB нет данных")

        # ──────────── Консенсус ────────────
        sides = [rsi_side, macd_side, bb_side]
        long_votes = sides.count("long")
        short_votes = sides.count("short")

        if long_votes == 3:
            final_side = "long"
            confidence = 3
        elif short_votes == 3:
            final_side = "short"
            confidence = 3
        elif long_votes >= 2:
            final_side = "long"
            confidence = long_votes
        elif short_votes >= 2:
            final_side = "short"
            confidence = short_votes
        else:
            final_side = "neutral"
            confidence = 0

        logger.info(
            f"{self._tag} votes | rsi={rsi_side} macd={macd_side} bb={bb_side} "
            f"→ {final_side} ({confidence}/3)"
        )

        return EntrySignal(
            side=final_side,
            rsi_signal=rsi_signal,
            macd_signal=macd_signal,
            bb_signal=bb_signal,
            confidence=confidence,
            reason=" | ".join(reasons),
        )

    # ──────────────────────────────────────────
    #  Открытие позиции (первый вход по индикаторам)
    # ──────────────────────────────────────────

    def _open_position(self, snapshot: MarketSnapshot, signal: EntrySignal) -> Dict:
        price = snapshot.close
        amount = self.exchange.calc_position_size(self.cfg.position_pct, price)

        if amount <= 0:
            logger.warning(f"{self._tag} skip open | reason=insufficient_balance")
            return {"action": "none", "reason": "insufficient_balance", "pnl": 0.0}

        order = self.exchange.place_market_order(signal.side, amount)
        if not order:
            logger.warning(f"{self._tag} skip open | reason=order_failed")
            if self.notifier:
                self.notifier.notify_order_failed(
                    self.user_id, "УМНЫЙ ВХОД", signal.side, price,
                    "place_market_order вернул None — проверь API-ключи, баланс и плечо"
                )
            return {"action": "none", "reason": "order_failed", "pnl": 0.0}

        if signal.side == "long":
            tp = price * (1 + self.cfg.tp_pct)
            sl = price * (1 - self.cfg.sl_pct)
        else:
            tp = price * (1 - self.cfg.tp_pct)
            sl = price * (1 + self.cfg.sl_pct)

        self.position = EntryPosition(
            side=signal.side,
            entry_price=price,
            amount=amount,
            tp_price=tp,
            sl_price=sl,
        )
        self.trade_count += 1

        logger.info(
            f"{self._tag} OPEN {signal.side.upper()} @ {price:.4f} | "
            f"TP={tp:.4f} SL={sl:.4f} | {signal.reason}"
        )

        # Telegram: первый вход по индикаторам
        if self.notifier:
            macd_above: Optional[bool] = None
            if snapshot.macd_line is not None and snapshot.macd_signal is not None:
                macd_above = snapshot.macd_line > snapshot.macd_signal

            bb_above_mid: Optional[bool] = None
            if snapshot.bb_mid is not None:
                bb_above_mid = snapshot.close > snapshot.bb_mid

            self.notifier.notify_entry_open(
                self.user_id, signal.side, price, amount, tp, sl,
                signal.reason, signal.confidence,
                rsi=snapshot.rsi,
                macd_above=macd_above,
                bb_above_mid=bb_above_mid,
                symbol=self.symbol,
            )

        return {
            "action": f"open_{signal.side}",
            "side": signal.side,
            "pnl": 0.0,
            "reason": signal.reason,
            "confidence": signal.confidence,
        }

    # ──────────────────────────────────────────
    #  Вспомогательные методы
    # ──────────────────────────────────────────

    def force_close(self) -> float:
        if self.position:
            ticker = self.exchange.fetch_ticker()
            price = ticker.get("last", self.position.entry_price)
            result = self._do_close(price, "force_close")
            return result.get("pnl", 0.0)
        return 0.0

    def get_stats(self) -> Dict:
        winrate = self.win_count / max(self.trade_count, 1) * 100
        return {
            "total_pnl": round(self.total_pnl, 4),
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "win_rate": round(winrate, 1),
            "win_streak": self.win_streak,
            "loss_streak": self.loss_streak,
            "last_result": self.last_result,
            "last_side": self.last_side,
            "has_position": self.position is not None,
        }
