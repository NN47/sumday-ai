"""Обработчики для контроля воды."""
import logging
from datetime import date
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from states.user_states import WaterStates
from utils.keyboards import (
    MAIN_MENU_BUTTON_ALIASES,
    main_menu_button,
    push_menu_stack,
    water_amount_menu,
    water_quick_add_inline,
    water_menu,
)
from utils.calendar_utils import (
    build_water_calendar_keyboard,
    build_water_day_actions_keyboard,
)
from utils.progress_formatters import build_water_progress_bar
from database.repositories import WaterRepository, WeightRepository

logger = logging.getLogger(__name__)

router = Router()


def reset_user_state(message: Message, *, keep_supplements: bool = False):
    """Сбрасывает состояние пользователя (упрощённая версия)."""
    # TODO: Заменить на FSM состояния
    pass


def get_water_recommended(user_id: str) -> float:
    """Получает рекомендуемую норму воды для пользователя."""
    weight = WeightRepository.get_last_weight(user_id)
    if weight and weight > 0:
        # Формула: вес (кг) × 32.5 мл
        return weight * 32.5
    # Стандартное значение, если вес не указан
    return 2000.0


@router.message(lambda m: m.text == "💧 Контроль воды")
async def water(message: Message):
    """Показывает меню контроля воды."""
    reset_user_state(message)
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} opened water menu")
    
    today = date.today()
    daily_total = WaterRepository.get_daily_total(user_id, today)
    recommended = get_water_recommended(user_id)
    
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    bar = build_water_progress_bar(daily_total, recommended)
    
    weight = WeightRepository.get_last_weight(user_id)
    norm_info = ""
    if weight and weight > 0:
        norm_info = f"\n📊 Норма рассчитана по твоему весу ({weight:.1f} кг): {weight:.1f} × 32.5 мл = {recommended:.0f} мл"
    else:
        norm_info = "\n📊 Норма рассчитана по среднему значению (2000 мл). Укажи свой вес в разделе «⚖️ Вес и замеры», чтобы получить персональную норму."
    
    intro_text = (
        "💧 Контроль воды\n\n"
        f"Выпито сегодня: {daily_total:.0f} мл\n"
        f"Рекомендуемая норма: {recommended:.0f} мл\n"
        f"Прогресс: {progress}%\n"
        f"{bar}"
        f"{norm_info}\n\n"
        "Отслеживай количество выпитой воды в течение дня."
    )
    
    await message.answer(intro_text, reply_markup=water_quick_add_inline)
    push_menu_stack(message.bot, water_menu)
    await message.answer("Выбери действие в меню ниже.", reply_markup=water_menu)


