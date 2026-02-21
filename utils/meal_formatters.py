"""Функции форматирования для приёмов пищи."""
import logging
import json
import html
from datetime import date
from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.repositories import MealRepository
from database.models import Meal

logger = logging.getLogger(__name__)


def format_today_meals(meals: list[Meal], daily_totals: dict, day_str: str) -> str:
    """Форматирует список приёмов пищи за день."""
    lines: list[str] = []
    lines.append(f"Приём пищи за {day_str}:\n")
    
    for idx, meal in enumerate(meals, start=1):
        # Что вводил пользователь
        user_text = getattr(meal, "raw_query", None) or meal.description or "Без описания"
        
        # Заголовок "Ты ввёл(а):" жирным через HTML
        lines.append(f"{idx}) 📝 <b>Ты ввёл(а):</b> {html.escape(user_text)}")
        
        api_details = getattr(meal, "api_details", None)
        
        if api_details:
            # "Результат:" жирным
            lines.append("🔍 <b>Результат:</b>")
            # api_details уже готовый текст, не экранируем
            lines.append(api_details)
        else:
            # Что мы показывали раньше как распознанный текст
            api_text_fallback = meal.description or "нет описания"
            
            # Пробуем достать продукты из JSON
            products = []
            raw_products = getattr(meal, "products_json", None)
            if raw_products:
                try:
                    products = json.loads(raw_products)
                except Exception as e:
                    logger.warning(f"Не смог распарсить products_json: {e}")
            
            if products:
                lines.append("🔍 <b>Результат:</b>")
                for p in products:
                    name = p.get("name_ru") or p.get("name") or "продукт"
                    
                    # Поддержка разных форматов данных (CalorieNinjas и Gemini API)
                    # CalorieNinjas использует: _calories, _protein_g, _fat_total_g, _carbohydrates_total_g
                    # Gemini API использует: kcal, protein, fat, carbs, grams
                    cal = (p.get("calories") or p.get("_calories") or 
                           p.get("kcal") or 0)
                    prot = (p.get("protein_g") or p.get("_protein_g") or 
                            p.get("protein") or 0)
                    fat = (p.get("fat_total_g") or p.get("_fat_total_g") or 
                           p.get("fat") or 0)
                    carb = (p.get("carbohydrates_total_g") or p.get("_carbohydrates_total_g") or 
                            p.get("carbs") or 0)
                    
                    # Если есть вес, показываем его
                    grams = p.get("grams") or p.get("weight")
                    if grams:
                        lines.append(
                            f"• {html.escape(name)} ({grams:.0f} г) — {cal:.0f} ккал "
                            f"(Б {prot:.1f} / Ж {fat:.1f} / У {carb:.1f})"
                        )
                    else:
                        lines.append(
                            f"• {html.escape(name)} — {cal:.0f} ккал "
                            f"(Б {prot:.1f} / Ж {fat:.1f} / У {carb:.1f})"
                        )
            else:
                # Старый вариант без products_json
                lines.append(
                    f"🔍 <b>Результат:</b> {html.escape(api_text_fallback)}"
                )
        
        # Итого по этому приёму
        lines.append(f"🔥 Калории: {meal.calories:.0f} ккал")
        lines.append(f"💪 Белки: {meal.protein:.1f} г")
        lines.append(f"🥑 Жиры: {meal.fat:.1f} г")
        lines.append(f"🍩 Углеводы: {meal.carbs:.1f} г")
        lines.append("— — — — —")
    
    # Итоги за день — тоже жирным
    lines.append("\n<b>Итого за день:</b>")
    lines.append(f"🔥 Калории: {daily_totals.get('calories', 0):.0f} ккал")
    lines.append(f"💪 Белки: {daily_totals.get('protein_g', daily_totals.get('protein', 0)):.1f} г")
    lines.append(f"🥑 Жиры: {daily_totals.get('fat_total_g', daily_totals.get('fat', 0)):.1f} г")
    lines.append(f"🍩 Углеводы: {daily_totals.get('carbohydrates_total_g', daily_totals.get('carbs', 0)):.1f} г")
    
    return "\n".join(lines)


def build_meals_actions_keyboard(
    meals: list[Meal],
    target_date: date,
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """Строит клавиатуру с действиями для приёмов пищи."""
    rows: list[list[InlineKeyboardButton]] = []
    for idx, meal in enumerate(meals, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {idx}",
                    callback_data=f"meal_edit:{meal.id}:{target_date.isoformat()}",
                ),
                InlineKeyboardButton(
                    text=f"🗑 {idx}",
                    callback_data=f"meal_del:{meal.id}:{target_date.isoformat()}",
                ),
            ]
        )
    
    if include_back:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Добавить",
                    callback_data=f"meal_cal_add:{target_date.isoformat()}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️ Назад к календарю",
                    callback_data=f"meal_cal_back:{target_date.year}-{target_date.month:02d}",
                )
            ]
        )
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_kbju_day_actions_keyboard(target_date: date) -> InlineKeyboardMarkup:
    """Строит клавиатуру действий для дня в календаре КБЖУ."""
    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="➕ Добавить приём",
                callback_data=f"meal_cal_add:{target_date.isoformat()}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад к календарю",
                callback_data=f"meal_cal_back:{target_date.year}-{target_date.month:02d}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
