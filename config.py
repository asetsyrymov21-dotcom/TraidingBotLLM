# ============================================================
#  Smart Adaptive Trading System — config.py
#  Все настройки системы в одном месте
# ============================================================

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ──────────────────────────────────────────
#  Биржи
# ──────────────────────────────────────────
SUPPORTED_EXCHANGES = ["binance", "bybit"]

# ──────────────────────────────────────────
#  Настройки по умолчанию для стратегий
# ──────────────────────────────────────────

@dataclass
class MarketAnalyzerConfig:
    """Параметры анализа рынка (RSI / MACD / BB)"""
    candle_limit: int = 100             # Кол-во свечей (RSI+MACD+BB достаточно 100)
    timeframe: str = "1m"               # Таймфрейм анализа
    volume_filter_period: int = 20      # Средний объём за N свечей для фильтра входа


@dataclass
class GridConfig:
    """Параметры GRID-стратегии"""
    grid_levels: int = 10               # Кол-во уровней сетки
    atr_multiplier: float = 0.5         # Ширина уровня = ATR * multiplier
    max_deposit_pct: float = 0.30       # Макс % депозита в GRID
    breakout_multiplier: float = 2.0    # Выход за ATR * X → закрыть сетку
    min_profit_pct: float = 0.003       # Мин прибыль на уровень (0.3%)


@dataclass
class TrendBotConfig:
    """Параметры трендового бота"""
    tp_pct: float = 0.005              # Take Profit 0.5%
    sl_pct: float = 0.04               # Stop Loss 4%
    trail_pct: float = 0.006           # Trailing Stop: отступ от лучшей цены 0.6%
    trail_activate_pct: float = 0.004  # Trailing активируется при прибыли 0.4%
    max_hold_minutes: int = 240        # Макс время удержания позиции (4 часа)
    base_position_pct: float = 0.05    # Базовый размер позиции 5%
    max_position_pct: float = 0.15     # Макс позиция 15%
    min_position_pct: float = 0.02     # Мин позиция 2%
    win_scale_up: float = 1.2          # Множитель при серии побед
    loss_scale_down: float = 0.8       # Множитель при серии убытков
    loss_streak_pause: int = 10        # Пауза после N убытков подряд
    pause_candles: int = 3             # Пауза в свечах после убытка
    delay_after_loss: int = 1          # Задержка свечей после убытка
    squeeze_threshold: float = 0.15    # Резкое движение против позиции > 15% → закрыть
    max_atr_multiplier: float = 3.0    # Аномальная волатильность (ATR * X)
    rsi_long_min: float = 45.0         # RSI минимум для лонга (фильтр)
    rsi_short_max: float = 55.0        # RSI максимум для шорта (фильтр)


@dataclass
class EntryBotConfig:
    """Параметры бота умного входа"""
    rsi_period: int = 14
    rsi_long_threshold: float = 50.0   # RSI > 50 → Long
    rsi_short_threshold: float = 50.0  # RSI < 50 → Short
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    tp_pct: float = 0.005              # TP 0.5%
    sl_pct: float = 0.04               # SL 4%
    position_pct: float = 0.05         # 5% депозита на каждую пару
    emergency_squeeze_pct: float = 0.15  # Экстренное закрытие при движении -15% против позиции
    max_hold_minutes: int = 240        # Макс время удержания позиции (4 часа)


@dataclass
class RiskConfig:
    """Глобальные параметры риска"""
    max_daily_loss_pct: float = 0.05   # Макс дневной убыток 5%
    max_drawdown_pct: float = 0.15     # Макс просадка 15%
    commission_rate: float = 0.001     # Комиссия биржи 0.1%


@dataclass
class TelegramConfig:
    """Настройки Telegram-уведомлений"""
    bot_token: str = ""                    # Токен от @BotFather
    chat_id: str = ""                      # ID чата (узнать через @userinfobot)
    enabled: bool = False                  # Включить/выключить уведомления
    tick_summary_interval: int = 4         # Отправлять саммари каждые N тиков (0 = выкл); 4 тика × 15мин = 1 час


@dataclass
class SystemConfig:
    """Системные настройки бота"""
    market_analyzer: MarketAnalyzerConfig = field(default_factory=MarketAnalyzerConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    trend_bot: TrendBotConfig = field(default_factory=TrendBotConfig)
    entry_bot: EntryBotConfig = field(default_factory=EntryBotConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    log_level: str = "INFO"
    log_file: str = "bot.log"
    data_dir: str = "data"


# ──────────────────────────────────────────
#  Профиль пользователя
# ──────────────────────────────────────────

@dataclass
class UserProfile:
    """Настройки конкретного пользователя"""
    user_id: str
    exchange: str                          # "binance" или "bybit"
    api_key: str
    api_secret: str
    symbol: str = "BTC/USDT"             # Одна пара (backward compat)
    symbols: List[str] = field(default_factory=list)  # Список пар (мультипарный режим)
    top_n_symbols: int = 5               # Сколько топ-пар выбирать автоматически (0 = ручной список)
    leverage: int = 3
    deposit_pct: float = 0.10             # % депозита на торговлю (суммарно на все пары)
    commission_pct: float = 0.20          # Комиссия системы с прибыли
    strategy_override: Optional[str] = None  # Принудительная стратегия
    is_testnet: bool = False
    custom_config: Optional[Dict] = None  # Переопределение параметров
    telegram_chat_id: str = ""            # Личный chat_id пользователя в Telegram

    def get_active_symbols(self) -> List[str]:
        """
        Возвращает список активных пар.
        Приоритет: symbols (если задан) → [symbol] (backward compat).
        При top_n_symbols > 0 список заполняется SymbolScanner'ом снаружи.
        """
        if self.symbols:
            return list(self.symbols)
        return [self.symbol]

    def per_pair_deposit_pct(self, n_pairs: int) -> float:
        """
        % депозита на одну пару при торговле n_pairs парами параллельно.
        Суммарный deposit_pct делится равномерно.
        """
        if n_pairs <= 1:
            return self.deposit_pct
        return self.deposit_pct / n_pairs

    def get_effective_config(self, base: SystemConfig) -> SystemConfig:
        """Возвращает конфиг с учётом пользовательских переопределений"""
        if not self.custom_config:
            return base
        import copy
        cfg = copy.deepcopy(base)
        cc = self.custom_config
        if "tp_pct" in cc:
            cfg.trend_bot.tp_pct = cc["tp_pct"]
            cfg.entry_bot.tp_pct = cc["tp_pct"]
        if "sl_pct" in cc:
            cfg.trend_bot.sl_pct = cc["sl_pct"]
            cfg.entry_bot.sl_pct = cc["sl_pct"]
        if "deposit_pct" in cc:
            cfg.trend_bot.base_position_pct = cc["deposit_pct"]
            cfg.entry_bot.position_pct = cc["deposit_pct"]
        return cfg