@router.message(lambda m: m.text == "💧 +250 мл")
async def quick_add_water_250(message: Message, state: FSMContext):
    """Быстро добавляет 250 мл воды одной кнопкой из главного меню."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} used quick water +250 button")
    
    # Сбрасываем состояние, если пользователь был в каком-то другом шаге
    await state.clear()
    
    entry_date = date.today()
    amount = 250.0
    WaterRepository.save_water_entry(user_id, amount, entry_date)
    
    daily_total = WaterRepository.get_daily_total(user_id, entry_date)
    recommended = get_water_recommended(user_id)
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    bar = build_water_progress_bar(daily_total, recommended)
    
    text = (
        f"✅ Добавил {amount:.0f} мл воды\n\n"
        f"💧 Всего за сегодня: {daily_total:.0f} мл\n"
        f"🎯 Норма: {recommended:.0f} мл\n"
        f"📈 Прогресс: {progress}%\n"
        f"{bar}"
    )
    
    await message.answer(text)


@router.callback_query(lambda c: c.data == "quick_water_250")
async def quick_add_water_250_cb(callback: CallbackQuery, state: FSMContext):
    """Быстро добавляет 250 мл воды по inline-кнопке под текстом."""
    await callback.answer()
    message = callback.message
    user_id = str(callback.from_user.id)
    logger.info(f"User {user_id} used quick water +250 inline button")
    
    await state.clear()
    
    entry_date = date.today()
    amount = 250.0
    WaterRepository.save_water_entry(user_id, amount, entry_date)
    
    daily_total = WaterRepository.get_daily_total(user_id, entry_date)
    recommended = get_water_recommended(user_id)
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    bar = build_water_progress_bar(daily_total, recommended)
    
    text = (
        f"✅ Добавил {amount:.0f} мл воды\n\n"
        f"💧 Всего за сегодня: {daily_total:.0f} мл\n"
        f"🎯 Норма: {recommended:.0f} мл\n"
        f"📈 Прогресс: {progress}%\n"
        f"{bar}"
    )
    
    await message.answer(text)


@router.callback_query(lambda c: c.data and c.data.startswith("quick_water_add_"))
async def quick_add_water_amount_cb(callback: CallbackQuery, state: FSMContext):
    """Добавляет воду по inline-кнопке в меню воды."""
    await callback.answer()
    message = callback.message
    user_id = str(callback.from_user.id)
    amount_text = callback.data.replace("quick_water_add_", "")
    
    try:
        amount = float(amount_text)
        if amount == 0:
            raise ValueError
    except ValueError:
        await message.answer("Не удалось определить количество воды. Попробуй ещё раз.")
        return
    
    await state.clear()
    
    entry_date = date.today()
    WaterRepository.save_water_entry(user_id, amount, entry_date)
    
    daily_total = WaterRepository.get_daily_total(user_id, entry_date)
    recommended = get_water_recommended(user_id)
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    bar = build_water_progress_bar(daily_total, recommended)
    
    text = (
        f"✅ Добавил {amount:.0f} мл воды\n\n"
        f"💧 Всего за сегодня: {daily_total:.0f} мл\n"
        f"🎯 Норма: {recommended:.0f} мл\n"
        f"📈 Прогресс: {progress}%\n"
        f"{bar}"
    )
    
    await message.answer(text, reply_markup=water_menu)


@router.message(lambda m: m.text == "➕ Добавить воду")
async def add_water(message: Message, state: FSMContext):
    """Обработчик добавления воды."""
    reset_user_state(message)
    await start_add_water(message, state)


async def start_add_water(message: Message, state: FSMContext, *, entry_date: date | None = None):
    """Запускает процесс добавления воды."""
    await state.update_data(entry_date=(entry_date or date.today()).isoformat())
    await state.set_state(WaterStates.entering_amount)
    push_menu_stack(message.bot, water_amount_menu)
    await message.answer(
        "💧 Добавление воды\n\n"
        "Напиши количество воды в миллилитрах или выбери из предложенных.",
        reply_markup=water_amount_menu,
    )


@router.message(lambda m: m.text == "📆 Календарь воды")
async def water_calendar(message: Message):
    """Показывает календарь воды."""
    reset_user_state(message)
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} opened water calendar")
    today = date.today()
    await show_water_calendar(message, user_id, today.year, today.month)


async def show_water_calendar(message: Message, user_id: str, year: int, month: int):
    """Показывает календарь воды."""
    keyboard = build_water_calendar_keyboard(user_id, year, month)
    await message.answer(
        "📆 Календарь воды\n\nВыбери день, чтобы посмотреть или добавить воду:",
        reply_markup=keyboard,
    )


@router.callback_query(lambda c: c.data.startswith("water_cal_nav:"))
async def navigate_water_calendar(callback: CallbackQuery):
    """Навигация по календарю воды."""
    await callback.answer()
    parts = callback.data.split(":")
    year, month = map(int, parts[1].split("-"))
    user_id = str(callback.from_user.id)
    await show_water_calendar(callback.message, user_id, year, month)


@router.callback_query(lambda c: c.data.startswith("water_cal_back:"))
async def back_to_water_calendar(callback: CallbackQuery):
    """Возврат к календарю воды."""
    await callback.answer()
    parts = callback.data.split(":")
    year, month = map(int, parts[1].split("-"))
    user_id = str(callback.from_user.id)
    await show_water_calendar(callback.message, user_id, year, month)


@router.callback_query(lambda c: c.data.startswith("water_cal_day:"))
async def select_water_calendar_day(callback: CallbackQuery):
    """Выбор дня в календаре воды."""
    await callback.answer()
    parts = callback.data.split(":")
    target_date = date.fromisoformat(parts[1])
    user_id = str(callback.from_user.id)
    await show_water_day(callback.message, user_id, target_date)


async def show_water_day(message: Message, user_id: str, target_date: date):
    """Показывает записи воды за день."""
    entries = WaterRepository.get_entries_for_day(user_id, target_date)
    daily_total = WaterRepository.get_daily_total(user_id, target_date)
    recommended = get_water_recommended(user_id)

    if not entries:
        await message.answer(
            f"💧 {target_date.strftime('%d.%m.%Y')}\n\nВ этот день воды не было.",
            reply_markup=build_water_day_actions_keyboard([], target_date),
        )
        return

    lines = [f"💧 Вода за {target_date.strftime('%d.%m.%Y')}:\n"]
    for i, entry in enumerate(entries, 1):
        time_str = entry.timestamp.strftime("%H:%M") if entry.timestamp else ""
        lines.append(f"{i}. {entry.amount:.0f} мл {time_str}")

    lines.append(f"\n📊 Итого: {daily_total:.0f} мл")
    lines.append(f"🎯 Норма: {recommended:.0f} мл")
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    lines.append(f"📈 Прогресс: {progress}%")

    bar = build_water_progress_bar(daily_total, recommended)
    lines.append(f"\n{bar}")

    await message.answer(
        "\n".join(lines),
        reply_markup=build_water_day_actions_keyboard(entries, target_date),
    )


@router.callback_query(lambda c: c.data.startswith("water_cal_add:"))
async def add_water_from_calendar(callback: CallbackQuery, state: FSMContext):
    """Добавляет воду из календаря."""
    await callback.answer()
    parts = callback.data.split(":")
    target_date = date.fromisoformat(parts[1])
    await start_add_water(callback.message, state, entry_date=target_date)


@router.callback_query(lambda c: c.data.startswith("water_cal_del:"))
async def delete_water_from_calendar(callback: CallbackQuery):
    """Удаляет запись воды из календаря."""
    await callback.answer()
    parts = callback.data.split(":")
    target_date = date.fromisoformat(parts[1])
    entry_id = int(parts[2])
    user_id = str(callback.from_user.id)

    success = WaterRepository.delete_entry(entry_id, user_id)
    if success:
        await callback.message.answer("✅ Запись воды удалена.")
    else:
        await callback.message.answer("❌ Не удалось удалить запись воды.")

    await show_water_day(callback.message, user_id, target_date)


@router.message(WaterStates.entering_amount)
async def process_water_amount(message: Message, state: FSMContext):
    """Обрабатывает ввод количества воды."""
    user_id = str(message.from_user.id)
    text = message.text.strip()
    
    # Проверяем, не является ли это кнопкой меню
    if text in ["⬅️ Назад", "📆 Календарь воды", "➕ Добавить воду"] or text in MAIN_MENU_BUTTON_ALIASES:
        await state.clear()
        if text == "⬅️ Назад":
            # Возвращаемся в меню воды
            await water(message)
        return
    
    try:
        amount = float(text.replace(",", "."))
        if amount == 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(
            "Пожалуйста, введи число (количество миллилитров) или выбери из предложенных.",
            reply_markup=water_amount_menu,
        )
        return
    
    data = await state.get_data()
    entry_date_str = data.get("entry_date")
    entry_date = date.today()
    if entry_date_str:
        try:
            entry_date = date.fromisoformat(entry_date_str)
        except ValueError:
            entry_date = date.today()
    WaterRepository.save_water_entry(user_id, amount, entry_date)
    
    await state.clear()
    
    daily_total = WaterRepository.get_daily_total(user_id, entry_date)
    
    push_menu_stack(message.bot, water_menu)
    date_label = entry_date.strftime("%d.%m.%Y")
    await message.answer(
        f"✅ Добавил {amount:.0f} мл воды\n\n"
        f"📅 Дата: {date_label}\n"
        f"💧 Всего за день: {daily_total:.0f} мл",
        reply_markup=water_menu,
    )


def register_water_handlers(dp):
    """Регистрирует обработчики воды."""
    dp.include_router(router)
