# ============================================================
#  Smart Adaptive Trading System — telegram_notifier.py
#  Telegram-уведомления о действиях бота
# ============================================================

import logging
import ssl
import threading
import time
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError

# SSL-контекст без верификации (нужно на Windows с корпоративным прокси/антивирусом)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Отправляет уведомления в Telegram.

    Использует Telegram Bot API напрямую через urllib (без зависимостей).
    Сообщения отправляются асинхронно чтобы не блокировать торговлю.
    """

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._last_balance: Optional[float] = None   # Обновляется из BotEngine каждый тик
        self._session_pnl: Optional[float] = None    # Суммарный PnL сессии
        self._in_trade_amount: float = 0.0           # Сумма в открытой сделке (USDT)
        # Пакетный режим: все сообщения тика объединяются в одно
        self._batching: bool = False
        self._buffer: list = []

    def update_balance(self, balance: float):
        """Обновляет текущий баланс — добавляется в конец каждого сообщения"""
        self._last_balance = balance

    def update_session_info(self, session_pnl: float, in_trade_amount: float = 0.0):
        """Обновляет PnL сессии и сумму в сделке — добавляется в футер каждого сообщения"""
        self._session_pnl = session_pnl
        self._in_trade_amount = in_trade_amount

    # ──────────────────────────────────────────
    #  Низкоуровневая отправка
    # ──────────────────────────────────────────

    # ──────────────────────────────────────────
    #  Пакетный режим (batch): все уведомления тика → одно TG-сообщение
    # ──────────────────────────────────────────

    def start_batch(self):
        """Начать накопление сообщений. Вызывается перед тиком."""
        self._buffer = []
        self._batching = True

    def flush_batch(self):
        """
        Отправить все накопленные сообщения одним TG-сообщением.
        Вызывается после тика. Если буфер пустой — ничего не шлём.
        """
        self._batching = False
        if not self._buffer:
            return

        divider = "\n\n" + "─" * 22 + "\n\n"
        combined = divider.join(self._buffer)

        # Один общий футер в конце
        footer = self._build_footer()
        if footer:
            combined += "\n\n" + footer

        # Telegram лимит ~4096 символов
        if len(combined) > 4000:
            combined = combined[:3950] + "\n<i>...обрезано</i>"

        self._send_raw(combined)
        self._buffer = []

    def _build_footer(self) -> str:
        """Строит строку футера: баланс + PnL + сумма в сделке."""
        parts = []
        if self._last_balance is not None:
            parts.append(f"💼 <b>{self._last_balance:.2f} USDT</b>")
        if self._session_pnl is not None:
            sign = "+" if self._session_pnl >= 0 else ""
            emoji = "📈" if self._session_pnl >= 0 else "📉"
            parts.append(f"{emoji} PnL: <b>{sign}{self._session_pnl:.4f}</b>")
        if self._in_trade_amount > 0:
            parts.append(f"🔄 В сделке: <b>{self._in_trade_amount:.2f} USDT</b>")
        return " | ".join(parts)

    def _send_message(self, text: str):
        """
        Отправляет сообщение.
        В пакетном режиме — кладёт в буфер (без футера).
        В обычном режиме — добавляет футер и шлёт сразу.
        """
        if not self.enabled or not self.bot_token or not self.chat_id:
            return

        if self._batching:
            # Накапливаем без футера — он будет один в конце flush_batch
            self._buffer.append(text)
            return

        # Обычная отправка с футером
        footer = self._build_footer()
        if footer:
            text += "\n\n" + footer
        self._send_raw(text)

    def _send_urgent(self, text: str):
        """
        Немедленная отправка вне батча — для важных событий (закрытие позиции).
        Всегда уходит отдельным сообщением, даже если батч активен.
        """
        if not self.enabled or not self.bot_token or not self.chat_id:
            return
        footer = self._build_footer()
        if footer:
            text += "\n\n" + footer
        self._send_raw(text)

    def _send_raw(self, text: str):
        """Низкоуровневая отправка в Telegram (в отдельном потоке)."""
        def _do_send():
            try:
                encoded = quote_plus(text)
                url = (
                    f"{self._base_url}/sendMessage"
                    f"?chat_id={self.chat_id}"
                    f"&text={encoded}"
                    f"&parse_mode=HTML"
                )
                req = Request(url, method="GET")
                with urlopen(req, timeout=10, context=_ssl_ctx) as resp:
                    if resp.status != 200:
                        logger.warning(f"[TG] Send failed: HTTP {resp.status}")
            except URLError as e:
                logger.warning(f"[TG] Send failed: {e}")
            except Exception as e:
                logger.warning(f"[TG] Unexpected error: {e}")

        threading.Thread(target=_do_send, daemon=True).start()

    # ──────────────────────────────────────────
    #  Старт / стоп бота
    # ──────────────────────────────────────────

    def notify_bot_started(self, user_id: str, symbol: str, exchange: str, balance: float):
        self._send_message(
            f"🟢 <b>Бот запущен</b>\n"
            f"👤 Пользователь: {user_id}\n"
            f"📊 Пара: {symbol}\n"
            f"🏦 Биржа: {exchange}\n"
            f"💰 Баланс: {balance:.2f} USDT"
        )

    def notify_bot_started_multi(
        self,
        user_id: str,
        exchange: str,
        symbols: list,
        balance: float,
        leverage: int = 1,
        deposit_pct: float = 0.05,
        is_testnet: bool = True,
    ):
        """
        Одно объединённое уведомление о старте бота со списком всех активных пар.
        Заменяет N отдельных notify_bot_started при мультипарном режиме.
        """
        n = len(symbols)
        per_pair_pct = (deposit_pct / n * 100) if n > 0 else 0
        pairs_text = "\n".join(f"  • {s}" for s in symbols)
        testnet_str = "🧪 TESTNET" if is_testnet else "🔴 LIVE"

        self._send_message(
            f"🟢 <b>Бот запущен</b>\n"
            f"👤 Пользователь: {user_id}\n"
            f"🏦 Биржа: {exchange} | {testnet_str}\n"
            f"⚡ Плечо: x{leverage}\n"
            f"💰 Баланс: {balance:.2f} USDT\n\n"
            f"📊 <b>Активные пары ({n}):</b>\n"
            f"{pairs_text}\n\n"
            f"💼 <i>На каждую пару: ~{per_pair_pct:.2f}% депозита</i>"
        )

    def notify_bot_stopped(self, user_id: str, stats: dict):
        risk = stats.get("risk", {})
        trend = stats.get("trend_bot", {})
        entry = stats.get("entry_bot", {})
        grid = stats.get("grid_bot", {})

        total_pnl = trend.get("total_pnl", 0) + entry.get("total_pnl", 0) + grid.get("realized_pnl", 0)
        total_trades = trend.get("trade_count", 0) + entry.get("trade_count", 0)

        self._send_message(
            f"🔴 <b>Бот остановлен</b>\n"
            f"👤 {user_id}\n"
            f"📈 Итого PnL: {total_pnl:+.4f} USDT\n"
            f"🔢 Сделок: {total_trades}\n"
            f"🏆 Winrate Trend: {trend.get('win_rate', 0)}%\n"
            f"🏆 Winrate Entry: {entry.get('win_rate', 0)}%"
        )

    # ──────────────────────────────────────────
    #  Переключение режима
    # ──────────────────────────────────────────

    def notify_mode_switch(
        self,
        user_id: str,
        old_mode: Optional[str],
        new_mode: str,
        market_state: str,
        price: float,
        adx: Optional[float] = None,
        symbol: str = "",
        ema_fast: Optional[float] = None,
        ema_slow: Optional[float] = None,
        atr: Optional[float] = None,
    ):
        mode_names = {
            "grid": "🔲 GRID (флэт)",
            "trend": "📈 ТРЕНД",
            "wait": "⏸ ОЖИДАНИЕ",
        }
        old_name = mode_names.get(old_mode, "—")
        new_name = mode_names.get(new_mode, "—")

        reasons = {
            "FLAT": "ADX показывает слабый тренд — рынок во флэте, ждём тренд",
            "TREND_UP": "ADX показывает сильный восходящий тренд — торгуем по тренду вверх",
            "TREND_DOWN": "ADX показывает сильный нисходящий тренд — торгуем по тренду вниз",
            "UNKNOWN": "Состояние рынка неопределённое",
        }

        symbol_str = f"\n📊 Пара: <b>{symbol}</b>" if symbol else ""
        adx_str = f"\n📏 ADX: {adx:.1f}" if adx is not None else ""
        atr_str = f" | ATR: {atr:.4f}" if atr is not None else ""
        ema_str = ""
        if ema_fast is not None and ema_slow is not None:
            cross = "▲" if ema_fast > ema_slow else "▼"
            ema_str = f"\n📉 EMA9: {ema_fast:.2f} {cross} EMA21: {ema_slow:.2f}"

        self._send_message(
            f"🔄 <b>Смена режима</b>\n"
            f"👤 {user_id}{symbol_str}\n"
            f"Было: {old_name} → Стало: {new_name}\n"
            f"💲 Цена: {price:.4f}{atr_str}\n"
            f"🌡 Рынок: {market_state}{adx_str}{ema_str}\n\n"
            f"💡 <i>Причина: {reasons.get(market_state, market_state)}</i>"
        )

    # ──────────────────────────────────────────
    #  Трендовая стратегия
    # ──────────────────────────────────────────

    def notify_trend_open(
        self,
        user_id: str,
        side: str,
        price: float,
        amount: float,
        tp: float,
        sl: float,
        rsi: float,
        ema_fast: float,
        ema_slow: float,
        last_result: str,
        size_mult: float,
        symbol: str = "",
        atr: Optional[float] = None,
        leverage: int = 1,
    ):
        side_emoji = "🟢 LONG" if side == "long" else "🔴 SHORT"

        symbol_str = f"\n📊 Пара: <b>{symbol}</b>" if symbol else ""
        atr_str = f" | ATR: {atr:.4f}" if atr is not None else ""
        leverage_str = f"⚡ Плечо: x{leverage} | " if leverage > 1 else ""

        # Объясняем почему именно эта сторона
        if last_result == "LOSS":
            side_reason = f"Предыдущая сделка была убыточной → переворот в {side.upper()}"
        elif last_result == "WIN":
            side_reason = f"Предыдущая сделка была прибыльной → продолжаем {side.upper()}"
        else:
            side_reason = f"Первый вход по тренду в {side.upper()}"

        ema_reason = (
            f"EMA9 ({ema_fast:.2f}) {'выше' if ema_fast > ema_slow else 'ниже'} "
            f"EMA21 ({ema_slow:.2f}) → {'восходящий' if ema_fast > ema_slow else 'нисходящий'} тренд"
        )

        self._send_message(
            f"📈 <b>ТРЕНД: Открыта позиция</b>\n"
            f"👤 {user_id}{symbol_str}\n"
            f"🔹 {side_emoji} @ {price:.4f}{atr_str}\n"
            f"📦 {leverage_str}Размер: {amount} (×{size_mult:.2f})\n"
            f"🎯 TP: {tp:.4f} (+{abs(tp/price - 1)*100:.1f}%)\n"
            f"🛑 SL: {sl:.4f} (-{abs(sl/price - 1)*100:.1f}%)\n\n"
            f"💡 <i>Почему {side.upper()}:</i>\n"
            f"• {side_reason}\n"
            f"• {ema_reason}\n"
            f"• RSI: {rsi:.1f}"
        )

    def notify_trend_close(
        self,
        user_id: str,
        side: str,
        entry_price: float,
        close_price: float,
        pnl: float,
        reason: str,
        win_streak: int,
        loss_streak: int,
        symbol: str = "",
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
    ):
        is_win = pnl > 0
        pnl_emoji = "✅" if is_win else "❌"

        symbol_str = f"\n📊 Пара: <b>{symbol}</b>" if symbol else ""
        streak = f"🏆 Серия побед: {win_streak}" if win_streak > 0 else f"💀 Серия убытков: {loss_streak}"
        price_change_pct = (close_price - entry_price) / entry_price * 100
        if side == "short":
            price_change_pct = -price_change_pct
        move_pct = abs(price_change_pct)

        tp_str = f" (уровень: {tp_price:.4f})" if tp_price else ""
        sl_str = f" (уровень: {sl_price:.4f})" if sl_price else ""

        reason_text = {
            "tp": f"🎯 Take Profit сработал{tp_str} — цена прошла {move_pct:.2f}% в нашу сторону",
            "sl": f"🛑 Stop Loss сработал{sl_str} — цена пошла {move_pct:.2f}% против позиции",
            "squeeze": f"🚨 Анти-сквиз — резкое движение {move_pct:.1f}% против позиции, экстренный выход",
            "force_close": "⛔ Принудительное закрытие — бот остановлен или достигнут риск-лимит",
            "trail_stop": f"📉 Trailing Stop — цена откатилась от максимума, фиксируем прибыль ({move_pct:.2f}%)",
            "timeout": f"⏱ Таймаут — позиция висела слишком долго без движения, принудительное закрытие",
        }

        self._send_urgent(
            f"{pnl_emoji} <b>ТРЕНД: Позиция закрыта</b>\n"
            f"👤 {user_id}{symbol_str}\n"
            f"{'🟢' if side == 'long' else '🔴'} {side.upper()}\n"
            f"📥 Вход: {entry_price:.4f} → 📤 Выход: {close_price:.4f} ({price_change_pct:+.2f}%)\n"
            f"💰 PnL: {pnl:+.4f} USDT\n"
            f"{streak}\n\n"
            f"💡 <i>Причина: {reason_text.get(reason, reason)}</i>"
        )

    def notify_trend_skip(self, user_id: str, reason: str, price: float, symbol: str = ""):
        """Уведомление о пропуске входа (только важные — пауза, волатильность)"""
        important_reasons = {
            "pause_active": "⏸ Пауза после серии убытков. Бот ждёт 20 минут",
            "high_volatility": "⚡ Аномальная волатильность! Вход слишком рискован",
        }
        text = important_reasons.get(reason)
        if text:
            symbol_str = f" | 📊 {symbol}" if symbol else ""
            self._send_message(
                f"⚠️ <b>ТРЕНД: Пропуск входа</b>\n"
                f"👤 {user_id}{symbol_str} | 💲 {price:.4f}\n"
                f"{text}"
            )

    def notify_order_failed(self, user_id: str, strategy: str, side: str, price: float, reason: str):
        """Уведомление об ошибке размещения ордера"""
        self._send_message(
            f"🚫 <b>Ордер не выставлен [{strategy}]</b>\n"
            f"👤 {user_id}\n"
            f"{'🟢' if side == 'long' else '🔴'} {side.upper()} @ {price:.4f}\n"
            f"❗ Причина: {reason}\n\n"
            f"💡 <i>Проверь логи (bot.log) и настройки API.</i>"
        )

    def notify_risk_blocked(self, user_id: str, reason: str, daily_pnl: str, drawdown: str):
        self._send_message(
            f"⛔ <b>Торговля заблокирована</b>\n"
            f"👤 {user_id}\n"
            f"❗ Причина: {reason}\n"
            f"📉 Дневной PnL: {daily_pnl} | Просадка: {drawdown}"
        )

    def notify_emergency_close(self, user_id: str):
        self._send_message(
            f"🚨 <b>Экстренное закрытие позиций</b>\n"
            f"👤 {user_id}\n"
            f"⚠️ Все позиции закрыты по риск-лимиту."
        )

    # ──────────────────────────────────────────
    #  Стратегия умного входа (Entry)
    # ──────────────────────────────────────────

    def notify_entry_open(
        self,
        user_id: str,
        side: str,
        price: float,
        amount: float,
        tp: float,
        sl: float,
        signal_reason: str,
        confidence: int,
        rsi: Optional[float] = None,
        macd_above: Optional[bool] = None,
        bb_above_mid: Optional[bool] = None,
        symbol: str = "",
    ):
        side_emoji = "🟢 LONG" if side == "long" else "🔴 SHORT"
        direction = "вверх" if side == "long" else "вниз"
        symbol_str = f"\n📊 <b>{symbol}</b>" if symbol else ""

        # Объясняем каждый индикатор человеческим языком
        explanations = []

        if rsi is not None:
            if side == "long":
                explanations.append(
                    f"RSI = {rsi:.1f} — выше 50, рынок бычий → сигнал на покупку"
                )
            else:
                explanations.append(
                    f"RSI = {rsi:.1f} — ниже 50, рынок медвежий → сигнал на продажу"
                )

        if macd_above is not None:
            if macd_above:
                explanations.append("MACD — линия выше сигнальной, импульс направлен вверх")
            else:
                explanations.append("MACD — линия ниже сигнальной, импульс направлен вниз")

        if bb_above_mid is not None:
            if bb_above_mid:
                explanations.append("Цена выше средней полосы BB → тренд восходящий")
            else:
                explanations.append("Цена ниже средней полосы BB → тренд нисходящий")

        bullets = "\n".join(f"• {e}" for e in explanations) if explanations else signal_reason

        conf_text = {3: "все 3/3 индикатора совпали", 2: "2/3 индикатора совпали"}.get(
            confidence, f"{confidence}/3 индикатора"
        )

        self._send_message(
            f"🧠 <b>ПЕРВЫЙ ВХОД (3 индикатора)</b>{symbol_str}\n"
            f"👤 {user_id}\n"
            f"🔹 {side_emoji} @ {price:.4f}\n"
            f"📦 Размер: {amount}\n"
            f"🎯 TP: {tp:.4f} (+{abs(tp/price - 1)*100:.2f}%)\n"
            f"🛑 SL: {sl:.4f} (-{abs(sl/price - 1)*100:.2f}%)\n\n"
            f"💡 <i>Сигнал {side.upper()} ({conf_text}):</i>\n"
            f"{bullets}"
        )

    def notify_entry_close(
        self,
        user_id: str,
        side: str,
        entry_price: float,
        close_price: float,
        pnl: float,
        reason: str,
        win_streak: int = 0,
        loss_streak: int = 0,
        symbol: str = "",
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
    ):
        pnl_emoji = "✅" if pnl > 0 else "❌"
        symbol_str = f"\n📊 <b>{symbol}</b>" if symbol else ""
        price_change_pct = (close_price - entry_price) / entry_price * 100
        if side == "short":
            price_change_pct = -price_change_pct
        streak = f"🏆 Серия побед: {win_streak}" if win_streak > 0 else f"💀 Серия убытков: {loss_streak}"

        tp_str = f" (уровень: {tp_price:.4f})" if tp_price else ""
        sl_str = f" (уровень: {sl_price:.4f})" if sl_price else ""
        move_pct = abs(price_change_pct)

        reason_text = {
            "tp": f"🎯 Take Profit сработал{tp_str} — цена прошла {move_pct:.2f}% в нашу сторону",
            "sl": f"🛑 Stop Loss сработал{sl_str} — цена пошла {move_pct:.2f}% против позиции",
            "emergency_squeeze": f"🚨 Анти-сквиз — цена упала {move_pct:.1f}% против позиции, принудительный выход",
            "force_close": "⛔ Принудительное закрытие — бот остановлен или достигнут риск-лимит",
            "timeout": f"⏱ Таймаут — позиция висела слишком долго без движения, принудительное закрытие",
        }

        self._send_urgent(
            f"{pnl_emoji} <b>ПОЗИЦИЯ ЗАКРЫТА</b>{symbol_str}\n"
            f"👤 {user_id}\n"
            f"{'🟢' if side == 'long' else '🔴'} {side.upper()}\n"
            f"📥 Вход: {entry_price:.4f} → 📤 Выход: {close_price:.4f} ({price_change_pct:+.2f}%)\n"
            f"💰 PnL: <b>{pnl:+.4f} USDT</b>\n"
            f"{streak}\n\n"
            f"💡 <i>{reason_text.get(reason, reason)}</i>"
        )

    def notify_winloss_open(
        self,
        user_id: str,
        side: str,
        price: float,
        amount: float,
        tp: float,
        sl: float,
        reason: str = "",
        win_streak: int = 0,
        loss_streak: int = 0,
        symbol: str = "",
    ):
        """Уведомление об открытии позиции по Win/Loss системе."""
        side_emoji = "🟢 LONG" if side == "long" else "🔴 SHORT"
        symbol_str = f"\n📊 <b>{symbol}</b>" if symbol else ""

        if reason == "win_continue":
            reason_text = f"✅ Предыдущая сделка — WIN (серия: {win_streak}). Продолжаем {side.upper()}"
        elif reason == "loss_reverse":
            reason_text = f"❌ Предыдущая сделка — LOSS (серия: {loss_streak}). Переворот → {side.upper()}"
        else:
            reason_text = reason

        self._send_message(
            f"⚡ <b>ОТКРЫТА ПОЗИЦИЯ</b>{symbol_str}\n"
            f"👤 {user_id}\n"
            f"🔹 {side_emoji} @ {price:.4f}\n"
            f"📦 Размер: {amount}\n"
            f"🎯 TP: {tp:.4f} (+{abs(tp/price - 1)*100:.2f}%)\n"
            f"🛑 SL: {sl:.4f} (-{abs(sl/price - 1)*100:.2f}%)\n\n"
            f"💡 <i>{reason_text}</i>"
        )

    # ──────────────────────────────────────────
    #  GRID стратегия
    # ──────────────────────────────────────────

    def notify_grid_setup(
        self,
        user_id: str,
        price: float,
        range_low: float,
        range_high: float,
        levels: int,
        allocated: float,
    ):
        self._send_message(
            f"🔲 <b>GRID: Сетка активирована</b>\n"
            f"👤 {user_id}\n"
            f"💲 Центр: {price:.4f}\n"
            f"📏 Диапазон: {range_low:.4f} — {range_high:.4f}\n"
            f"🔢 Уровней: {levels}\n"
            f"💰 Выделено: {allocated:.2f} USDT\n\n"
            f"💡 <i>Рынок во флэте — бот расставил сетку ордеров.\n"
            f"Покупает дешевле, продаёт дороже в заданном коридоре.</i>"
        )

    def notify_grid_breakout(self, user_id: str, price: float, pnl: float):
        self._send_message(
            f"💥 <b>GRID: Выход из диапазона</b>\n"
            f"👤 {user_id}\n"
            f"💲 Цена: {price:.4f}\n"
            f"💰 PnL сетки: {pnl:+.4f} USDT\n\n"
            f"💡 <i>Цена вышла за границы коридора — все ордера закрыты.\n"
            f"Бот переоценит рынок на следующем тике.</i>"
        )

    def notify_tick_summary(
        self, user_id: str, tick: int, price: float,
        mode: str, daily_pnl: str, drawdown: str, symbol: str = "",
    ):
        symbol_str = f"\n📊 Пара: <b>{symbol}</b>" if symbol else ""
        self._send_message(
            f"📊 <b>Сводка</b>\n"
            f"👤 {user_id}{symbol_str}\n"
            f"💰 Цена: {price:.4f}\n"
            f"⚙️ Режим: {mode}\n"
            f"📉 Дневной PnL: {daily_pnl} | Просадка: {drawdown}"
        )

    def notify_loss_streak_reset(self, user_id: str, symbol: str = ""):
        sym = f" [{symbol}]" if symbol else ""
        self._send_message(
            f"🔄 <b>Сброс после 10 убытков{sym}</b>\n"
            f"👤 {user_id}\n"
            f"📊 Серия из 10 минусовых сделок подряд.\n"
            f"🔍 Жду новый сигнал по RSI + MACD + BB для входа."
        )

    # ──────────────────────────────────────────
    #  Изменение настроек через веб-интерфейс
    # ──────────────────────────────────────────

    def notify_settings_changed(
        self,
        old: dict,
        new: dict,
        pairs: list = None,
        user_id: str = "",
    ):
        """
        Уведомление об изменении настроек.
        Показывает только изменившиеся параметры в формате: было → стало.
        Если ничего не изменилось — не отправляет.
        """
        LABELS = {
            "tp_pct":       ("TP",       100, "%"),
            "sl_pct":       ("SL",       100, "%"),
            "position_pct": ("Позиция",  100, "%"),
        }

        lines = []

        if not pairs:
            # Глобальное изменение — сравниваем top-level значения
            for key, (label, mult, unit) in LABELS.items():
                old_v = round(float(old.get(key, 0)) * mult, 2)
                new_v = round(float(new.get(key, 0)) * mult, 2)
                if abs(old_v - new_v) > 0.001:
                    lines.append(f"  {label}: {old_v}{unit} → <b>{new_v}{unit}</b>")
            # Плечо (целое число, отдельная обработка)
            old_lev = int(old.get("leverage", 3))
            new_lev = int(new.get("leverage", 3))
            if old_lev != new_lev:
                lines.append(f"  Плечо: x{old_lev} → <b>x{new_lev}</b>")
        else:
            # Переопределение для конкретных пар
            old_overrides = old.get("pair_overrides", {})
            new_overrides = new.get("pair_overrides", {})
            for sym in pairs:
                old_sym = old_overrides.get(sym, {})
                new_sym = new_overrides.get(sym, {})
                sym_lines = []
                for key, (label, mult, unit) in LABELS.items():
                    if key == "position_pct":
                        continue  # overrides не содержат position_pct
                    # Если старого override не было — сравниваем с глобальным значением
                    old_v = round(float(old_sym.get(key, old.get(key, 0))) * mult, 2)
                    new_v = round(float(new_sym.get(key, new.get(key, 0))) * mult, 2)
                    if abs(old_v - new_v) > 0.001:
                        sym_lines.append(f"    {label}: {old_v}{unit} → <b>{new_v}{unit}</b>")
                if sym_lines:
                    lines.append(f"  📊 <b>{sym}:</b>")
                    lines.extend(sym_lines)

        if not lines:
            logger.debug("[TG] notify_settings_changed: diff пустой, уведомление не отправлено")
            return  # Реально ничего не изменилось — не шлём

        pairs_str = ", ".join(pairs) if pairs else "все пары"
        user_str  = f"\n👤 {user_id}" if user_id else ""

        self._send_urgent(
            f"⚙️ <b>Настройки обновлены</b>{user_str}\n"
            f"📊 Применено: {pairs_str}\n\n"
            + "\n".join(lines)
        )
