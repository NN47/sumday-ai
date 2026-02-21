"""Обработчики для анализа деятельности."""
import logging
import re
from datetime import date, timedelta
from collections import Counter
from aiogram import Router
from aiogram.types import Message
from utils.keyboards import activity_analysis_menu, push_menu_stack
from services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

router = Router()


async def generate_activity_analysis(user_id: str, start_date: date, end_date: date, period_name: str) -> str:
    """Генерирует анализ активности за указанный период через Gemini."""
    from database.repositories import (
        WorkoutRepository, MealRepository, WeightRepository,
        WaterRepository, SupplementRepository, ProcedureRepository,
        WellbeingRepository
    )
    from utils.workout_utils import calculate_workout_calories
    from utils.formatters import format_count_with_unit, get_kbju_goal_label
    
    days_count = (end_date - start_date).days + 1
    
    # 🔹 Тренировки за период
    workouts = WorkoutRepository.get_workouts_for_period(user_id, start_date, end_date)
    
    workouts_by_ex = {}
    total_workout_calories = 0.0
    workout_days = set()
    
    for w in workouts:
        key = (w.exercise, w.variant)
        entry = workouts_by_ex.setdefault(key, {"count": 0, "calories": 0.0})
        entry["count"] += w.count
        cals = w.calories or calculate_workout_calories(user_id, w.exercise, w.variant, w.count)
        entry["calories"] += cals
        total_workout_calories += cals
        workout_days.add(w.date)
    
    workout_days_count = len(workout_days)
    avg_workout_calories = total_workout_calories / workout_days_count if workout_days_count > 0 else 0
    
    if workouts_by_ex:
        workout_lines = []
        for (exercise, variant), data in workouts_by_ex.items():
            formatted_count = format_count_with_unit(data["count"], variant)
            variant_text = f" ({variant})" if variant else ""
            workout_lines.append(
                f"- {exercise}{variant_text}: {formatted_count}, ~{data['calories']:.0f} ккал"
            )
        workout_summary = "\n".join(workout_lines)
        workout_summary += f"\n\nВсего тренировочных дней: {workout_days_count} из {days_count} ({workout_days_count * 100 // days_count if days_count > 0 else 0}%)."
        workout_summary += f"\nСредний расход калорий за тренировочный день: ~{avg_workout_calories:.0f} ккал."
    else:
        workout_summary = f"За {period_name.lower()} тренировки не записаны."
    
    # 🔹 КБЖУ за период
    meals = []
    meal_days = set()
    current_date = start_date
    while current_date <= end_date:
        day_meals = MealRepository.get_meals_for_date(user_id, current_date)
        if day_meals:
            meals.extend(day_meals)
            meal_days.add(current_date)
        current_date += timedelta(days=1)
    
    total_calories = sum(m.calories or 0 for m in meals)
    total_protein = sum(m.protein or 0 for m in meals)
    total_fat = sum(m.fat or 0 for m in meals)
    total_carbs = sum(m.carbs or 0 for m in meals)
    
    # 🔹 Цель / норма КБЖУ и проценты выполнения
    settings = MealRepository.get_kbju_settings(user_id)
    if settings:
        goal_label = get_kbju_goal_label(settings.goal)
        goal_calories = settings.calories * days_count
        goal_protein = settings.protein * days_count
        goal_fat = settings.fat * days_count
        goal_carbs = settings.carbs * days_count
        
        calories_percent = (total_calories / goal_calories * 100) if goal_calories > 0 else 0
        protein_percent = (total_protein / goal_protein * 100) if goal_protein > 0 else 0
        fat_percent = (total_fat / goal_fat * 100) if goal_fat > 0 else 0
        carbs_percent = (total_carbs / goal_carbs * 100) if goal_carbs > 0 else 0
        
        meals_summary = (
            f"Калории: {total_calories:.0f} / {goal_calories:.0f} ккал ({calories_percent:.0f}%), "
            f"Белки: {total_protein:.1f} / {goal_protein:.1f} г ({protein_percent:.0f}%), "
            f"Жиры: {total_fat:.1f} / {goal_fat:.1f} г ({fat_percent:.0f}%), "
            f"Углеводы: {total_carbs:.1f} / {goal_carbs:.1f} г ({carbs_percent:.0f}%)."
        )
        
        kbju_goal_summary = (
            f"Цель: {goal_label}. "
            f"Дней с записями питания: {len(meal_days)} из {days_count} ({len(meal_days) * 100 // days_count if days_count > 0 else 0}%)."
        )
    else:
        meals_summary = (
            f"Калории: {total_calories:.0f} ккал, "
            f"Белки: {total_protein:.1f} г, "
            f"Жиры: {total_fat:.1f} г, "
            f"Углеводы: {total_carbs:.1f} г."
        )
        kbju_goal_summary = "Цель по КБЖУ ещё не настроена."
    
    # 🔹 Статистика по дням недели (для недели и месяца)
    weekday_stats = ""
    if days_count >= 7:
        from collections import defaultdict
        weekday_workouts = defaultdict(int)
        weekday_meals = defaultdict(int)
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        
        for w in workouts:
            weekday_workouts[w.date.weekday()] += 1
        for d in meal_days:
            weekday_meals[d.weekday()] += 1
        
        if weekday_workouts or weekday_meals:
            weekday_lines = []
            for day_idx in range(7):
                workout_count = weekday_workouts.get(day_idx, 0)
                meal_count = weekday_meals.get(day_idx, 0)
                if workout_count > 0 or meal_count > 0:
                    weekday_lines.append(
                        f"{weekday_names[day_idx]}: тренировок {workout_count}, дней с питанием {meal_count}"
                    )
            if weekday_lines:
                weekday_stats = "\nСтатистика по дням недели:\n" + "\n".join(weekday_lines)
    
    # 🔹 Вода за период
    total_water = 0.0
    water_days = set()
    current_date = start_date
    while current_date <= end_date:
        day_water = WaterRepository.get_daily_total(user_id, current_date)
        if day_water > 0:
            total_water += day_water
            water_days.add(current_date)
        current_date += timedelta(days=1)
    
    avg_water = total_water / len(water_days) if water_days else 0
    water_summary = ""
    if water_days:
        water_summary = (
            f"\nВода: всего {total_water:.0f} мл за период, "
            f"среднее {avg_water:.0f} мл/день, "
            f"дней с записями: {len(water_days)} из {days_count}."
        )
    
    # 🔹 Добавки за период
    supplements = SupplementRepository.get_supplements(user_id)
    supplement_summary = ""
    if supplements:
        supplement_entries_count = 0
        supplement_names = []
        for sup in supplements:
            for entry in sup.get("history", []):
                entry_date = entry["timestamp"].date() if hasattr(entry["timestamp"], "date") else entry["timestamp"]
                if start_date <= entry_date <= end_date:
                    supplement_entries_count += 1
                    if sup["name"] not in supplement_names:
                        supplement_names.append(sup["name"])
        
        if supplement_entries_count > 0:
            supplement_summary = (
                f"\nДобавки: {supplement_entries_count} приёмов, "
                f"активных добавок: {len(supplement_names)} ({', '.join(supplement_names[:3])}"
                f"{'...' if len(supplement_names) > 3 else ''})."
            )
    
    # 🔹 Процедуры за период
    procedure_count = 0
    current_date = start_date
    while current_date <= end_date:
        day_procedures = ProcedureRepository.get_procedures_for_day(user_id, current_date)
        procedure_count += len(day_procedures)
        current_date += timedelta(days=1)
    
    procedure_summary = ""
    if procedure_count > 0:
        procedure_summary = f"\nПроцедуры: {procedure_count} записей за период."

    # 🔹 Самочувствие за период
    wellbeing_entries = WellbeingRepository.get_entries_for_period(user_id, start_date, end_date)
    wellbeing_summary = ""
    if wellbeing_entries:
        quick_entries = [entry for entry in wellbeing_entries if entry.entry_type == "quick"]
        comment_entries = [
            entry for entry in wellbeing_entries if entry.entry_type == "comment" and entry.comment
        ]
        mood_counts = Counter(entry.mood for entry in quick_entries if entry.mood)
        influence_counts = Counter(entry.influence for entry in quick_entries if entry.influence)
        difficulty_counts = Counter(entry.difficulty for entry in quick_entries if entry.difficulty)

        mood_summary = ", ".join(
            f"{mood} — {count}" for mood, count in mood_counts.most_common()
        )
        influence_summary = ", ".join(
            f"{influence} — {count}" for influence, count in influence_counts.most_common()
        )
        difficulty_summary = ", ".join(
            f"{difficulty} — {count}" for difficulty, count in difficulty_counts.most_common()
        )

        wellbeing_parts = [
            f"Записей самочувствия: {len(wellbeing_entries)} "
            f"(быстрых опросов: {len(quick_entries)}, комментариев: {len(comment_entries)})."
        ]
        if mood_summary:
            wellbeing_parts.append(f"Настроение: {mood_summary}.")
        if influence_summary:
            wellbeing_parts.append(f"Что влияло чаще всего: {influence_summary}.")
        if difficulty_summary:
            wellbeing_parts.append(f"Сложности: {difficulty_summary}.")
        if comment_entries:
            latest_comment = comment_entries[0]
            wellbeing_parts.append(
                f"Последний комментарий ({latest_comment.date.strftime('%d.%m')}): {latest_comment.comment}."
            )
        wellbeing_summary = "\n" + " ".join(wellbeing_parts)
    else:
        wellbeing_summary = "\nСамочувствие: записей за период нет."
    
    # 🔹 Вес и история веса
    weights = WeightRepository.get_weights_for_date_range(user_id, start_date, end_date)
    
    if weights:
        current_weight = weights[0]
        if len(weights) > 1:
            first_weight = weights[-1]
            change = float(str(current_weight.value).replace(",", ".")) - float(str(first_weight.value).replace(",", "."))
            change_percent = (change / float(str(first_weight.value).replace(",", ".")) * 100) if float(str(first_weight.value).replace(",", ".")) > 0 else 0
            change_text = f" ({'+' if change >= 0 else ''}{change:.1f} кг, {change_percent:+.1f}%)"
        else:
            change_text = ""
        history_lines = [
            f"{w.date.strftime('%d.%m')}: {w.value} кг"
            for w in weights[:10]
        ]
        weight_summary = (
            f"Текущий вес: {current_weight.value} кг (от {current_weight.date.strftime('%d.%m.%Y')}){change_text}. "
            f"История измерений: " + "; ".join(history_lines)
        )
    else:
        # Если нет веса за период, показываем последний известный вес
        all_weights = WeightRepository.get_weights(user_id, limit=1)
        if all_weights:
            w = all_weights[0]
            weight_summary = f"Последний зафиксированный вес: {w.value} кг (от {w.date.strftime('%d.%m.%Y')}). За {period_name.lower()} новых измерений не было."
        else:
            weight_summary = "Записей по весу ещё нет."
    
    # 🔹 Сравнение с предыдущим периодом (для недели и месяца)
    comparison_summary = ""
    if days_count >= 7:
        prev_start = start_date - timedelta(days=days_count)
        prev_end = start_date - timedelta(days=1)
        
        prev_workouts = WorkoutRepository.get_workouts_for_period(user_id, prev_start, prev_end)
        prev_workout_days = len(set(w.date for w in prev_workouts))
        
        prev_meals = []
        prev_date = prev_start
        while prev_date <= prev_end:
            prev_meals.extend(MealRepository.get_meals_for_date(user_id, prev_date))
            prev_date += timedelta(days=1)
        prev_calories = sum(m.calories or 0 for m in prev_meals)
        
        if prev_workout_days > 0 or prev_calories > 0:
            workout_change = workout_days_count - prev_workout_days
            calories_change = total_calories - prev_calories
            
            comparison_lines = []
            if workout_change != 0:
                comparison_lines.append(f"Тренировочных дней: {workout_change:+d} к предыдущему периоду")
            if calories_change != 0:
                comparison_lines.append(f"Калорий: {calories_change:+.0f} ккал к предыдущему периоду")
            
            if comparison_lines:
                comparison_summary = "\n\nСравнение с предыдущим периодом:\n" + "\n".join(comparison_lines)
    
    # 🔹 Собираем summary для Gemini
    date_range_str = f"{start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"
    summary = f"""
Период: {period_name} ({date_range_str}), всего дней: {days_count}.

Тренировки за период:
{workout_summary}
Всего ориентировочно израсходовано: ~{total_workout_calories:.0f} ккал.{weekday_stats}

Питание (КБЖУ) за период:
{meals_summary}

Норма / цель КБЖУ:
{kbju_goal_summary}{water_summary}{supplement_summary}{procedure_summary}{wellbeing_summary}

Вес:
{weight_summary}{comparison_summary}
"""
    
    # 🔹 Промпт для робота Дайри
    prompt = f"""
Ты — робот Дайри 🤖, персональный фитнес-помощник пользователя.
Говори дружелюбно, уверенно и по делу.

Очень важно:
- Не считай количество записей тренировок, я уже дал тебе готовый текст по объёму и видам упражнений.
- Цель по КБЖУ уже указана в данных, не используй формулировки вроде "если твоя цель...".
- История веса может включать несколько измерений — используй её для оценки тенденции, не говори, что измерение одно, если в данных есть история.
- Используй HTML-теги <b>текст</b> для выделения важных цифр и фактов жирным шрифтом.
- Обрати внимание на проценты выполнения целей КБЖУ — выдели их жирным и дай оценку.
- Если есть сравнение с предыдущим периодом, обязательно упомяни это в анализе.
- Если есть статистика по дням недели, используй её для выявления паттернов активности.

Всегда начинай анализ с приветствия:
"Привет, это Дайри на связи! Вот твой отчёт {period_name.lower()}👇"

Данные пользователя за период:
{summary}

Сделай краткий отчёт по 4 блокам. ОБЯЗАТЕЛЬНО используй следующий формат для заголовков блоков (без решеток #, только жирный текст с эмодзи):
<b>1) 🏋️ Тренировки</b>
<b>2) 🍱 Питание (КБЖУ)</b>
<b>3) ⚖️ Вес</b>
<b>4) 📈 Общий прогресс и мотивация</b>

Пиши структурированно, но компактно. Используй <b>жирный шрифт</b> для выделения важных цифр, фактов и процентов выполнения целей.
Учитывай блок самочувствия и отражай его выводы в "Общий прогресс и мотивация" (или там, где это уместно).
В блоке "Общий прогресс и мотивация" дай конкретные рекомендации на основе данных: что улучшить, что работает хорошо, на что обратить внимание.

Рекомендации делай в стиле кнопки "🤖 Рекомендации", учитывай её принципы, но не вставляй текст или списки из неё дословно.
"""
    
    result = gemini_service.analyze(prompt)
    
    # Заменяем markdown звездочки на HTML-теги для жирного шрифта
    # Заменяем **текст** на <b>текст</b>
    result = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', result)
    # Заменяем оставшиеся одиночные звездочки в конце (если есть)
    result = re.sub(r'\*+$', '', result)
    
    return result


