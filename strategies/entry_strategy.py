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
                 notifier: Optional['TelegramNotifier'] = None, user_id: str = "",
                 symbol: str = ""):
        self.exchange = exchange
        self.cfg = cfg
        self.symbol = symbol
        # Тег для логов: "[ENTRY:BTC/USDT]" в мультипарном режиме,
        # "[ENTRY]" если пара не задана (обратная совместимость).
        self._tag = f"[ENTRY:{symbol}]" if symbol else "[ENTRY]"
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
            f"{self._tag} tick start | price={snapshot.close} "
            f"state={getattr(snapshot.state, 'value', snapshot.state)} "
            f"has_position={self.position is not None}"
        )

        # Управление открытой позицией
        if self.position:
            logger.info(
                f"{self._tag} managing open position | side={self.position.side} "
                f"entry={self.position.entry_price} amount={self.position.amount}"
            )
            return self._manage_position(snapshot)

        # Анализ сигнала
        signal = self._analyze_signal(snapshot)

        logger.info(
            f"{self._tag} signal analyzed | side={signal.side} confidence={signal.confidence} "
            f"rsi={signal.rsi_signal} macd={signal.macd_signal} bb={signal.bb_signal} "
            f"reason={signal.reason}"
        )

        if signal.confidence < 2:
            result["reason"] = f"signal_weak ({signal.confidence}/3): {signal.reason}"
            logger.info(f"{self._tag} skip entry | reason={result['reason']}")
            return result

        # Открытие позиции
        logger.info(f"{self._tag} signal accepted -> opening position | side={signal.side}")
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
                f"{self._tag} MACD check | macd={macd:.6f} signal={macd_sig:.6f} "
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

        # ──────────── Bollinger Bands сигнал (трендовая логика) ────────────
        # Используем BB midband (SMA20) как трендовый фильтр:
        # Цена ВЫШЕ midband → рынок бычий → LONG
        # Цена НИЖЕ midband → рынок медвежий → SHORT
        # Старая mean-reversion логика (buy at lower band) противоречила тренду:
        # в сильном аптренде цена едет по верхней полосе, BB давал сигнал SHORT.
        bb_signal = False
        bb_side = "neutral"
        bb_mid = snapshot.bb_mid
        bb_upper = snapshot.bb_upper
        bb_lower = snapshot.bb_lower

        if bb_mid and bb_upper and bb_lower:
            bb_range = bb_upper - bb_lower
            # Мёртвая зона: слишком узкие полосы = нет тренда, BB не голосует
            bb_squeeze = bb_range / bb_mid < 0.005  # ширина полосы < 0.5% цены

            logger.info(
                f"{self._tag} BB check | price={price:.4f} mid={bb_mid:.4f} "
                f"range={bb_range:.4f} squeeze={bb_squeeze}"
            )

            if bb_squeeze:
                bb_side = "neutral"
                bb_signal = False
                reasons.append(f"BB squeeze->neutral (band too tight, no trend)")
            elif price > bb_mid:
                bb_side = "long"
                bb_signal = True
                reasons.append(f"BB price above midband->LONG (price={price:.2f} > mid={bb_mid:.2f})")
            elif price < bb_mid:
                bb_side = "short"
                bb_signal = True
                reasons.append(f"BB price below midband->SHORT (price={price:.2f} < mid={bb_mid:.2f})")
            else:
                bb_side = "neutral"
                bb_signal = False
                reasons.append(f"BB price at midband->neutral")
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
            f"{self._tag} votes | rsi_side={rsi_side} macd_side={macd_side} bb_side={bb_side} "
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
            f"{self._tag} open_position start | raw_signal_side={signal.side} price={price:.4f}"
        )

        amount = self.exchange.calc_position_size(self.cfg.position_pct, price)
        logger.info(
            f"{self._tag} amount calculated | position_pct={self.cfg.position_pct} "
            f"price={price:.4f} amount={amount}"
        )

        if amount <= 0:
            logger.warning(
                f"{self._tag} skip open | reason=insufficient_balance_or_zero_amount"
            )
            return {"action": "none", "reason": "insufficient_balance", "pnl": 0.0}

        side = signal.side
        logger.info(f"{self._tag} calling place_market_order | side={side} amount={amount}")

        order = self.exchange.place_market_order(side, amount)

        logger.info(f"{self._tag} place_market_order result | order={order}")

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
            f"amount={amount} TP={tp:.4f} SL={sl:.4f} | {signal.reason}"
        )

        # Telegram: открыта позиция умного входа
        if self.notifier:
            # Определяем состояние MACD (выше/ниже сигнальной линии)
            macd_above: Optional[bool] = None
            if snapshot.macd_line is not None and snapshot.macd_signal is not None:
                macd_above = snapshot.macd_line > snapshot.macd_signal

            # Определяем положение цены относительно BB midband
            bb_above_mid: Optional[bool] = None
            if snapshot.bb_mid is not None:
                bb_above_mid = snapshot.close > snapshot.bb_mid

            self.notifier.notify_entry_open(
                self.user_id, signal.side, price, amount, tp, sl,
                signal.reason, signal.confidence,
                rsi=snapshot.rsi,
                macd_above=macd_above,
                bb_above_mid=bb_above_mid,
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
                f"{self._tag} CLOSE {pos.side.upper()} @ {price:.4f} | "
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
