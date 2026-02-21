"""Утилиты для работы с тренировками."""
import logging
from typing import Optional
from database.repositories import WeightRepository

logger = logging.getLogger(__name__)


def estimate_met_for_exercise(exercise: str) -> float:
    """
    Оценивает MET (Metabolic Equivalent of Task) для упражнения.
    MET - это единица измерения энергетических затрат.
    """
    met_values = {
        # С собственным весом
        "Подтягивания": 3.0,
        "Отжимания": 3.5,
        "Приседания": 5.0,
        "Пресс": 3.0,
        "Берпи": 8.0,
        "Шаги": 3.0,
        "Шаги (Ходьба)": 3.0,
        "Пробежка": 7.0,
        "Скакалка": 10.0,
        "Становая тяга без утяжелителя": 4.0,
        "Румынская тяга без утяжелителя": 4.0,
        "Планка": 3.0,
        "Йога": 2.5,
        
        # С утяжелителем
        "Приседания со штангой": 6.0,
        "Жим штанги лёжа": 5.0,
        "Становая тяга с утяжелителем": 6.0,
        "Румынская тяга с утяжелителем": 5.0,
        "Тяга штанги в наклоне": 5.0,
        "Жим гантелей лёжа": 5.0,
        "Жим гантелей сидя": 4.0,
        "Подъёмы гантелей на бицепс": 3.0,
        "Тяга верхнего блока": 4.0,
        "Тяга нижнего блока": 4.0,
        "Жим ногами": 5.0,
        "Разведения гантелей": 3.0,
        "Тяга горизонтального блока": 4.0,
        "Сгибание ног в тренажёре": 3.0,
        "Разгибание ног в тренажёре": 3.0,
        "Гиперэкстензия с утяжелителем": 4.0,
    }
    
    # Старая логика: только точные соответствия, иначе дефолт 3.0
    return met_values.get(exercise, 3.0)


def calculate_workout_calories(
    user_id: str,
    exercise: str,
    variant: Optional[str],
    count: int,
) -> float:
    """
    Вычисляет примерные калории, сожжённые на тренировке (старая формула).

    Старая формула из проекта:
    калории = MET × вес(кг) × время(часы)

    - Если variant указывает на секунды/минуты — переводим в часы и считаем по времени.
    - Иначе (включая шаги и повторы) — старая грубая оценка по количеству:
      duration_hours = (count / 100) * 0.1  (≈ 0.1 часа на 100 повторений/условных единиц)
    """
    weight = WeightRepository.get_last_weight(user_id) or 70.0
    met = estimate_met_for_exercise(exercise)

    try:
        value = float(count or 0)
    except (TypeError, ValueError):
        value = 0.0

    v = (variant or "").strip().lower()

    # Время: секунды
    if v in {"сек", "сек.", "секунды", "seconds", "second", "seconds."} or (variant == "Секунды"):
        duration_hours = value / 3600.0
        return max(met * weight * duration_hours, 0.0)

    # Время: минуты
    if v in {"мин", "мин.", "минуты", "minutes", "minute", "minutes."} or (variant == "Минуты"):
        duration_hours = value / 60.0
        return max(met * weight * duration_hours, 0.0)

    # Шаги: специальная формула на основе ориентира 16705 шагов = 634 ккал
    if (
        v in {"количество шагов", "шаги", "steps"}
        or (variant == "Количество шагов")
        or (exercise in {"Шаги", "Шаги (Ходьба)"})
    ):
        # Формула: калории = шаги × (634 / 16705) × (вес / 70)
        # 634 / 16705 ≈ 0.03796 ккал на шаг при весе 70 кг
        base_calories_per_step = 634.0 / 16705.0  # ≈ 0.03796
        base_weight = 70.0
        calories = value * base_calories_per_step * (weight / base_weight)
        return max(calories, 0.0)

    # Всё остальное (повторы / иные варианты)
    duration_hours = (value / 100.0) * 0.1
    return max(met * weight * duration_hours, 0.0)


def get_daily_workout_calories(user_id: str, entry_date) -> float:
    """Получает суммарные калории, сожжённые на тренировках за день."""
    from database.repositories import WorkoutRepository
    
    workouts = WorkoutRepository.get_workouts_for_day(user_id, entry_date)
    total = 0.0
    
    for w in workouts:
        if w.calories:
            total += w.calories
        else:
            total += calculate_workout_calories(user_id, w.exercise, w.variant, w.count)
    
    return total