@router.message(lambda m: m.text == "🤖 ИИ анализ деятельности")
async def analyze_activity(message: Message):
    """Показывает меню анализа деятельности."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} opened activity analysis")
    push_menu_stack(message.bot, activity_analysis_menu)
    await message.answer(
        "🤖 <b>ИИ анализ деятельности</b>\n\nВыбери период для анализа:",
        parse_mode="HTML",
        reply_markup=activity_analysis_menu,
    )


@router.message(lambda m: m.text == "📅 Анализ за день")
async def analyze_activity_day(message: Message):
    """Анализ за день."""
    user_id = str(message.from_user.id)
    today = date.today()
    analysis = await generate_activity_analysis(user_id, today, today, "за день")
    push_menu_stack(message.bot, activity_analysis_menu)
    await message.answer(analysis, parse_mode="HTML", reply_markup=activity_analysis_menu)


@router.message(lambda m: m.text == "📆 Анализ за неделю")
async def analyze_activity_week(message: Message):
    """Анализ за неделю."""
    user_id = str(message.from_user.id)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    analysis = await generate_activity_analysis(user_id, week_start, today, "за неделю")
    push_menu_stack(message.bot, activity_analysis_menu)
    await message.answer(analysis, parse_mode="HTML", reply_markup=activity_analysis_menu)


@router.message(lambda m: m.text == "📊 Анализ за месяц")
async def analyze_activity_month(message: Message):
    """Анализ за месяц."""
    user_id = str(message.from_user.id)
    today = date.today()
    month_start = date(today.year, today.month, 1)
    analysis = await generate_activity_analysis(user_id, month_start, today, "за месяц")
    push_menu_stack(message.bot, activity_analysis_menu)
    await message.answer(analysis, parse_mode="HTML", reply_markup=activity_analysis_menu)


@router.message(lambda m: m.text == "📈 Анализ за все время")
async def analyze_activity_all_time(message: Message):
    """Анализ за все время."""
    user_id = str(message.from_user.id)
    today = date.today()
    # Берём последние 365 дней
    all_time_start = today - timedelta(days=365)
    analysis = await generate_activity_analysis(user_id, all_time_start, today, "за все время")
    push_menu_stack(message.bot, activity_analysis_menu)
    await message.answer(analysis, parse_mode="HTML", reply_markup=activity_analysis_menu)


def register_activity_handlers(dp):
    """Регистрирует обработчики анализа деятельности."""
    dp.include_router(router)
