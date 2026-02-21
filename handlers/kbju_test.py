"""Обработчики для теста КБЖУ."""
import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from states.user_states import KbjuTestStates
from utils.keyboards import (
    kbju_gender_menu,
    kbju_activity_menu,
    kbju_goal_menu,
    kbju_menu,
    push_menu_stack,
)
from services.kbju_calculator import calculate_kbju_from_test
from database.repositories import MealRepository
from utils.formatters import format_kbju_goal_text

logger = logging.getLogger(__name__)

router = Router()


@router.message(lambda m: m.text == "🎯 Цель / Норма КБЖУ")
async def show_kbju_goal(message: Message, state: FSMContext):
    """Показывает текущую цель КБЖУ или предлагает пройти тест."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} opened KBJU goal settings")
    
    # Получаем текущие настройки
    settings = MealRepository.get_kbju_settings(user_id)
    
    if settings:
        # Показываем текущие настройки
        goal_labels = {
            "loss": "📉 Похудение",
            "maintain": "⚖️ Поддержание веса",
            "gain": "💪 Набор массы"
        }
        goal_label = goal_labels.get(settings.get("goal"), "Не указана")
        
        text = format_kbju_goal_text(
            settings.get("calories"),
            settings.get("protein"),
            settings.get("fat"),
            settings.get("carbs"),
            goal_label
        )
        text += "\n\n💡 Хочешь изменить цель? Пройди тест заново, нажав кнопку ниже."
        
        push_menu_stack(message.bot, kbju_menu)
        await message.answer(text, parse_mode="HTML")
        await message.answer("Или можешь продолжить работу с текущими настройками:", reply_markup=kbju_menu)
    else:
        # Предлагаем пройти тест
        await start_kbju_test(message, state)


@router.message(lambda m: m.text == "✅ Пройти быстрый тест КБЖУ")
async def start_kbju_test(message: Message, state: FSMContext):
    """Начинает тест КБЖУ."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} started KBJU test")
    
    await state.clear()
    await state.set_state(KbjuTestStates.entering_gender)
    
    push_menu_stack(message.bot, kbju_gender_menu)
    await message.answer(
        "Окей, пройдём небольшой тест 💪\n\n"
        "Для начала — укажи пол:",
        reply_markup=kbju_gender_menu,
    )


@router.message(KbjuTestStates.entering_gender)
async def handle_kbju_test_gender(message: Message, state: FSMContext):
    """Обрабатывает выбор пола в тесте КБЖУ."""
    user_id = str(message.from_user.id)
    txt = message.text.strip()

    if txt == "🙋‍♂️ Мужчина":
        gender = "male"
    elif txt == "🙋‍♀️ Женщина":
        gender = "female"
    else:
        await message.answer("Пожалуйста, выбери вариант с кнопки 🙂")
        return

    await state.update_data(gender=gender)
    await state.set_state(KbjuTestStates.entering_age)
    await message.answer("Сколько тебе лет? (например: 28)")


@router.message(KbjuTestStates.entering_age)
async def handle_kbju_test_age(message: Message, state: FSMContext):
    """Обрабатывает ввод возраста в тесте КБЖУ."""
    try:
        age = float(message.text.replace(",", "."))
        if age <= 0 or age > 150:
            raise ValueError
    except ValueError:
        await message.answer("Нужно ввести число от 1 до 150, попробуй ещё раз 🙂")
        return

    await state.update_data(age=age)
    await state.set_state(KbjuTestStates.entering_height)
    await message.answer("Какой у тебя рост в сантиметрах? (например: 171)")


@router.message(KbjuTestStates.entering_height)
async def handle_kbju_test_height(message: Message, state: FSMContext):
    """Обрабатывает ввод роста в тесте КБЖУ."""
    try:
        height = float(message.text.replace(",", "."))
        if height <= 0 or height > 300:
            raise ValueError
    except ValueError:
        await message.answer("Нужно ввести число от 1 до 300, попробуй ещё раз 🙂")
        return

    await state.update_data(height=height)
    await state.set_state(KbjuTestStates.entering_weight)
    await message.answer("Сколько ты весишь сейчас? В кг (например: 86.5)")


@router.message(KbjuTestStates.entering_weight)
async def handle_kbju_test_weight(message: Message, state: FSMContext):
    """Обрабатывает ввод веса в тесте КБЖУ."""
    try:
        weight = float(message.text.replace(",", "."))
        if weight <= 0 or weight > 500:
            raise ValueError
    except ValueError:
        await message.answer("Нужно ввести число от 1 до 500, попробуй ещё раз 🙂")
        return

    await state.update_data(weight=weight)
    await state.set_state(KbjuTestStates.entering_activity)
    
    push_menu_stack(message.bot, kbju_activity_menu)
    await message.answer(
        "Опиши свой обычный уровень активности:",
        reply_markup=kbju_activity_menu,
    )


@router.message(KbjuTestStates.entering_activity)
async def handle_kbju_test_activity(message: Message, state: FSMContext):
    """Обрабатывает выбор активности в тесте КБЖУ."""
    txt = message.text.strip()

    if txt == "🪑 Мало движения":
        activity = "low"
    elif txt == "🚶 Умеренная активность":
        activity = "medium"
    elif txt == "🏋️ Тренировки 3–5 раз/нед":
        activity = "high"
    else:
        await message.answer("Выбери вариант с кнопки, пожалуйста 🙂")
        return

    await state.update_data(activity=activity)
    await state.set_state(KbjuTestStates.entering_goal)
    
    push_menu_stack(message.bot, kbju_goal_menu)
    await message.answer(
        "Какая у тебя сейчас цель?",
        reply_markup=kbju_goal_menu,
    )


@router.message(KbjuTestStates.entering_goal)
async def handle_kbju_test_goal(message: Message, state: FSMContext):
    """Обрабатывает выбор цели в тесте КБЖУ и сохраняет настройки."""
    user_id = str(message.from_user.id)
    txt = message.text.strip()

    if txt == "📉 Похудение":
        goal = "loss"
    elif txt == "⚖️ Поддержание":
        goal = "maintain"
    elif txt == "💪 Набор массы":
        goal = "gain"
    else:
        await message.answer("Выбери вариант с кнопки, пожалуйста 🙂")
        return

    # Получаем все данные из FSM
    data = await state.get_data()
    data["goal"] = goal
    
    # Рассчитываем КБЖУ
    calories, protein, fat, carbs, goal_label = calculate_kbju_from_test(data)
    
    # Сохраняем настройки
    MealRepository.save_kbju_settings(
        user_id=user_id,
        calories=calories,
        protein=protein,
        fat=fat,
        carbs=carbs,
        goal=goal,
        activity=data.get("activity"),
    )
    
    await state.clear()
    
    # Форматируем и отправляем результат
    text = format_kbju_goal_text(calories, protein, fat, carbs, goal_label)
    
    push_menu_stack(message.bot, kbju_menu)
    await message.answer(text, parse_mode="HTML")
    await message.answer("Теперь можешь пользоваться разделом КБЖУ 👇", reply_markup=kbju_menu)


def register_kbju_test_handlers(dp):
    """Регистрирует обработчики теста КБЖУ."""
    dp.include_router(router)
