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
from dataclasses import dataclass, field
from typing import Optional, Dict

from typing import TYPE_CHECKING

from config import EntryBotConfig
from exchange import ExchangeConnector
from market_analyzer import MarketSnapshot

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
    entry_fee: float = 0.0
    open_time: float = field(default_factory=time.time)


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

        # ── ПЕРВЫЙ ВХОД: по 3 индикаторам ──
        if self.last_result == "NONE":
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
            direction = self.last_side
            logger.info(f"{self._tag} WIN continuation → {direction.upper()}")
            return self._open_in_direction(snapshot, direction, "win_continue")

        # ── LOSS → переворот ──
        direction = "short" if self.last_side == "long" else "long"
        logger.info(f"{self._tag} LOSS reversal → {direction.upper()} (was {self.last_side})")
        return self._open_in_direction(snapshot, direction, "loss_reverse")

    # ──────────────────────────────────────────
    #  Управление позицией
    # ──────────────────────────────────────────

    def _manage_position(self, snapshot: MarketSnapshot) -> Dict:
        pos = self.position
        price = snapshot.close
        high = getattr(snapshot, "high", price)
        low = getattr(snapshot, "low", price)

        # ── Экстренный сквиз -15% (если SL не сработал) ──
        emergency_pct = getattr(self.cfg, 'emergency_squeeze_pct', 0.15)
        if pos.side == "long":
            drop = (pos.entry_price - low) / pos.entry_price
            if drop >= emergency_pct:
                logger.warning(
                    f"{self._tag} EMERGENCY SQUEEZE! LONG drop={drop*100:.1f}% >= {emergency_pct*100:.0f}%"
                )
                return self._do_close(low, "emergency_squeeze")
        else:
            rise = (high - pos.entry_price) / pos.entry_price
            if rise >= emergency_pct:
                logger.warning(
                    f"{self._tag} EMERGENCY SQUEEZE! SHORT rise={rise*100:.1f}% >= {emergency_pct*100:.0f}%"
                )
                return self._do_close(high, "emergency_squeeze")

        # ── TP ──
        hit_tp = (pos.side == "long" and high >= pos.tp_price) or (
            pos.side == "short" and low <= pos.tp_price
        )
        if hit_tp:
            logger.info(
                f"{self._tag} TP HIT | side={pos.side} low={low:.4f} high={high:.4f} "
                f"tp={pos.tp_price:.4f} sl={pos.sl_price:.4f} next_side={pos.side}"
            )
            return self._close_and_reopen(snapshot, pos.tp_price, "tp", pos.side, "tp_reopen")

        # ── SL ──
        hit_sl = (pos.side == "long" and low <= pos.sl_price) or (
            pos.side == "short" and high >= pos.sl_price
        )
        if hit_sl:
            reverse_side = "short" if pos.side == "long" else "long"
            logger.info(
                f"{self._tag} SL HIT | side={pos.side} low={low:.4f} high={high:.4f} "
                f"tp={pos.tp_price:.4f} sl={pos.sl_price:.4f} next_side={reverse_side}"
            )
            return self._close_and_reopen(snapshot, pos.sl_price, "sl", reverse_side, "sl_reverse")

        return {"action": "hold", "side": pos.side, "pnl": 0.0, "reason": ""}

    def _close_and_reopen(self, snapshot: MarketSnapshot, close_price: float,
                          close_reason: str, next_side: str, open_reason: str) -> Dict:
        """Закрывает позицию и сразу открывает следующую сделку."""
        started_at = time.time()
        logger.info(
            f"{self._tag} FAST_CHAIN start | close_reason={close_reason} "
            f"close_price={close_price:.4f} next_side={next_side} open_reason={open_reason}"
        )
        close_result = self._do_close(close_price, close_reason)

        if self.position is not None or self.last_result == "NONE":
            logger.info(
                f"{self._tag} FAST_CHAIN stop_after_close | elapsed={time.time() - started_at:.3f}s "
                f"position_exists={self.position is not None} last_result={self.last_result}"
            )
            return close_result

        open_result = self._open_in_direction(snapshot, next_side, open_reason)
        logger.info(
            f"{self._tag} FAST_CHAIN done | elapsed={time.time() - started_at:.3f}s "
            f"close_action={close_result.get('action')} open_action={open_result.get('action')} "
            f"open_reason={open_result.get('reason')}"
        )
        return {
            "action": f"{close_result['action']}_{open_result['action']}",
            "side": open_result.get("side", close_result.get("side")),
            "pnl": close_result.get("pnl", 0.0),
            "reason": open_reason,
            "close": close_result,
            "open": open_result,
        }

    def _do_close(self, price: float, reason: str) -> Dict:
        """Закрывает позицию и обновляет Win/Loss состояние."""
        pos = self.position
        close_side = "sell" if pos.side == "long" else "buy"
        order_started_at = time.time()
        logger.info(
            f"{self._tag} CLOSE_ORDER send | side={close_side} amount={pos.amount} "
            f"reduce_only=True reason={reason}"
        )
        order = self.exchange.place_market_order(close_side, pos.amount, reduce_only=True)
        logger.info(
            f"{self._tag} CLOSE_ORDER done | elapsed={time.time() - order_started_at:.3f}s "
            f"order_ok={order is not None}"
        )
        close_price, close_amount, close_fee = self._extract_order_fill(order or {}, price, pos.amount)

        # Расчёт PnL
        if pos.side == "long":
            gross_pnl = (close_price - pos.entry_price) * close_amount
        else:
            gross_pnl = (pos.entry_price - close_price) * close_amount
        pnl = gross_pnl - pos.entry_fee - close_fee

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
            self.pause_candles_left = 0 if reason == "sl" else 1

            # Серия 10+ убытков → полный сброс, снова ищем вход по индикаторам
            if self.loss_streak >= 10:
                logger.warning(
                    f"{self._tag} Loss streak {self.loss_streak}! "
                    f"Resetting to first-entry mode (RSI+MACD+BB)."
                )
                self.last_result = "NONE"
                self.last_side = ""
                self.win_streak = 0
                self.loss_streak = 0
                self.pause_candles_left = 1  # Ждём 1 тик перед новым входом

                # Telegram: сброс после серии убытков
                if self.notifier:
                    self.notifier.notify_loss_streak_reset(
                        self.user_id, symbol=self.symbol
                    )

        logger.info(
            f"{self._tag} CLOSE {pos.side.upper()} @ {close_price:.4f} | "
            f"GrossPnL={gross_pnl:+.4f} Fees={pos.entry_fee + close_fee:.6f} "
            f"NetPnL={pnl:+.4f} | Reason={reason} | "
            f"WinStreak={self.win_streak} LossStreak={self.loss_streak}"
        )

        # Telegram: позиция закрыта
        if self.notifier:
            self.notifier.notify_entry_close(
                self.user_id, pos.side, pos.entry_price, close_price, pnl, reason,
                win_streak=self.win_streak,
                loss_streak=self.loss_streak,
                symbol=self.symbol,
                tp_price=pos.tp_price,
                sl_price=pos.sl_price,
            )

        self.position = None
        return {"action": f"close_{reason}", "pnl": pnl, "reason": reason, "side": pos.side}

    @staticmethod
    def _extract_order_fill(order: Dict, fallback_price: float, fallback_amount: float):
        info = order.get("info") or {}

        def _num(*values):
            for value in values:
                try:
                    if value not in (None, ""):
                        parsed = float(value)
                        if parsed > 0:
                            return parsed
                except (TypeError, ValueError):
                    pass
            return 0.0

        price = _num(
            order.get("average"), order.get("avgPrice"), order.get("price"),
            info.get("avgPrice"), info.get("execPrice"),
        ) or fallback_price
        amount = _num(
            order.get("filled"), order.get("executedQty"), order.get("amount"),
            info.get("executedQty"), info.get("cumExecQty"), info.get("qty"),
        ) or fallback_amount
        fee = 0.0
        if isinstance(order.get("fee"), dict):
            fee += _num(order["fee"].get("cost"))
        for item in order.get("fees") or []:
            if isinstance(item, dict):
                fee += _num(item.get("cost"))
        fee += _num(info.get("execFee"), info.get("cumExecFee"))

        return price, amount, fee

    def _calc_adaptive_tp_sl(self, snapshot: MarketSnapshot, direction: str):
        """
        Рассчитывает TP и SL с учётом ATR (волатильности рынка).
        Тихий рынок → меньший TP/SL, волатильный → больший.
        Возвращает (tp_price, sl_price, tp_pct, sl_pct, regime).
        """
        price = snapshot.close
        atr_pct = snapshot.atr_pct or 0.0

        quiet_thr    = getattr(self.cfg, "atr_quiet_threshold",    0.003)
        volatile_thr = getattr(self.cfg, "atr_volatile_threshold", 0.008)
        tp_quiet     = getattr(self.cfg, "tp_quiet",               0.002)
        tp_normal    = getattr(self.cfg, "tp_normal",              0.005)
        tp_volatile  = getattr(self.cfg, "tp_volatile",            0.010)
        sl_mult      = getattr(self.cfg, "sl_multiplier",          8.0)

        if atr_pct > 0 and atr_pct < quiet_thr:
            regime = "quiet"
            tp_pct = tp_quiet
        elif atr_pct >= volatile_thr:
            regime = "volatile"
            tp_pct = tp_volatile
        else:
            regime = "normal"
            tp_pct = tp_normal

        sl_pct = tp_pct * sl_mult

        if direction == "long":
            tp = price * (1 + tp_pct)
            sl = price * (1 - sl_pct)
        else:
            tp = price * (1 - tp_pct)
            sl = price * (1 + sl_pct)

        logger.info(
            f"{self._tag} adaptive_tp_sl | ATR%={atr_pct*100:.3f}% "
            f"regime={regime} TP={tp_pct*100:.2f}% SL={sl_pct*100:.2f}%"
        )
        return tp, sl, tp_pct, sl_pct, regime

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

        order_started_at = time.time()
        logger.info(
            f"{self._tag} OPEN_ORDER send | side={direction} amount={amount} reason={reason}"
        )
        order = self.exchange.place_market_order(direction, amount)
        logger.info(
            f"{self._tag} OPEN_ORDER done | elapsed={time.time() - order_started_at:.3f}s "
            f"order_ok={order is not None} reason={reason}"
        )
        if not order:
            logger.warning(f"{self._tag} skip open | reason=order_failed ({reason})")
            # Сбрасываем last_result — иначе следующий тик снова попытается открыть тот же ордер
            self.last_result = "NONE"
            self.last_side = ""
            if self.notifier:
                self.notifier.notify_order_failed(
                    self.user_id, "WIN/LOSS", direction, price,
                    "place_market_order вернул None — проверь API-ключи и баланс"
                )
            return {"action": "none", "reason": "order_failed", "pnl": 0.0}

        tp, sl, tp_pct, sl_pct, regime = self._calc_adaptive_tp_sl(snapshot, direction)
        fill_price, fill_amount, entry_fee = self._extract_order_fill(order, price, amount)

        self.position = EntryPosition(
            side=direction,
            entry_price=fill_price,
            amount=fill_amount,
            tp_price=tp,
            sl_price=sl,
            entry_fee=entry_fee,
        )
        self.trade_count += 1

        logger.info(
            f"{self._tag} OPEN {direction.upper()} @ {fill_price:.4f} | "
            f"TP={tp:.4f} SL={sl:.4f} | Reason={reason} | "
            f"Amount={fill_amount} | EntryFee={entry_fee:.6f}"
        )

        # Telegram: открыта позиция (win/loss)
        if self.notifier:
            self.notifier.notify_winloss_open(
                self.user_id, direction, fill_price, fill_amount, tp, sl,
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
            # Сбрасываем last_result — иначе следующий тик снова попытается открыть тот же ордер
            self.last_result = "NONE"
            self.last_side = ""
            if self.notifier:
                self.notifier.notify_order_failed(
                    self.user_id, "УМНЫЙ ВХОД", signal.side, price,
                    "place_market_order вернул None — проверь API-ключи, баланс и плечо"
                )
            return {"action": "none", "reason": "order_failed", "pnl": 0.0}

        tp, sl, tp_pct, sl_pct, regime = self._calc_adaptive_tp_sl(snapshot, signal.side)
        fill_price, fill_amount, entry_fee = self._extract_order_fill(order, price, amount)

        self.position = EntryPosition(
            side=signal.side,
            entry_price=fill_price,
            amount=fill_amount,
            tp_price=tp,
            sl_price=sl,
            entry_fee=entry_fee,
        )
        self.trade_count += 1

        logger.info(
            f"{self._tag} OPEN {signal.side.upper()} @ {fill_price:.4f} | "
            f"TP={tp:.4f} SL={sl:.4f} | Amount={fill_amount} | "
            f"EntryFee={entry_fee:.6f} | {signal.reason}"
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
                self.user_id, signal.side, fill_price, fill_amount, tp, sl,
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
        }
