# ============================================================
#  Smart Adaptive Trading System — strategies/adx_logic.py
#  Торговая логика на основе ADX + +DI / -DI
# ============================================================
#
#  Принципы:
#  - ADX = сила тренда (не направление)
#  - Направление = соотношение +DI и -DI
#  - Динамика ADX (растёт/падает) меняет агрессивность
#  - Шум = пересечение DI при слабом ADX → no_trade
#  - При ослаблении тренда — не входим, думаем о выходе
# ============================================================

from dataclasses import dataclass
from typing import Literal

Signal   = Literal["long", "short", "hold", "exit_long", "exit_short", "no_trade"]
Position = Literal["long", "short", "none"]


@dataclass
class ADXConfig:
    """
    Все пороги ADX-логики в одном месте.
    Можно переопределить при создании TrendStrategy.
    """
    adx_strong: float    = 25.0  # ADX ≥ → тренд подтверждён, входы разрешены
    adx_weak: float      = 20.0  # ADX < → нет тренда, не торгуем
    adx_delta_min: float = 0.3   # мин. изменение ADX чтобы считать его растущим/падающим

    di_noise_thr: float  = 5.0   # |+DI − −DI| < → шум, сигнал ненадёжен
    di_clear_thr: float  = 10.0  # |+DI − −DI| ≥ → чёткий сигнал направления
    di_exit_thr:  float  = 3.0   # DI сближаются ниже этого при падающем ADX → выход


def adx_signal(
    adx: float,
    prev_adx: float,
    plus_di: float,
    minus_di: float,
    position: Position = "none",
    cfg: ADXConfig = None,
) -> Signal:
    """
    Главная функция торговой логики ADX + DI.

    Args:
        adx      : текущий ADX
        prev_adx : ADX предыдущей свечи (для определения динамики)
        plus_di  : +DI — давление покупателей
        minus_di : -DI — давление продавцов
        position : текущая открытая позиция ("long" / "short" / "none")
        cfg      : пороги (ADXConfig); если None — используются дефолтные

    Returns:
        "long"       — открыть/удержать лонг
        "short"      — открыть/удержать шорт
        "hold"       — держать текущую позицию, тренд ещё жив
        "exit_long"  — закрыть лонг (DI развернулись или тренд угасает)
        "exit_short" — закрыть шорт
        "no_trade"   — зона шума / нет подтверждения / ADX слаб

    Приоритет решений:
        EXIT > NO_TRADE > HOLD > ENTRY
    """
    if cfg is None:
        cfg = ADXConfig()

    # ── 1. Динамика ADX ────────────────────────────────────
    adx_delta   = adx - prev_adx
    adx_rising  = adx_delta >  cfg.adx_delta_min   # тренд усиливается
    adx_falling = adx_delta < -cfg.adx_delta_min   # тренд слабеет
    # adx_flat  = not rising and not falling        # неопределённость

    # ── 2. Зона ADX (сила тренда) ──────────────────────────
    is_weak       = adx < cfg.adx_weak                           # < 20
    is_transition = cfg.adx_weak <= adx < cfg.adx_strong        # 20–25
    is_strong     = adx >= cfg.adx_strong                       # ≥ 25

    # ── 3. Направление и сила DI ───────────────────────────
    di_spread = plus_di - minus_di   # > 0 = бычий, < 0 = медвежий
    di_abs    = abs(di_spread)
    bullish   = di_spread > 0        # покупатели доминируют
    bearish   = di_spread < 0        # продавцы доминируют

    is_noise     = di_abs < cfg.di_noise_thr                    # шум
    is_clear     = cfg.di_noise_thr <= di_abs < cfg.di_clear_thr  # чёткий
    is_strong_di = di_abs >= cfg.di_clear_thr                   # сильный

    # ══════════════════════════════════════════════════════
    #  4. EXIT — наивысший приоритет
    #     Проверяем ДО входных сигналов
    # ══════════════════════════════════════════════════════
    if position == "long":
        # DI развернулись против позиции — медведи берут контроль
        if bearish and (is_clear or is_strong_di):
            return "exit_long"
        # Тренд угасает: ADX падает и DI почти нейтральны (сближаются)
        if adx_falling and di_abs < cfg.di_exit_thr:
            return "exit_long"

    if position == "short":
        # DI развернулись — быки берут контроль
        if bullish and (is_clear or is_strong_di):
            return "exit_short"
        if adx_falling and di_abs < cfg.di_exit_thr:
            return "exit_short"

    # ══════════════════════════════════════════════════════
    #  5. NO-TRADE ZONE
    # ══════════════════════════════════════════════════════

    # Нет тренда вообще
    if is_weak:
        return "no_trade"

    # DI-пересечение при слабом разрыве → шум, не реагируем
    if is_noise:
        return "no_trade"

    # ADX высокий, но слабеет + DI не даёт чёткого сигнала
    # → тренд ещё не умер, но открываться уже поздно
    if is_strong and adx_falling and not is_strong_di:
        return "no_trade"

    # ══════════════════════════════════════════════════════
    #  6. HOLD — позиция открыта и тренд ещё за нас
    # ══════════════════════════════════════════════════════
    if position == "long"  and bullish:
        return "hold"
    if position == "short" and bearish:
        return "hold"

    # ══════════════════════════════════════════════════════
    #  7. ENTRY — открываем новую позицию
    # ══════════════════════════════════════════════════════

    # Основная зона: сильный ADX и растёт → входим при чётком DI
    if is_strong and adx_rising:
        if bullish and (is_clear or is_strong_di):
            return "long"
        if bearish and (is_clear or is_strong_di):
            return "short"

    # Переходная зона (20–25): только при очень сильном DI сигнале
    if is_transition and adx_rising and is_strong_di:
        if bullish:
            return "long"
        if bearish:
            return "short"

    # ADX силён, но не растёт → не открываем, только держим
    if is_strong and not adx_rising and position != "none":
        return "hold"

    return "no_trade"


