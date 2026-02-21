"""Функции форматирования текста."""
from database.models import KbjuSettings


def format_kbju_goal_text(calories: float, protein: float, fat: float, carbs: float, goal_label: str) -> str:
    """Форматирует текст с целью КБЖУ."""
    return (
        "🎯 Я настроил твою дневную норму КБЖУ!\n\n"
        f"🔥 Калории: <b>{calories:.0f} ккал</b>\n"
        f"💪 Белки: <b>{protein:.0f} г</b>\n"
        f"🧈 Жиры: <b>{fat:.0f} г</b>\n"
        f"🍞 Углеводы: <b>{carbs:.0f} г</b>\n\n"
        f"Цель: <b>{goal_label}</b>\n\n"
        "Теперь в разделе КБЖУ я буду сравнивать твой рацион с этой целью.\n"
        "В любой момент можно изменить параметры через кнопку «🎯 Цель / Норма КБЖУ»."
    )


def get_kbju_goal_label(goal: str | None) -> str:
    """Возвращает читаемое название цели КБЖУ."""
    labels = {
        "loss": "Похудение",
        "maintain": "Поддержание веса",
        "gain": "Набор массы",
    }
    if goal in labels:
        return labels[goal]
    if goal:
        return goal
    return "Своя норма"


def format_current_kbju_goal(settings: KbjuSettings) -> str:
    """Форматирует текущую цель КБЖУ."""
    goal_label = get_kbju_goal_label(settings.goal)
    return (
        "🎯 Твоя текущая цель по КБЖУ:\n\n"
        f"🔥 Калории: <b>{settings.calories:.0f} ккал</b>\n"
        f"💪 Белки: <b>{settings.protein:.0f} г</b>\n"
        f"🧈 Жиры: <b>{settings.fat:.0f} г</b>\n"
        f"🍞 Углеводы: <b>{settings.carbs:.0f} г</b>\n\n"
        f"Цель: <b>{goal_label}</b>"
    )


def format_count_with_unit(count: int | float, variant: str | None) -> str:
    """Форматирует количество с единицей измерения."""
    if variant == "раз":
        return f"{count} раз"
    elif variant == "сек":
        return f"{count} сек"
    elif variant == "мин":
        return f"{count} мин"
    elif variant == "км":
        return f"{count} км"
    elif variant == "м":
        return f"{count} м"
    else:
        return str(count)

