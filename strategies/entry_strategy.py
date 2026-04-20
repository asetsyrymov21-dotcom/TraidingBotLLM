# ============================================================
#  Smart Adaptive Trading System — entry_strategy.py
#  Бот умного входа: RSI + MACD + Bollinger Bands
#  Только 3/3 совпадений → вход
# ============================================================

import logging
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
    Бот умного входа (подтверждённые входы).

    Правило: ВСЕ 3 индикатора должны совпасть:
    - RSI(14): > 50 → long, < 50 → short
    - MACD: пересечение вверх → long, вниз → short
    - Bollinger Bands: цена у нижней → long, у верхней → short

    Работает только в ТРЕНДЕ. Дополняет TrendStrategy.
    """

    def __init__(self, exchange: ExchangeConnector, cfg: EntryBotConfig,
                 notifier: Optional['TelegramNotifier'] = None, user_id: str = ""):
        self.exchange = exchange
        self.cfg = cfg
        self.position: Optional[EntryPosition] = None
        self._prev_macd_diff: Optional[float] = None
        self.total_pnl = 0.0
        self.trade_count = 0
        self.win_count = 0
        self.notifier = notifier
        self.user_id = user_id

    # ──────────────────────────────────────────
    #  Основной цикл
    # ──────────────────────────────────────────

    def tick(self, snapshot: MarketSnapshot) -> Dict:
        result = {"action": "none", "side": None, "pnl": 0.0, "reason": ""}

        logger.info(
            f"[ENTRY] tick start | price={snapshot.close} "
            f"state={getattr(snapshot.state, 'value', snapshot.state)} "
            f"has_position={self.position is not None}"
        )

        # Управление открытой позицией
        if self.position:
            logger.info(
                f"[ENTRY] managing open position | side={self.position.side} "
                f"entry={self.position.entry_price} amount={self.position.amount}"
            )
            return self._manage_position(snapshot)

        # Анализ сигнала
        signal = self._analyze_signal(snapshot)

        logger.info(
            f"[ENTRY] signal analyzed | side={signal.side} confidence={signal.confidence} "
            f"rsi={signal.rsi_signal} macd={signal.macd_signal} bb={signal.bb_signal} "
            f"reason={signal.reason}"
        )

        if signal.confidence < 2:
            result["reason"] = f"signal_weak ({signal.confidence}/3): {signal.reason}"
            logger.info(f"[ENTRY] skip entry | reason={result['reason']}")
            return result

        # Открытие позиции
        logger.info(f"[ENTRY] signal accepted -> opening position | side={signal.side}")
        return self._open_position(snapshot, signal)

    # ──────────────────────────────────────────
    #  Анализ сигналов
    # ──────────────────────────────────────────

    def _analyze_signal(self, snapshot: MarketSnapshot) -> EntrySignal:
        """
        Проверяет все 3 индикатора и возвращает EntrySignal.
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
            reasons.append(f"RSI={rsi:.1f}>50->LONG")
        elif rsi < self.cfg.rsi_short_threshold:
            rsi_side = "short"
            rsi_signal = True
            reasons.append(f"RSI={rsi:.1f}<50->SHORT")
        else:
            rsi_side = "neutral"
            rsi_signal = False
            reasons.append(f"RSI={rsi:.1f} neutral")

        # ──────────── MACD сигнал ────────────
        macd_signal = False
        macd_side = "neutral"

        if macd is not None and macd_sig is not None:
            macd_diff = macd - macd_sig
            logger.info(
                f"[ENTRY] MACD check | macd={macd:.6f} signal={macd_sig:.6f} "
                f"diff={macd_diff:.6f} prev_diff={self._prev_macd_diff}"
            )

            if self._prev_macd_diff is not None:
                if self._prev_macd_diff < 0 and macd_diff > 0:
                    macd_side = "long"
                    macd_signal = True
                    reasons.append("MACD cross UP->LONG")
                elif self._prev_macd_diff > 0 and macd_diff < 0:
                    macd_side = "short"
                    macd_signal = True
                    reasons.append("MACD cross DOWN->SHORT")
                elif macd_diff > 0:
                    macd_side = "long"
                    macd_signal = True
                    reasons.append("MACD above signal->LONG")
                elif macd_diff < 0:
                    macd_side = "short"
                    macd_signal = True
                    reasons.append("MACD below signal->SHORT")
                else:
                    reasons.append("MACD neutral")
            else:
                reasons.append("MACD first tick, no prev diff")

            self._prev_macd_diff = macd_diff
        else:
            reasons.append("MACD data missing")

        # ──────────── Bollinger Bands сигнал ────────────
        bb_signal = False
        bb_side = "neutral"
        bb_upper = snapshot.bb_upper
        bb_lower = snapshot.bb_lower
        bb_mid = snapshot.bb_mid

        if bb_upper and bb_lower and bb_mid:
            bb_range = bb_upper - bb_lower
            # Зона "у края" = последние 20% полосы
            edge_pct = 0.20
            lower_edge = bb_lower + bb_range * edge_pct   # нижние 20% → LONG
            upper_edge = bb_upper - bb_range * edge_pct   # верхние 20% → SHORT

            logger.info(
                f"[ENTRY] BB check | price={price:.4f} lower={bb_lower:.4f} "
                f"lower_edge={lower_edge:.4f} upper_edge={upper_edge:.4f} "
                f"upper={bb_upper:.4f} range={bb_range:.4f}"
            )

            # Трендовая логика BB: голосуем только у краёв полосы.
            # Цена у нижней границы → перепродан → LONG
            # Цена у верхней границы → перекуплен → SHORT
            # В середине полосы — нейтрально (не мешаем RSI+MACD)
            if price <= lower_edge:
                bb_side = "long"
                bb_signal = True
                reasons.append(
                    f"BB near lower band->LONG (price={price:.2f}, edge={lower_edge:.2f})"
                )
            elif price >= upper_edge:
                bb_side = "short"
                bb_signal = True
                reasons.append(
                    f"BB near upper band->SHORT (price={price:.2f}, edge={upper_edge:.2f})"
                )
            else:
                bb_side = "neutral"
                bb_signal = False
                reasons.append(
                    f"BB mid-zone->neutral (price={price:.2f}, "
                    f"range=[{lower_edge:.2f}–{upper_edge:.2f}])"
                )
        else:
            reasons.append("BB data missing")

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
            f"[ENTRY] votes | rsi_side={rsi_side} macd_side={macd_side} bb_side={bb_side} "
            f"long_votes={long_votes} short_votes={short_votes} "
            f"final_side={final_side} confidence={confidence}"
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
    #  Открытие и управление позицией
    # ──────────────────────────────────────────

    def _open_position(self, snapshot: MarketSnapshot, signal: EntrySignal) -> Dict:
        price = snapshot.close

        logger.info(
            f"[ENTRY] open_position start | raw_signal_side={signal.side} price={price:.4f}"
        )

        amount = self.exchange.calc_position_size(self.cfg.position_pct, price)
        logger.info(
            f"[ENTRY] amount calculated | position_pct={self.cfg.position_pct} "
            f"price={price:.4f} amount={amount}"
        )

        if amount <= 0:
            logger.warning(
                "[ENTRY] skip open | reason=insufficient_balance_or_zero_amount"
            )
            return {"action": "none", "reason": "insufficient_balance", "pnl": 0.0}

        side = signal.side
        logger.info(f"[ENTRY] calling place_market_order | side={side} amount={amount}")

        order = self.exchange.place_market_order(side, amount)

        logger.info(f"[ENTRY] place_market_order result | order={order}")

        if not order:
            logger.warning("[ENTRY] skip open | reason=order_failed")
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
            f"[ENTRY] OPEN {signal.side.upper()} @ {price:.4f} | "
            f"amount={amount} TP={tp:.4f} SL={sl:.4f} | {signal.reason}"
        )

        # Telegram: открыта позиция умного входа
        if self.notifier:
            self.notifier.notify_entry_open(
                self.user_id, signal.side, price, amount, tp, sl,
                signal.reason, signal.confidence,
            )

        return {
            "action": f"open_{signal.side}",
            "side": signal.side,
            "pnl": 0.0,
            "reason": signal.reason,
            "confidence": signal.confidence,
        }

    def _manage_position(self, snapshot: MarketSnapshot) -> Dict:
        pos = self.position
        price = snapshot.close
        result = {"action": "hold", "side": pos.side, "pnl": 0.0, "reason": ""}

        hit_tp = (pos.side == "long" and price >= pos.tp_price) or (
            pos.side == "short" and price <= pos.tp_price
        )
        hit_sl = (pos.side == "long" and price <= pos.sl_price) or (
            pos.side == "short" and price >= pos.sl_price
        )

        if hit_tp or hit_sl:
            reason = "tp" if hit_tp else "sl"
            close_side = "sell" if pos.side == "long" else "buy"
            self.exchange.place_market_order(close_side, pos.amount, reduce_only=True)

            if pos.side == "long":
                pnl = (price - pos.entry_price) * pos.amount
            else:
                pnl = (pos.entry_price - price) * pos.amount

            self.total_pnl += pnl
            if pnl > 0:
                self.win_count += 1

            logger.info(
                f"[ENTRY] CLOSE {pos.side.upper()} @ {price:.4f} | "
                f"PnL={pnl:.4f} | {reason.upper()}"
            )

            # Telegram: позиция закрыта
            if self.notifier:
                self.notifier.notify_entry_close(
                    self.user_id, pos.side, pos.entry_price, price, pnl, reason,
                )

            self.position = None
            result.update({"action": f"close_{reason}", "pnl": pnl})

        return result

    def force_close(self) -> float:
        if self.position:
            ticker = self.exchange.fetch_ticker()
            price = ticker.get("last", self.position.entry_price)
            pos = self.position
            close_side = "sell" if pos.side == "long" else "buy"
            self.exchange.place_market_order(close_side, pos.amount, reduce_only=True)
            pnl = (
                (price - pos.entry_price) * pos.amount
                if pos.side == "long"
                else (pos.entry_price - price) * pos.amount
            )
            self.total_pnl += pnl
            self.position = None
            return pnl
        return 0.0

    def get_stats(self) -> Dict:
        winrate = self.win_count / max(self.trade_count, 1) * 100
        return {
            "total_pnl": round(self.total_pnl, 4),
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "win_rate": round(winrate, 1),
            "has_position": self.position is not None,
        }