# ══════════════════════════════════════════════════════════
#  Встроенные тесты (python strategies/adx_logic.py)
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    cases = [
        # adx  prev  +DI  -DI   pos      ожидание
        (28,   26,   22,   9,  "none",  "long"),        # сильный тренд, растёт, быки
        (28,   26,    9,  22,  "none",  "short"),       # сильный тренд, растёт, медведи
        (18,   17,   25,   8,  "none",  "no_trade"),    # ADX < 20 → нет тренда
        (30,   33,   14,  12,  "long",  "exit_long"),   # ADX падает, DI нейтральны
        (30,   28,    8,  21,  "long",  "exit_long"),   # DI развернулись против лонга
        (27,   25,   18,   7,  "long",  "hold"),        # тренд жив, держим лонг
        (26,   28,   14,  12,  "none",  "no_trade"),    # ADX падает, DI нечёткий
        (22,   20,   20,   7,  "none",  "long"),        # transition + сильный DI
        (24,   22,    8,   6,  "none",  "no_trade"),    # transition, DI слабый (clear но не strong)
        (29,   27,    7,  20,  "short", "hold"),        # тренд жив, держим шорт
        (31,   29,   18,   6,  "short", "exit_short"),  # DI развернулись против шорта
        (19,   18,   30,   5,  "long",  "no_trade"),    # ADX слаб → выход НЕ по ADX-сигналу, no_trade
    ]

    cfg = ADXConfig()
    all_ok = True
    for adx, prev, pdi, mdi, pos, expected in cases:
        result = adx_signal(adx, prev, pdi, mdi, pos, cfg)
        ok = result == expected
        mark = "✅" if ok else "❌"
        if not ok:
            all_ok = False
        print(
            f"{mark}  ADX={adx}(Δ{adx - prev:+.0f}) "
            f"+DI={pdi:>4} -DI={mdi:>4} "
            f"pos={pos:<6} → {result:<12} (ожид: {expected})"
        )

    print()
    print("✅ Все тесты прошли!" if all_ok else "❌ Есть расхождения — проверь логику")
