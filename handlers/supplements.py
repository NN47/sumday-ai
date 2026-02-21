"""Обработчики для добавок."""
import logging
import re
import json
from datetime import date, datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from utils.keyboards import (
    LEGACY_MAIN_MENU_BUTTON_TEXT,
    MAIN_MENU_BUTTON_ALIASES,
    MAIN_MENU_BUTTON_TEXT,
    main_menu_button,
    push_menu_stack,
    training_date_menu,
)
from utils.supplement_keyboards import (
    supplements_main_menu,
    supplements_choice_menu,
    supplements_view_menu,
    supplement_details_menu,
    supplement_edit_menu,
    time_edit_menu,
    days_menu,
    duration_menu,
    time_first_menu,
)
from utils.calendar_utils import (
    build_supplement_calendar_keyboard,
    build_supplement_day_actions_keyboard,
)
from database.repositories import SupplementRepository
from states.user_states import SupplementStates
from utils.validators import parse_date

logger = logging.getLogger(__name__)

router = Router()


def parse_supplement_amount(text: str) -> Optional[float]:
    """Парсит количество добавки из текста."""
    normalized = text.replace(",", ".").strip()
    try:
        return float(normalized)
    except ValueError:
        return None


@router.message(lambda m: m.text == "💊 Добавки")
async def supplements(message: Message):
    """Показывает меню добавок."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} opened supplements menu")
    
    try:
        supplements_list = SupplementRepository.get_supplements(user_id)
    except Exception as e:
        logger.error(f"Error loading supplements: {e}", exc_info=True)
        await message.answer("Произошла ошибка при загрузке добавок. Попробуйте позже.")
        return
    
    dairi_description = (
        "Привет, это Дайри на связи! 🤖\n\n"
        "💊 Раздел «Добавки»\n\n"
        "Здесь ты можешь записывать свои добавки: лекарства, витамины, БАДы и любые другие препараты. "
        "Я помогу тебе отслеживать их приём, настроить расписание и получать статистику.\n\n"
        "⚠️ Важно: протеин нужно вписывать в раздел КБЖУ, потому что там подсчитывается количество белков "
        "для твоей дневной нормы. Этот раздел предназначен для лекарств и добавок, которые не влияют на калорийность и БЖУ.\n\n"
    )
    
    if not supplements_list:
        push_menu_stack(message.bot, supplements_main_menu(has_items=False))
        await message.answer(
            dairi_description + "Готов начать? Создай свою первую добавку!",
            reply_markup=supplements_main_menu(has_items=False),
        )
        return
    
    # Если добавки есть, показываем описание и список
    lines = [dairi_description + "📋 Твои добавки:\n"]
    for item in supplements_list:
        days = ", ".join(item["days"]) if item["days"] else "не выбрано"
        times = ", ".join(item["times"]) if item["times"] else "не выбрано"
        lines.append(
            f"\n💊 {item['name']} \n⏰ Время приема: {times}\n📅 Дни приема: {days}\n⏳ Длительность: {item['duration']}"
        )
    
    push_menu_stack(message.bot, supplements_main_menu(has_items=True))
    await message.answer("\n".join(lines), reply_markup=supplements_main_menu(has_items=True))


@router.message(lambda m: m.text == "📋 Мои добавки")
async def supplements_list_view(message: Message, state: FSMContext):
    """Показывает список добавок для просмотра."""
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    if not supplements_list:
        push_menu_stack(message.bot, supplements_main_menu(has_items=False))
        await message.answer(
            "У тебя пока нет добавок. Создай первую!",
            reply_markup=supplements_main_menu(has_items=False),
        )
        return
    
    await state.set_state(SupplementStates.viewing_history)
    push_menu_stack(message.bot, supplements_view_menu(supplements_list))
    await message.answer(
        "Выбери добавку для просмотра:",
        reply_markup=supplements_view_menu(supplements_list),
    )


@router.message(lambda m: m.text == "➕ Создать добавку")
async def start_create_supplement(message: Message, state: FSMContext):
    """Начинает процесс создания добавки."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} started creating supplement")
    
    await state.update_data({
        "supplement_id": None,
        "name": "",
        "times": [],
        "days": [],
        "duration": "постоянно",
        "notifications_enabled": True,
    })
    await state.set_state(SupplementStates.entering_name)
    await message.answer("Введите название добавки.")


@router.message(SupplementStates.entering_name)
async def handle_supplement_name(message: Message, state: FSMContext):
    """Обрабатывает ввод названия добавки - начало теста."""
    # Проверяем кнопку отмены
    if message.text == "❌ Отменить":
        await state.clear()
        await supplements(message)
        return
    
    name = message.text.strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите название добавки.")
        return
    
    await state.update_data(name=name)
    # Переходим к следующему шагу - время
    await state.set_state(SupplementStates.entering_time)
    
    from utils.supplement_keyboards import supplement_test_time_menu
    push_menu_stack(message.bot, supplement_test_time_menu([], show_back=True))
    await message.answer(
        f"✅ Название: {name}\n\n"
        "⏰ Шаг 2: Укажи время приёма добавки (например: 09:00, 12:00, 18:00)\n\n"
        "Можешь добавить несколько времён, вводя их по одному.\n"
        "Или нажми «⏭️ Пропустить», чтобы пропустить этот шаг.",
        reply_markup=supplement_test_time_menu([], show_back=True),
    )


async def start_log_supplement_flow(message: Message, state: FSMContext, user_id: str):
    """Начинает процесс отметки приёма добавки."""
    supplements_list = SupplementRepository.get_supplements(user_id)

    if not supplements_list:
        push_menu_stack(message.bot, supplements_main_menu(has_items=False))
        await message.answer(
            "Сначала создай добавку, чтобы отмечать приём.",
            reply_markup=supplements_main_menu(has_items=False),
        )
        return

    await state.update_data(from_calendar=False)
    await state.set_state(SupplementStates.logging_intake)
    push_menu_stack(message.bot, supplements_choice_menu(supplements_list))
    await message.answer(
        "Выбери добавку, приём которой нужно отметить:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@router.message(lambda m: m.text == "✅ Отметить приём")
async def start_log_supplement(message: Message, state: FSMContext):
    """Начинает процесс отметки приёма добавки."""
    user_id = str(message.from_user.id)
    await start_log_supplement_flow(message, state, user_id)


@router.message(SupplementStates.logging_intake)
async def log_supplement_intake(message: Message, state: FSMContext):
    """Обрабатывает выбор добавки для отметки приёма."""
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    # Проверяем, не является ли это кнопкой меню
    menu_buttons = ["⬅️ Назад", "❌ Отменить"]
    if message.text in menu_buttons or message.text in MAIN_MENU_BUTTON_ALIASES:
        await state.clear()
        if message.text == "⬅️ Назад" or message.text == "❌ Отменить":
            await supplements(message)
        return
    
    # Ищем добавку по имени (с учетом пробелов и регистра)
    message_text = message.text.strip()
    target = next(
        (item for item in supplements_list if item["name"].strip().lower() == message_text.lower()),
        None,
    )
    
    if not target:
        # Показываем список добавок снова
        push_menu_stack(message.bot, supplements_choice_menu(supplements_list))
        await message.answer(
            "Не нашёл такую добавку. Выбери название из списка или вернись назад.",
            reply_markup=supplements_choice_menu(supplements_list),
        )
        return
    
    target_date = date.today()
    await state.update_data(
        supplement_name=target["name"],
        supplement_id=target["id"],
        entry_date=target_date.isoformat(),
    )
    await state.set_state(SupplementStates.entering_history_time)
    from utils.supplement_keyboards import supplement_history_time_menu
    push_menu_stack(message.bot, supplement_history_time_menu())
    await message.answer(
        f"📅 Дата: {target_date.strftime('%d.%m.%Y')}\n\n"
        "Укажи время приёма в формате ЧЧ:ММ. Например: 09:30\n"
        "Или нажми «⏭️ Пропустить», чтобы оставить время по умолчанию.",
        reply_markup=supplement_history_time_menu(),
    )


@router.message(SupplementStates.choosing_date_for_intake)
async def handle_intake_date_choice(message: Message, state: FSMContext):
    """Обрабатывает выбор даты для приёма добавки."""
    # Проверяем кнопки отмены/назад
    if message.text == "❌ Отменить" or message.text == "⬅️ Назад":
        await state.clear()
        await supplements(message)
        return
    
    if message.text == "📅 Сегодня":
        target_date = date.today()
    elif message.text == "📅 Вчера":
        target_date = date.today() - timedelta(days=1)
    elif message.text == "📆 Позавчера":
        target_date = date.today() - timedelta(days=2)
    elif message.text == "✏️ Ввести дату вручную":
        await message.answer("Введи дату в формате ДД.ММ.ГГГГ:")
        return
    elif message.text == "📆 Другой день":
        from utils.keyboards import other_day_menu
        push_menu_stack(message.bot, other_day_menu)
        await message.answer(
            "Выбери день или введи дату вручную:",
            reply_markup=other_day_menu,
        )
        return
    else:
        # Проверяем, не дата ли это
        parsed = parse_date(message.text)
        if parsed:
            target_date = parsed.date() if isinstance(parsed, datetime) else date.today()
        else:
            await message.answer("Выбери дату из меню или введи в формате ДД.ММ.ГГГГ")
            return
    
    await state.update_data(entry_date=target_date.isoformat())
    await state.set_state(SupplementStates.entering_history_time)
    from utils.supplement_keyboards import supplement_history_time_menu
    push_menu_stack(message.bot, supplement_history_time_menu())
    await message.answer(
        f"📅 Дата: {target_date.strftime('%d.%m.%Y')}\n\n"
        "Укажи время приёма в формате ЧЧ:ММ. Например: 09:30\n"
        "Или нажми «⏭️ Пропустить», чтобы оставить время по умолчанию.",
        reply_markup=supplement_history_time_menu(),
    )


@router.message(SupplementStates.entering_history_time)
async def handle_history_time(message: Message, state: FSMContext):
    """Обрабатывает ввод времени приёма добавки."""
    # Проверяем кнопки отмены/назад
    if message.text == "❌ Отменить" or message.text == "⬅️ Назад":
        await state.clear()
        await supplements(message)
        return
    
    time_text = message.text.strip()
    if time_text == "⏭️ Пропустить":
        data = await state.get_data()
        entry_date_str = data.get("entry_date", date.today().isoformat())
        original_timestamp = data.get("original_timestamp")
        default_timestamp = None
        if isinstance(original_timestamp, str):
            try:
                default_timestamp = datetime.fromisoformat(original_timestamp)
            except (ValueError, TypeError):
                default_timestamp = None
        if default_timestamp is None:
            if isinstance(entry_date_str, str):
                try:
                    entry_date = date.fromisoformat(entry_date_str)
                except ValueError:
                    entry_date = date.today()
            else:
                entry_date = date.today()
            default_timestamp = datetime.combine(entry_date, datetime.now().time())
        await state.update_data(timestamp=default_timestamp.isoformat())
        await state.set_state(SupplementStates.entering_history_amount)
        await message.answer("Укажи количество для приёма (например: 1 или 2.5):")
        return

    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", time_text):
        await message.answer("Пожалуйста, укажи время в формате ЧЧ:ММ (например, 08:15)")
        return
    
    data = await state.get_data()
    entry_date_str = data.get("entry_date", date.today().isoformat())
    
    if isinstance(entry_date_str, str):
        try:
            entry_date = date.fromisoformat(entry_date_str)
        except ValueError:
            entry_date = date.today()
    else:
        entry_date = date.today()
    
    try:
        time_obj = datetime.strptime(time_text, "%H:%M").time()
        timestamp = datetime.combine(entry_date, time_obj)
        await state.update_data(timestamp=timestamp.isoformat())
        await state.set_state(SupplementStates.entering_history_amount)
        await message.answer("Укажи количество для приёма (например: 1 или 2.5):")
    except ValueError:
        await message.answer("Неверный формат времени. Используй ЧЧ:ММ (например, 09:30)")


@router.message(SupplementStates.entering_history_amount)
async def handle_history_amount(message: Message, state: FSMContext):
    """Обрабатывает ввод количества добавки и сохраняет запись."""
    # Проверяем кнопки отмены/назад
    if message.text == "❌ Отменить" or message.text == "⬅️ Назад":
        await state.clear()
        await supplements(message)
        return
    
    user_id = str(message.from_user.id)
    amount = parse_supplement_amount(message.text)
    
    if amount is None:
        await message.answer("Пожалуйста, укажи количество числом, например: 1 или 2.5")
        return
    
    data = await state.get_data()
    supplement_id = data.get("supplement_id")
    supplement_name = data.get("supplement_name")
    timestamp_str = data.get("timestamp")
    entry_date_str = data.get("entry_date")
    from_calendar = data.get("from_calendar", False)
    
    if not supplement_id or not timestamp_str:
        await message.answer("Ошибка: не найдены данные о добавке или времени.")
        await state.clear()
        return
    
    try:
        timestamp = datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        await message.answer("Ошибка: неверный формат времени.")
        await state.clear()
        return
    
    # Сохраняем запись
    entry_id = SupplementRepository.save_entry(user_id, supplement_id, timestamp, amount)
    
    if entry_id:
        # Если это редактирование из календаря, показываем обновлённый день
        if from_calendar and entry_date_str:
            try:
                entry_date = date.fromisoformat(entry_date_str)
                await state.clear()
                await show_supplement_day_entries(message, user_id, entry_date)
                return
            except (ValueError, TypeError):
                pass
        
        await state.clear()
        push_menu_stack(message.bot, supplements_main_menu(has_items=True))
        await message.answer(
            f"✅ Записал приём {supplement_name} ({amount}) на {timestamp.strftime('%d.%m.%Y %H:%M')}.",
            reply_markup=supplements_main_menu(has_items=True),
        )
    else:
        await message.answer("❌ Не удалось сохранить запись. Попробуйте позже.")
        await state.clear()


def format_supplement_history_lines(sup: dict) -> list[str]:
    """Форматирует историю приёма добавки."""
    history = sup.get("history", [])
    if not history:
        return ["Отметок пока нет."]
    
    def normalize_entry(entry):
        """Нормализует запись истории."""
        if isinstance(entry, dict):
            ts = entry.get("timestamp")
            if isinstance(ts, datetime):
                return ts
            elif isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    return None
        return None
    
    sorted_history = sorted(
        history,
        key=lambda entry: normalize_entry(entry) or datetime.min,
        reverse=True,
    )
    
    lines: list[str] = []
    for entry in sorted_history:
        ts = normalize_entry(entry)
        if not ts:
            continue
        amount = entry.get("amount") if isinstance(entry, dict) else None
        amount_text = f" — {amount}" if amount is not None else ""
        lines.append(f"{ts.strftime('%d.%m.%Y %H:%M')}{amount_text}")
    
    return lines or ["Отметок пока нет."]


async def show_supplement_details(message: Message, sup: dict, index: int):
    """Показывает детали добавки."""
    history_lines = format_supplement_history_lines(sup)
    
    lines = [f"💊 {sup.get('name', 'Добавка')}", "", "Отметки:"]
    lines.extend([f"• {item}" for item in history_lines])
    
    push_menu_stack(message.bot, supplement_details_menu())
    await message.answer("\n".join(lines), reply_markup=supplement_details_menu())


@router.message(
    SupplementStates.viewing_history,
    ~F.text.in_(
        [
            "✏️ Редактировать добавку",
            "🗑 Удалить добавку",
            "✅ Отметить добавку",
            "⬅️ Назад",
            MAIN_MENU_BUTTON_TEXT,
            LEGACY_MAIN_MENU_BUTTON_TEXT,
        ]
    )
)
async def choose_supplement_for_view(message: Message, state: FSMContext):
    """Обрабатывает выбор добавки для просмотра."""
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    # Ищем добавку по имени (с учетом пробелов и регистра)
    message_text = message.text.strip()
    
    # Более надежное сравнение - нормализуем пробелы и регистр
    def normalize_name(name: str) -> str:
        """Нормализует название для сравнения."""
        return " ".join(name.strip().split()).lower()
    
    normalized_search = normalize_name(message_text)
    target_index = None
    
    for idx, item in enumerate(supplements_list):
        item_name = item.get("name", "")
        normalized_item = normalize_name(item_name)
        if normalized_item == normalized_search:
            target_index = idx
            break
    
    if target_index is None:
        # Показываем список добавок снова
        push_menu_stack(message.bot, supplements_view_menu(supplements_list))
        await message.answer(
            f"Не нашёл такую добавку: '{message_text}'. Выбери название из списка.",
            reply_markup=supplements_view_menu(supplements_list),
        )
        return
    
    selected_supplement = supplements_list[target_index]
    # Сохраняем и индекс, и ID добавки для надежности
    await state.update_data(
        viewing_index=target_index,
        viewing_supplement_id=selected_supplement.get("id")
    )
    await show_supplement_details(message, selected_supplement, target_index)
    await state.set_state(SupplementStates.viewing_history)  # Сохраняем состояние просмотра


@router.message(lambda m: m.text == "✏️ Редактировать добавку")
async def edit_supplement_start(message: Message, state: FSMContext):
    """Начинает процесс редактирования добавки."""
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    # Проверяем, есть ли текущий просмотр
    data = await state.get_data()
    viewing_index = data.get("viewing_index")
    supplement_id = data.get("viewing_supplement_id")
    
    # Сначала пытаемся использовать ID, если он есть
    selected = None
    if supplement_id:
        selected = next((s for s in supplements_list if s.get("id") == supplement_id), None)
    
    # Если не нашли по ID, используем индекс
    if not selected and viewing_index is not None and 0 <= viewing_index < len(supplements_list):
        selected = supplements_list[viewing_index]
    
    if selected:
        await state.update_data(
            supplement_id=selected.get("id"),
            name=selected.get("name", ""),
            times=selected.get("times", []).copy(),
            days=selected.get("days", []).copy(),
            duration=selected.get("duration", "постоянно"),
            notifications_enabled=selected.get("notifications_enabled", True),
            editing_index=viewing_index,
        )
        await state.set_state(SupplementStates.editing_supplement)
        push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
        await message.answer(
            f"Редактирование: {selected.get('name', 'Добавка')}\n\n"
            f"⏰ Время: {', '.join(selected.get('times', [])) or 'не выбрано'}\n"
            f"📅 Дни: {', '.join(selected.get('days', [])) or 'не выбрано'}\n"
            f"⏳ Длительность: {selected.get('duration', 'постоянно')}",
            reply_markup=supplement_edit_menu(show_save=True),
        )
        return
    
    # Если нет текущего просмотра, показываем список для выбора
    if not supplements_list:
        push_menu_stack(message.bot, supplements_main_menu(has_items=False))
        await message.answer(
            "Пока нет добавок для редактирования.",
            reply_markup=supplements_main_menu(has_items=False),
        )
        return
    
    await state.set_state(SupplementStates.editing_supplement)
    push_menu_stack(message.bot, supplements_choice_menu(supplements_list))
    await message.answer(
        "Выбери добавку, которую нужно отредактировать:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@router.message(
    SupplementStates.editing_supplement,
    ~F.text.in_([
        "✏️ Редактировать время", 
        "📅 Редактировать дни", 
        "⏳ Длительность приема", 
        "🔔 Уведомления", 
        "✏️ Изменить название",
        "💾 Сохранить"
    ])
)
async def choose_supplement_to_edit(message: Message, state: FSMContext):
    """Обрабатывает выбор добавки для редактирования."""
    data = await state.get_data()
    
    # Если добавка уже выбрана (есть supplement_id), то этот обработчик
    # не должен обрабатывать сообщения (кнопки редактирования уже исключены фильтром)
    if data.get("supplement_id") is not None:
        # Обрабатываем только меню кнопки
        if message.text in MAIN_MENU_BUTTON_ALIASES:
            await state.clear()
            from handlers.common import go_main_menu
            await go_main_menu(message, state)
            return
        menu_buttons = ["⬅️ Назад", "❌ Отменить"]
        if message.text in menu_buttons:
            if message.text == "❌ Отменить":
                await state.clear()
                await supplements(message)
                return
            if message.text == "⬅️ Назад":
                # Уже редактируем добавку, просто возвращаемся к меню редактирования
                return
        return
    
    # Если добавка еще не выбрана, обрабатываем выбор добавки
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    # Проверяем, не является ли это кнопкой меню
    if message.text in MAIN_MENU_BUTTON_ALIASES:
        await state.clear()
        from handlers.common import go_main_menu
        await go_main_menu(message, state)
        return
    menu_buttons = ["⬅️ Назад", "💾 Сохранить", "❌ Отменить"]
    if message.text in menu_buttons:
        if message.text == "💾 Сохранить":
            # Сохранение обрабатывается отдельным обработчиком
            return
        if message.text == "❌ Отменить":
            await state.clear()
            await supplements(message)
            return
        if message.text == "⬅️ Назад":
            # Проверяем, есть ли уже выбранная добавка для редактирования
            data = await state.get_data()
            if data.get("supplement_id") is not None:
                # Уже редактируем добавку, просто возвращаемся к меню редактирования
                return
            # Если нет, возвращаемся к списку
            await state.clear()
            await supplements_list_view(message, state)
        return
    
    # Ищем добавку по имени (с учетом пробелов и регистра)
    message_text = message.text.strip()
    
    # Логируем для отладки
    logger.info(f"User {user_id} searching for supplement: '{message_text}'")
    logger.info(f"Available supplements: {[item.get('name', '') for item in supplements_list]}")
    
    # Более надежное сравнение - нормализуем пробелы и регистр
    def normalize_name(name: str) -> str:
        """Нормализует название для сравнения."""
        return " ".join(name.strip().split()).lower()
    
    normalized_search = normalize_name(message_text)
    target_index = None
    
    for idx, item in enumerate(supplements_list):
        item_name = item.get("name", "")
        normalized_item = normalize_name(item_name)
        logger.info(f"Comparing: '{normalized_search}' with '{normalized_item}' (original: '{item_name}')")
        if normalized_item == normalized_search:
            target_index = idx
            break
    
    if target_index is None:
        # Показываем список добавок снова
        push_menu_stack(message.bot, supplements_choice_menu(supplements_list))
        await message.answer(
            f"Не нашёл такую добавку: '{message_text}'. Выбери название из списка.",
            reply_markup=supplements_choice_menu(supplements_list),
        )
        return
    
    selected = supplements_list[target_index]
    await state.update_data(
        supplement_id=selected.get("id"),
        name=selected.get("name", ""),
        times=selected.get("times", []).copy(),
        days=selected.get("days", []).copy(),
        duration=selected.get("duration", "постоянно"),
        notifications_enabled=selected.get("notifications_enabled", True),
        editing_index=target_index,
    )
    
    push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
    await message.answer(
        f"Редактирование: {selected.get('name', 'Добавка')}\n\n"
        f"⏰ Время: {', '.join(selected.get('times', [])) or 'не выбрано'}\n"
        f"📅 Дни: {', '.join(selected.get('days', [])) or 'не выбрано'}\n"
        f"⏳ Длительность: {selected.get('duration', 'постоянно')}",
        reply_markup=supplement_edit_menu(show_save=True),
    )


@router.message(lambda m: m.text == "🗑 Удалить добавку")
async def delete_supplement(message: Message, state: FSMContext):
    """Удаляет добавку."""
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    data = await state.get_data()
    viewing_index = data.get("viewing_index")
    supplement_id = data.get("viewing_supplement_id")
    
    # Сначала пытаемся использовать ID, если он есть
    target = None
    if supplement_id:
        # Проверяем, что добавка с таким ID существует
        target = next((s for s in supplements_list if s.get("id") == supplement_id), None)
        if target:
            success = SupplementRepository.delete_supplement(user_id, supplement_id)
            if success:
                await message.answer(f"🗑 Добавка {target.get('name', 'без названия')} удалена.")
                await state.clear()
                await supplements_list_view(message, state)
            else:
                await message.answer("❌ Не удалось удалить добавку. Попробуйте позже.")
            return
    
    # Если не нашли по ID, пытаемся использовать индекс (для обратной совместимости)
    if not target and viewing_index is not None and viewing_index < len(supplements_list):
        target = supplements_list[viewing_index]
        supplement_id = target.get("id")
        
        if supplement_id:
            success = SupplementRepository.delete_supplement(user_id, supplement_id)
            if success:
                await message.answer(f"🗑 Добавка {target.get('name', 'без названия')} удалена.")
                await state.clear()
                await supplements_list_view(message, state)
            else:
                await message.answer("❌ Не удалось удалить добавку. Попробуйте позже.")
            return
        else:
            await message.answer("❌ Не найдена добавка для удаления.")
            return
    
    # Если не нашли добавку ни по ID, ни по индексу
    if not target:
        await message.answer("❌ Не нашёл такую добавку. Выбери добавку из списка 'Мои добавки'.")
        await supplements_list_view(message, state)


@router.message(lambda m: m.text == "✅ Отметить добавку")
async def mark_supplement_from_details(message: Message, state: FSMContext):
    """Отмечает приём добавки из деталей."""
    user_id = str(message.from_user.id)
    supplements_list = SupplementRepository.get_supplements(user_id)
    
    data = await state.get_data()
    viewing_index = data.get("viewing_index")
    supplement_id = data.get("viewing_supplement_id")
    
    # Сначала пытаемся использовать ID, если он есть
    target = None
    if supplement_id:
        target = next((s for s in supplements_list if s.get("id") == supplement_id), None)
    
    # Если не нашли по ID, используем индекс
    if not target and viewing_index is not None and viewing_index < len(supplements_list):
        target = supplements_list[viewing_index]
    
    if not target:
        push_menu_stack(message.bot, supplements_main_menu(has_items=bool(supplements_list)))
        await message.answer(
            "Сначала выбери добавку в списке 'Мои добавки'.",
            reply_markup=supplements_main_menu(has_items=bool(supplements_list)),
        )
        return
    
    target_date = date.today()
    await state.update_data(
        supplement_name=target.get("name", ""),
        supplement_id=target.get("id"),
        entry_date=target_date.isoformat(),
    )
    await state.set_state(SupplementStates.entering_history_time)
    from utils.supplement_keyboards import supplement_history_time_menu
    push_menu_stack(message.bot, supplement_history_time_menu())
    await message.answer(
        f"📅 Дата: {target_date.strftime('%d.%m.%Y')}\n\n"
        "Укажи время приёма в формате ЧЧ:ММ. Например: 09:30\n"
        "Или нажми «⏭️ Пропустить», чтобы оставить время по умолчанию.",
        reply_markup=supplement_history_time_menu(),
    )


@router.message(SupplementStates.editing_supplement, lambda m: m.text == "💾 Сохранить")
async def save_supplement(message: Message, state: FSMContext):
    """Сохраняет добавку (только для редактирования существующей)."""
    user_id = str(message.from_user.id)
    data = await state.get_data()
    
    supplement_id = data.get("supplement_id")
    if supplement_id is None:
        # На всякий случай: в режиме создания/теста сохранение обрабатывается другими шагами
        return
    
    name = data.get("name", "").strip()
    if not name:
        await message.answer("Пожалуйста, укажите название добавки перед сохранением.")
        return
    
    supplement_payload = {
        "name": name,
        "times": data.get("times", []).copy(),
        "days": data.get("days", []).copy(),
        "duration": data.get("duration", "постоянно"),
        "notifications_enabled": data.get("notifications_enabled", True),
    }
    
    saved_id = SupplementRepository.save_supplement(user_id, supplement_payload, supplement_id)
    
    if saved_id:
        await state.clear()
        notifications_status = "включены" if supplement_payload.get("notifications_enabled", True) else "выключены"
        push_menu_stack(message.bot, supplements_main_menu(has_items=True))
        await message.answer(
            "✅ Добавка сохранена!\n\n"
            f"💊 {supplement_payload['name']} \n"
            f"⏰ Время приема: {', '.join(supplement_payload['times']) or 'не выбрано'}\n"
            f"📅 Дни приема: {', '.join(supplement_payload['days']) or 'не выбрано'}\n"
            f"⏳ Длительность: {supplement_payload['duration']}\n"
            f"🔔 Уведомления: {notifications_status}",
            reply_markup=supplements_main_menu(has_items=True),
        )
    else:
        await message.answer("❌ Не удалось сохранить добавку. Попробуйте позже.")


@router.message(SupplementStates.editing_supplement, lambda m: m.text == "✏️ Редактировать время")
async def edit_supplement_time(message: Message, state: FSMContext):
    """Начинает редактирование времени приёма."""
    data = await state.get_data()
    times = data.get("times", [])
    
    await state.set_state(SupplementStates.entering_time)
    if times:
        push_menu_stack(message.bot, time_edit_menu(times))
        times_list = "\n".join(times)
        await message.answer(
            f"⏰ Редактирование времени приёма\n\n"
            f"Текущее расписание:\n{times_list}\n\n"
            f"💡 Введите время в формате ЧЧ:ММ (например: 09:00)\n\n"
            f"ℹ️ Нажмите ❌ чтобы удалить время",
            reply_markup=time_edit_menu(times),
        )
    else:
        push_menu_stack(message.bot, time_first_menu())
        await message.answer(
            f"⏰ Добавление времени приёма\n\n"
            f"💡 Введите время в формате ЧЧ:ММ\n"
            f"Например: 09:00 или 14:30\n\n"
            f"Нажмите «💾 Сохранить», когда закончите добавлять время",
            reply_markup=time_first_menu(),
        )


@router.message(SupplementStates.entering_time)
async def handle_time_value(message: Message, state: FSMContext):
    """Обрабатывает ввод времени."""
    text = message.text.strip()
    data = await state.get_data()
    supplement_id = data.get("supplement_id")
    
    # Если это создание новой добавки (тест)
    if supplement_id is None:
        # Проверяем отмену
        if text == "❌ Отменить":
            await state.clear()
            await supplements(message)
            return
        
        # Проверяем назад - возвращаемся к шагу названия
        if text == "⬅️ Назад":
            data = await state.get_data()
            name = data.get("name", "")
            if name:
                # Возвращаемся к шагу названия
                await state.set_state(SupplementStates.entering_name)
                from utils.supplement_keyboards import supplement_test_skip_menu
                push_menu_stack(message.bot, supplement_test_skip_menu())
                await message.answer(
                    f"⏪ Возвращаемся к шагу 1\n\n"
                    f"Текущее название: {name}\n\n"
                    f"Введите новое название добавки или оставьте текущее:",
                    reply_markup=supplement_test_skip_menu(),
                )
            else:
                await state.clear()
                await supplements(message)
            return
        
        # Проверяем пропуск (только если времен нет)
        if text == "⏭️ Пропустить":
            current_times = data.get("times", [])
            if not current_times or len(current_times) == 0:
                await state.update_data(times=[])
                # Переходим к следующему шагу - дни
                await state.set_state(SupplementStates.selecting_days)
                from utils.supplement_keyboards import supplement_test_skip_menu, days_menu
                push_menu_stack(message.bot, supplement_test_skip_menu(show_back=True))
                await message.answer(
                    "⏭️ Время пропущено\n\n"
                    "📅 Шаг 3: Выбери дни приёма добавки\n\n"
                    "Можешь выбрать несколько дней или нажми «⏭️ Пропустить».",
                    reply_markup=days_menu([], show_cancel=True),
                )
                return
        
        # Проверяем сохранение (когда есть времена)
        if text == "💾 Сохранить":
            current_times = data.get("times", [])
            if current_times and len(current_times) > 0:
                # Явно сохраняем времена в state перед переходом
                await state.update_data(times=current_times)
                # Переходим к следующему шагу - дни
                await state.set_state(SupplementStates.selecting_days)
                from utils.supplement_keyboards import supplement_test_skip_menu, days_menu
                push_menu_stack(message.bot, supplement_test_skip_menu(show_back=True))
                times_text = ", ".join(current_times)
                await message.answer(
                    f"✅ Время сохранено: {times_text}\n\n"
                    "📅 Шаг 3: Выбери дни приёма добавки\n\n"
                    "Можешь выбрать несколько дней или нажми «⏭️ Пропустить».",
                    reply_markup=days_menu([], show_cancel=True),
                )
                return
        
        # Проверяем формат времени
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", text):
            current_times = data.get("times", [])
            from utils.supplement_keyboards import supplement_test_time_menu
            push_menu_stack(message.bot, supplement_test_time_menu(current_times, show_back=True))
            if current_times and len(current_times) > 0:
                await message.answer(
                    "Пожалуйста, укажи время в формате ЧЧ:ММ (например: 09:00) или нажми «💾 Сохранить», чтобы продолжить.",
                    reply_markup=supplement_test_time_menu(current_times, show_back=True),
                )
            else:
                await message.answer(
                    "Пожалуйста, укажи время в формате ЧЧ:ММ (например: 09:00) или нажми «⏭️ Пропустить»",
                    reply_markup=supplement_test_time_menu(current_times, show_back=True),
                )
            return
        
        # Добавляем время
        times = data.get("times", []).copy()
        if text not in times:
            times.append(text)
        times.sort()
        await state.update_data(times=times)
        
        # Показываем текущие времена и предлагаем добавить еще или продолжить
        from utils.supplement_keyboards import supplement_test_time_menu
        times_list = "\n".join(times) if times else "нет"
        push_menu_stack(message.bot, supplement_test_time_menu(times, show_back=True))
        if len(times) > 0:
            await message.answer(
                f"✅ Добавлено время: {text}\n\n"
                f"Текущие времена приёма:\n{times_list}\n\n"
                "Введи ещё одно время (ЧЧ:ММ) или нажми «💾 Сохранить», чтобы продолжить.",
                reply_markup=supplement_test_time_menu(times, show_back=True),
            )
        else:
            await message.answer(
                f"✅ Добавлено время: {text}\n\n"
                f"Текущие времена приёма:\n{times_list}\n\n"
                "Введи ещё одно время (ЧЧ:ММ) или нажми «⏭️ Пропустить», чтобы продолжить.",
                reply_markup=supplement_test_time_menu(times, show_back=True),
            )
        return
    
    # Если это редактирование существующей добавки - старая логика
    # "💾 Сохранить" в режиме редактирования времени означает "готово" и возврат в меню редактирования,
    # а не сохранение в БД (это делается отдельной кнопкой в меню редактирования добавки).
    if text == "💾 Сохранить":
        await state.set_state(SupplementStates.editing_supplement)
        data = await state.get_data()
        push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
        await message.answer(
            "✅ Время сохранено.\n\n"
            f"💊 {data.get('name', 'Добавка')}\n"
            f"⏰ Время: {', '.join(data.get('times', [])) or 'не выбрано'}\n"
            f"📅 Дни: {', '.join(data.get('days', [])) or 'не выбрано'}\n"
            f"⏳ Длительность: {data.get('duration', 'постоянно')}",
            reply_markup=supplement_edit_menu(show_save=True),
        )
        return
    
    
    # Обрабатываем кнопку "⬅️ Назад"
    if text == "⬅️ Назад":
        await state.set_state(SupplementStates.editing_supplement)
        data = await state.get_data()
        push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
        await message.answer(
            f"💊 {data.get('name', 'Добавка')}\n"
            f"⏰ Время: {', '.join(data.get('times', [])) or 'не выбрано'}\n"
            f"📅 Дни: {', '.join(data.get('days', [])) or 'не выбрано'}\n"
            f"⏳ Длительность: {data.get('duration', 'постоянно')}",
            reply_markup=supplement_edit_menu(show_save=True),
        )
        return
    
    # Обрабатываем удаление времени (кнопки начинающиеся с "❌")
    if text.startswith("❌"):
        # Удаление времени
        time_value = text.replace("❌ ", "").strip()
        times = data.get("times", []).copy()
        if time_value in times:
            times.remove(time_value)
        await state.update_data(times=times)
        if times:
            push_menu_stack(message.bot, time_edit_menu(times))
            times_list = "\n".join(times)
            await message.answer(
                f"✅ Время удалено\n\n"
                f"Обновленное расписание:\n{times_list}\n\n"
                f"💡 Введите время в формате ЧЧ:ММ (например: 09:00) или нажмите «💾 Сохранить»",
                reply_markup=time_edit_menu(times),
            )
        else:
            push_menu_stack(message.bot, time_first_menu())
            await message.answer(
                "✅ Расписание очищено\n\n"
                "💡 Введите время в формате ЧЧ:ММ (например: 09:00)",
                reply_markup=time_first_menu(),
            )
        return
    
    # Проверяем формат времени
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", text):
        data = await state.get_data()
        times = data.get("times", [])
        if times:
            push_menu_stack(message.bot, time_edit_menu(times))
            await message.answer(
                "❌ Неверный формат времени\n\n"
                "💡 Пожалуйста, укажите время в формате ЧЧ:ММ\n"
                "Например: 09:00 или 14:30",
                reply_markup=time_edit_menu(times),
            )
        else:
            push_menu_stack(message.bot, time_first_menu())
            await message.answer(
                "❌ Неверный формат времени\n\n"
                "💡 Пожалуйста, укажите время в формате ЧЧ:ММ\n"
                "Например: 09:00 или 14:30",
                reply_markup=time_first_menu(),
            )
        return
    
    times = data.get("times", []).copy()
    if text not in times:
        times.append(text)
    times.sort()
    
    await state.update_data(times=times)
    push_menu_stack(message.bot, time_edit_menu(times))
    times_list = "\n".join(times)
    await message.answer(
        f"✅ Время добавлено: {text}\n\n"
        f"📋 Расписание приёма:\n{times_list}\n\n"
        f"💡 Введите ещё одно время (ЧЧ:ММ) или нажмите «💾 Сохранить»",
        reply_markup=time_edit_menu(times),
    )


@router.message(SupplementStates.editing_supplement, lambda m: m.text == "📅 Редактировать дни")
async def edit_days(message: Message, state: FSMContext):
    """Начинает редактирование дней приёма."""
    data = await state.get_data()
    days = data.get("days", [])
    
    await state.set_state(SupplementStates.selecting_days)
    push_menu_stack(message.bot, days_menu(days))
    await message.answer(
        "Выберите дни приема:\nНажмите на день для выбора",
        reply_markup=days_menu(days),
    )


@router.message(SupplementStates.selecting_days)
async def toggle_day(message: Message, state: FSMContext):
    """Переключает выбор дня."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} selecting days, input: {message.text}")
    
    try:
        data = await state.get_data()
        supplement_id = data.get("supplement_id")
        
        # Если это создание новой добавки (тест)
        if supplement_id is None:
            # Проверяем пропуск
            if message.text == "⏭️ Пропустить":
                times = data.get("times", [])
                # Явно сохраняем дни и времена в state перед переходом
                await state.update_data(days=[], times=times)
                # Переходим к следующему шагу - длительность
                await state.set_state(SupplementStates.choosing_duration)
                from utils.supplement_keyboards import supplement_test_skip_menu, duration_menu
                push_menu_stack(message.bot, supplement_test_skip_menu())
                await message.answer(
                    "⏭️ Дни пропущены\n\n"
                    "⏳ Шаг 4: Выбери длительность приёма добавки\n\n"
                    "Или нажми «⏭️ Пропустить», чтобы оставить «Постоянно».",
                    reply_markup=duration_menu(),
                )
                return
            
            # Проверяем отмену
            if message.text == "❌ Отменить":
                await state.clear()
                await supplements(message)
                return
            
            # Проверяем назад - возвращаемся к шагу времени
            if message.text == "⬅️ Назад":
                data = await state.get_data()
                name = data.get("name", "")
                times = data.get("times", [])
                
                # Возвращаемся к шагу времени
                await state.set_state(SupplementStates.entering_time)
                from utils.supplement_keyboards import supplement_test_time_menu
                push_menu_stack(message.bot, supplement_test_time_menu(times, show_back=True))
                
                times_text = "\n".join(times) if times else "нет"
                if times and len(times) > 0:
                    await message.answer(
                        f"⏪ Возвращаемся к шагу 2\n\n"
                        f"💊 {name}\n\n"
                        f"⏰ Текущие времена приёма:\n{times_text}\n\n"
                        f"Введи ещё одно время (ЧЧ:ММ) или нажми «💾 Сохранить», чтобы продолжить.",
                        reply_markup=supplement_test_time_menu(times, show_back=True),
                    )
                else:
                    await message.answer(
                        f"⏪ Возвращаемся к шагу 2\n\n"
                        f"💊 {name}\n\n"
                        f"⏰ Текущие времена приёма:\n{times_text}\n\n"
                        f"Введи ещё одно время (ЧЧ:ММ) или нажми «⏭️ Пропустить», чтобы продолжить.",
                        reply_markup=supplement_test_time_menu(times, show_back=True),
                    )
                return
            
            # Проверяем "Выбрать все"
            if message.text == "Выбрать все":
                await state.update_data(days=["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
                data = await state.get_data()
                from utils.supplement_keyboards import days_menu
                push_menu_stack(message.bot, days_menu(data.get("days", []), show_cancel=True))
                await message.answer("✅ Все дни выбраны", reply_markup=days_menu(data.get("days", []), show_cancel=True))
                return
            
            # Проверяем "💾 Сохранить" - переход к следующему шагу
            if message.text == "💾 Сохранить":
                days = data.get("days", [])
                times = data.get("times", [])
                # Явно сохраняем дни и времена в state перед переходом
                await state.update_data(days=days, times=times)
                # Переходим к следующему шагу - длительность
                await state.set_state(SupplementStates.choosing_duration)
                from utils.supplement_keyboards import duration_menu
                push_menu_stack(message.bot, duration_menu())
                days_text = ", ".join(days) if days else "не выбрано"
                await message.answer(
                    f"✅ Дни сохранены: {days_text}\n\n"
                    "⏳ Шаг 4: Выбери длительность приёма добавки\n\n"
                    "Или нажми «⏭️ Пропустить», чтобы оставить «Постоянно».",
                    reply_markup=duration_menu(),
                )
                return
            
            # Обрабатываем выбор дня
            day = message.text.replace("✅ ", "").strip()
            if day not in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
                # Если это не день, показываем подсказку
                from utils.supplement_keyboards import days_menu
                current_days = data.get("days", [])
                await message.answer(
                    "Пожалуйста, выбери дни недели из меню или нажми «💾 Сохранить», чтобы продолжить.",
                    reply_markup=days_menu(current_days, show_cancel=True),
                )
                return
            
            days = data.get("days", []).copy()
            if day in days:
                days.remove(day)
            else:
                days.append(day)
            
            await state.update_data(days=days)
            from utils.supplement_keyboards import days_menu
            push_menu_stack(message.bot, days_menu(days, show_cancel=True))
            days_text = ", ".join(days) if days else "не выбрано"
            await message.answer(f"✅ Дни обновлены: {days_text}", reply_markup=days_menu(days, show_cancel=True))
            return
        
        # Если это редактирование существующей добавки - старая логика
        if message.text == "💾 Сохранить":
            # В режиме редактирования дней "Сохранить" = завершить выбор и вернуться в меню редактирования
            await state.set_state(SupplementStates.editing_supplement)
            data = await state.get_data()
            push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
            await message.answer(
                "✅ Дни сохранены.\n\n"
                f"💊 {data.get('name', 'Добавка')}\n"
                f"⏰ Время: {', '.join(data.get('times', [])) or 'не выбрано'}\n"
                f"📅 Дни: {', '.join(data.get('days', [])) or 'не выбрано'}\n"
                f"⏳ Длительность: {data.get('duration', 'постоянно')}",
                reply_markup=supplement_edit_menu(show_save=True),
            )
            return
        
        if message.text == "Выбрать все":
            await state.update_data(days=["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
            data = await state.get_data()
            from utils.supplement_keyboards import days_menu
            push_menu_stack(message.bot, days_menu(data.get("days", [])))
            await message.answer("Все дни выбраны", reply_markup=days_menu(data.get("days", [])))
            return
        
        day = message.text.replace("✅ ", "").strip()
        if day not in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
            # Если это не день, показываем подсказку
            from utils.supplement_keyboards import days_menu
            current_days = data.get("days", [])
            await message.answer(
                "Пожалуйста, выбери дни недели из меню или нажми «💾 Сохранить», чтобы вернуться к редактированию.",
                reply_markup=days_menu(current_days),
            )
            return
        
        data = await state.get_data()
        days = data.get("days", []).copy()
        if day in days:
            days.remove(day)
        else:
            days.append(day)
        
        await state.update_data(days=days)
        from utils.supplement_keyboards import days_menu
        push_menu_stack(message.bot, days_menu(days))
        await message.answer("Дни обновлены", reply_markup=days_menu(days))
    except Exception as e:
        logger.error(f"Error in toggle_day for user {user_id}: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуй ещё раз.")


@router.message(SupplementStates.editing_supplement, lambda m: m.text == "⏳ Длительность приема")
async def choose_duration(message: Message, state: FSMContext):
    """Показывает меню выбора длительности."""
    await state.set_state(SupplementStates.choosing_duration)
    push_menu_stack(message.bot, duration_menu())
    await message.answer("Выберите длительность приема", reply_markup=duration_menu())


# Обработчик handle_duration_choice теперь объединен с handle_notifications_in_test выше


async def ask_notifications_in_test(message: Message, state: FSMContext):
    """Спрашивает про уведомления в тесте создания добавки."""
    from utils.supplement_keyboards import supplement_test_notifications_menu
    # Получаем текущие данные для проверки
    data = await state.get_data()
    times = data.get("times", [])
    days = data.get("days", [])
    
    # Убеждаемся, что times и days являются списками
    if not isinstance(times, list):
        times = [times] if times else []
    if not isinstance(days, list):
        days = [days] if days else []
    
    # Логируем для отладки
    logger.info(f"User {message.from_user.id} asking notifications:")
    logger.info(f"  Raw times={times}, type={type(times)}, is_list={isinstance(times, list)}")
    logger.info(f"  Raw days={days}, type={type(days)}, is_list={isinstance(days, list)}")
    logger.info(f"  Full state data keys: {list(data.keys())}")
    
    # Сохраняем флаг, что это тест создания добавки, и убеждаемся, что times и days сохранены как списки
    await state.update_data(
        is_test_creation=True,
        times=times,  # Явно сохраняем как список
        days=days,   # Явно сохраняем как список
    )
    await state.set_state(SupplementStates.choosing_duration)  # Используем существующее состояние
    push_menu_stack(message.bot, supplement_test_notifications_menu())
    
    # Показываем текущие значения времени и дней в сообщении
    times_text = ", ".join(times) if times and len(times) > 0 else "не указано"
    days_text = ", ".join(days) if days and len(days) > 0 else "не выбрано"
    
    await message.answer(
        f"🔔 Шаг 5: Включить уведомления о приёме добавки?\n\n"
        f"Если включишь уведомления, я буду напоминать тебе о приёме добавки в указанное время.\n\n"
        f"⏰ Время: {times_text}\n"
        f"📅 Дни: {days_text}\n\n"
        f"⚠️ Для уведомлений нужно указать время и дни приёма.",
        reply_markup=supplement_test_notifications_menu(),
    )


@router.message(SupplementStates.choosing_duration)
async def handle_duration_or_notifications(message: Message, state: FSMContext):
    """Обрабатывает выбор длительности или уведомлений в тесте создания добавки."""
    data = await state.get_data()
    supplement_id = data.get("supplement_id")
    is_test_creation = data.get("is_test_creation", False)
    
    # Если это режим уведомлений (is_test_creation=True и supplement_id=None)
    if supplement_id is None and is_test_creation:
        # Обрабатываем кнопки уведомлений
        if message.text == "❌ Отменить":
            await state.clear()
            await supplements(message)
            return
        
        if message.text == "⬅️ Назад":
            # Возвращаемся к шагу длительности
            data = await state.get_data()
            duration = data.get("duration", "постоянно")
            # Снимаем флаг is_test_creation, чтобы вернуться к выбору длительности
            await state.update_data(is_test_creation=False)
            await state.set_state(SupplementStates.choosing_duration)
            from utils.supplement_keyboards import duration_menu
            push_menu_stack(message.bot, duration_menu())
            duration_text = duration.capitalize() if duration != "постоянно" else "Постоянно"
            await message.answer(
                f"⏪ Возвращаемся к шагу 4\n\n"
                f"⏳ Текущая длительность: {duration_text}\n\n"
                f"Выбери длительность приёма добавки:",
                reply_markup=duration_menu(),
            )
            return
        
        if message.text == "⏭️ Пропустить":
            await state.update_data(notifications_enabled=False)
            await save_supplement_from_test(message, state)
            return
        
        if message.text == "✅ Включить":
            # Перезагружаем данные из state, чтобы убедиться, что у нас актуальные данные
            current_data = await state.get_data()
            times = current_data.get("times", [])
            days = current_data.get("days", [])
            
            # Проверяем, что есть хотя бы одно время и хотя бы один день
            # Исправляем проверку: times может быть None или пустым списком
            times_list = []
            if times:
                if isinstance(times, list):
                    times_list = [t for t in times if t]  # Убираем пустые значения
                elif isinstance(times, str):
                    times_list = [times]
            
            days_list = []
            if days:
                if isinstance(days, list):
                    days_list = [d for d in days if d]  # Убираем пустые значения
                elif isinstance(days, str):
                    days_list = [days]
            
            # Логируем для отладки
            logger.info(f"User {message.from_user.id} checking notifications:")
            logger.info(f"  Raw times={times}, type={type(times)}, times_list={times_list}")
            logger.info(f"  Raw days={days}, type={type(days)}, days_list={days_list}")
            logger.info(f"  Full state data: {current_data}")
            
            if not times_list or not days_list:
                from utils.supplement_keyboards import supplement_test_notifications_menu
                times_status = "не указано" if not times_list or len(times_list) == 0 else f"указано: {', '.join(times_list)}"
                days_status = "не выбрано" if not days_list or len(days_list) == 0 else f"выбрано: {', '.join(days_list)}"
                await message.answer(
                    f"⚠️ Для уведомлений нужно указать время и дни приёма!\n\n"
                    f"⏰ Время: {times_status}\n"
                    f"📅 Дни: {days_status}\n\n"
                    f"Вернись назад и заполни эти поля, или выключи уведомления.",
                    reply_markup=supplement_test_notifications_menu(),
                )
                return
            
            await state.update_data(notifications_enabled=True)
            logger.info(f"User {message.from_user.id} enabling notifications: times={times_list}, days={days_list}")
            await save_supplement_from_test(message, state)
            return
        
        if message.text == "❌ Выключить":
            await state.update_data(notifications_enabled=False)
            await save_supplement_from_test(message, state)
            return
        
        # Если это неизвестное сообщение в режиме уведомлений
        from utils.supplement_keyboards import supplement_test_notifications_menu
        await message.answer(
            "Пожалуйста, выбери один из вариантов:\n"
            "✅ Включить - включить уведомления\n"
            "❌ Выключить - выключить уведомления\n"
            "⏭️ Пропустить - пропустить этот шаг",
            reply_markup=supplement_test_notifications_menu(),
        )
        return
    
    # Если это режим выбора длительности
    # Проверяем отмену
    if message.text == "❌ Отменить":
        await state.clear()
        await supplements(message)
        return
    
    # Проверяем назад - возвращаемся к шагу дней
    if message.text == "⬅️ Назад":
        if supplement_id is None:
            # Возвращаемся к шагу дней
            data = await state.get_data()
            days = data.get("days", [])
            await state.set_state(SupplementStates.selecting_days)
            from utils.supplement_keyboards import days_menu
            push_menu_stack(message.bot, days_menu(days, show_cancel=True))
            days_text = ", ".join(days) if days else "не выбрано"
            await message.answer(
                f"⏪ Возвращаемся к шагу 3\n\n"
                f"📅 Текущие дни: {days_text}\n\n"
                f"Выбери дни приёма добавки или нажми «⏭️ Пропустить».",
                reply_markup=days_menu(days, show_cancel=True),
            )
        else:
            await state.clear()
            await supplements(message)
        return
    
    # Проверяем пропуск (только в режиме теста)
    if supplement_id is None and message.text == "⏭️ Пропустить":
        # Получаем текущие данные и убеждаемся, что times и days сохранены как списки
        current_data = await state.get_data()
        times = current_data.get("times", [])
        days = current_data.get("days", [])
        
        # Убеждаемся, что times и days являются списками
        if not isinstance(times, list):
            times = [times] if times else []
        if not isinstance(days, list):
            days = [days] if days else []
        
        # Сохраняем все данные вместе
        await state.update_data(
            duration="постоянно",
            is_test_creation=True,
            times=times,  # Явно сохраняем как список
            days=days,    # Явно сохраняем как список
        )
        
        logger.info(f"User {message.from_user.id} skipped duration, saving: times={times}, days={days}")
        await ask_notifications_in_test(message, state)
        return
    
    # Проверяем выбор длительности
    if message.text in {"Постоянно", "14 дней", "30 дней"}:
        duration = message.text.lower()
        
        # Если это создание новой добавки (тест) - переходим к уведомлениям
        if supplement_id is None:
            # Получаем текущие данные и убеждаемся, что times и days сохранены как списки
            current_data = await state.get_data()
            times = current_data.get("times", [])
            days = current_data.get("days", [])
            
            # Убеждаемся, что times и days являются списками
            if not isinstance(times, list):
                times = [times] if times else []
            if not isinstance(days, list):
                days = [days] if days else []
            
            # Сохраняем все данные вместе, включая флаг is_test_creation
            await state.update_data(
                duration=duration,
                is_test_creation=True,
                times=times,  # Явно сохраняем как список
                days=days,    # Явно сохраняем как список
            )
            
            logger.info(f"User {message.from_user.id} selected duration, saving: times={times}, days={days}")
            await ask_notifications_in_test(message, state)
            return
        
        # Если это редактирование - показываем меню редактирования
        await state.update_data(duration=duration)
        
        # Если это редактирование - показываем меню редактирования
        await state.set_state(SupplementStates.editing_supplement)
        push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
        await message.answer(
            f"Длительность установлена: {message.text}\n\n"
            f"💊 {data.get('name', 'Добавка')}\n"
            f"⏰ Время: {', '.join(data.get('times', [])) or 'не выбрано'}\n"
            f"📅 Дни: {', '.join(data.get('days', [])) or 'не выбрано'}\n"
            f"⏳ Длительность: {duration}",
            reply_markup=supplement_edit_menu(show_save=True),
        )
        return
    
    # Если это неизвестное сообщение в режиме выбора длительности
    from utils.supplement_keyboards import duration_menu
    await message.answer(
        "Пожалуйста, выбери длительность приёма из меню:\n"
        "• Постоянно\n"
        "• 14 дней\n"
        "• 30 дней\n\n"
        "Или нажми «⏭️ Пропустить», чтобы оставить «Постоянно».",
        reply_markup=duration_menu(),
    )


async def save_supplement_from_test(message: Message, state: FSMContext):
    """Сохраняет добавку после завершения теста."""
    user_id = str(message.from_user.id)
    
    try:
        data = await state.get_data()
        
        name = data.get("name", "").strip()
        if not name:
            await message.answer("❌ Ошибка: название добавки не указано.")
            await state.clear()
            return
        
        supplement_payload = {
            "name": name,
            "times": data.get("times", []),
            "days": data.get("days", []),
            "duration": data.get("duration", "постоянно"),
            "notifications_enabled": data.get("notifications_enabled", False),
        }
        
        saved_id = SupplementRepository.save_supplement(user_id, supplement_payload)
        
        if saved_id:
            await state.clear()
            notifications_status = "включены" if supplement_payload.get("notifications_enabled", False) else "выключены"
            push_menu_stack(message.bot, supplements_main_menu(has_items=True))
            await message.answer(
                "✅ Добавка успешно создана!\n\n"
                f"💊 {supplement_payload['name']}\n"
                f"⏰ Время: {', '.join(supplement_payload['times']) or 'не указано'}\n"
                f"📅 Дни: {', '.join(supplement_payload['days']) or 'не указано'}\n"
                f"⏳ Длительность: {supplement_payload['duration']}\n"
                f"🔔 Уведомления: {notifications_status}",
                reply_markup=supplements_main_menu(has_items=True),
            )
        else:
            await message.answer("❌ Не удалось сохранить добавку. Попробуйте позже.")
            await state.clear()
    except Exception as e:
        logger.error(f"Error saving supplement from test for user {user_id}: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при сохранении добавки. Попробуйте позже.")
        await state.clear()


@router.message(SupplementStates.editing_supplement, lambda m: m.text == "🔔 Уведомления")
async def toggle_notifications(message: Message, state: FSMContext):
    """Переключает уведомления (для редактирования)."""
    data = await state.get_data()
    supplement_id = data.get("supplement_id")
    
    # Только для редактирования существующих добавок
    if supplement_id is not None:
        current_status = data.get("notifications_enabled", True)
        new_status = not current_status
        await state.update_data(notifications_enabled=new_status)
        status_text = "включены" if new_status else "выключены"
        push_menu_stack(message.bot, supplement_edit_menu(show_save=True))
        await message.answer(
            f"🔔 Уведомления {status_text}\n\n"
            f"Уведомления будут приходить в указанное время приема добавки.",
            reply_markup=supplement_edit_menu(show_save=True),
        )


@router.message(SupplementStates.editing_supplement, lambda m: m.text == "✏️ Изменить название")
async def rename_supplement(message: Message, state: FSMContext):
    """Начинает изменение названия добавки."""
    await state.set_state(SupplementStates.entering_name)
    await message.answer("Введите новое название добавки.")


@router.message(lambda m: m.text == "❌ Отменить")
async def cancel_supplement(message: Message, state: FSMContext):
    """Отменяет создание/редактирование добавки."""
    await state.clear()
    await supplements(message)


@router.message(lambda m: m.text == "📅 Календарь добавок")
async def show_supplement_calendar_menu(message: Message, state: FSMContext):
    """Показывает календарь добавок."""
    user_id = str(message.from_user.id)
    logger.info(f"User {user_id} opened supplement calendar")
    await state.clear()  # Очищаем состояние при открытии календаря
    await show_supplement_calendar(message, user_id)


async def show_supplement_calendar(message: Message, user_id: str, year: Optional[int] = None, month: Optional[int] = None):
    """Показывает календарь добавок."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    keyboard = build_supplement_calendar_keyboard(user_id, year, month)
    await message.answer(
        "📅 Календарь добавок. Выберите день, чтобы посмотреть, добавить или изменить приёмы:",
        reply_markup=keyboard,
    )


async def show_supplement_day_entries(message: Message, user_id: str, target_date: date):
    """Показывает записи приёма добавок за день."""
    entries = SupplementRepository.get_entries_for_day(user_id, target_date)
    
    if not entries:
        await message.answer(
            f"{target_date.strftime('%d.%m.%Y')}: приёмы не найдены. Можно добавить новый приём.",
            reply_markup=build_supplement_day_actions_keyboard([], target_date),
        )
        return
    
    lines = [
        f"📅 {target_date.strftime('%d.%m.%Y')} — приёмы добавок:",
        "Можно изменить, удалить или добавить ещё приём.",
    ]
    for entry in entries:
        amount_text = f" — {entry['amount']}" if entry.get("amount") is not None else ""
        lines.append(f"• {entry['supplement_name']} в {entry['time_text']}{amount_text}")
    
    await message.answer(
        "\n".join(lines),
        reply_markup=build_supplement_day_actions_keyboard(entries, target_date),
    )


@router.callback_query(lambda c: c.data == "supcal_close")
async def close_supplement_calendar(callback: CallbackQuery):
    """Закрывает календарь добавок."""
    await callback.answer("Календарь закрыт")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(lambda c: c.data.startswith("supcal_nav:"))
async def navigate_supplement_calendar(callback: CallbackQuery):
    """Навигация по календарю добавок."""
    await callback.answer()
    parts = callback.data.split(":")
    year, month = map(int, parts[1].split("-"))
    user_id = str(callback.from_user.id)
    keyboard = build_supplement_calendar_keyboard(user_id, year, month)
    await callback.message.edit_reply_markup(reply_markup=keyboard)


@router.callback_query(lambda c: c.data.startswith("supcal_back:"))
async def back_to_supplement_calendar(callback: CallbackQuery):
    """Возврат к календарю добавок."""
    await callback.answer()
    parts = callback.data.split(":")
    year, month = map(int, parts[1].split("-"))
    user_id = str(callback.from_user.id)
    await show_supplement_calendar(callback.message, user_id, year, month)


@router.callback_query(lambda c: c.data.startswith("supcal_day:"))
async def open_supplement_day(callback: CallbackQuery):
    """Открывает день в календаре добавок."""
    await callback.answer()
    parts = callback.data.split(":")
    date_str = parts[1]
    target_date = date.fromisoformat(date_str)
    user_id = str(callback.from_user.id)
    await show_supplement_day_entries(callback.message, user_id, target_date)


@router.callback_query(lambda c: c.data.startswith("supcal_add:"))
async def add_supplement_from_calendar(callback: CallbackQuery, state: FSMContext):
    """Добавляет приём добавки из календаря."""
    await callback.answer()
    parts = callback.data.split(":")
    target_date = date.fromisoformat(parts[1])
    user_id = str(callback.from_user.id)
    
    supplements_list = SupplementRepository.get_supplements(user_id)
    if not supplements_list:
        await callback.message.answer("Сначала создай добавку, чтобы отмечать приём.")
        return
    
    await state.update_data(entry_date=target_date.isoformat(), from_calendar=True)
    await state.set_state(SupplementStates.logging_intake)
    
    push_menu_stack(callback.message.bot, supplements_choice_menu(supplements_list))
    await callback.message.answer(
        f"Выбери добавку для отметки на {target_date.strftime('%d.%m.%Y')}:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@router.callback_query(lambda c: c.data.startswith("supcal_del:"))
async def delete_supplement_entry(callback: CallbackQuery):
    """Удаляет запись приёма добавки."""
    await callback.answer()
    parts = callback.data.split(":")
    target_date = date.fromisoformat(parts[1])
    sup_idx = int(parts[2]) if len(parts) > 2 else None
    entry_idx = int(parts[3]) if len(parts) > 3 else None
    user_id = str(callback.from_user.id)
    
    if sup_idx is None or entry_idx is None:
        await callback.message.answer("❌ Не найдена запись для удаления")
        await show_supplement_day_entries(callback.message, user_id, target_date)
        return
    
    supplements_list = SupplementRepository.get_supplements(user_id)
    if sup_idx >= len(supplements_list):
        await callback.message.answer("❌ Не нашёл запись для удаления")
        await show_supplement_day_entries(callback.message, user_id, target_date)
        return
    
    history = supplements_list[sup_idx].get("history", [])
    if entry_idx >= len(history):
        await callback.message.answer("❌ Не нашёл запись для удаления")
        await show_supplement_day_entries(callback.message, user_id, target_date)
        return
    
    removed = history[entry_idx]
    entry_id = removed.get("id") if isinstance(removed, dict) else None
    
    if entry_id:
        success = SupplementRepository.delete_entry(user_id, entry_id)
        if success:
            await callback.message.answer("✅ Приём удалён")
        else:
            await callback.message.answer("❌ Не удалось удалить запись")
    else:
        await callback.message.answer("❌ Не найдена запись для удаления")
    
    await show_supplement_day_entries(callback.message, user_id, target_date)


@router.callback_query(lambda c: c.data.startswith("supcal_edit:"))
async def edit_supplement_entry(callback: CallbackQuery, state: FSMContext):
    """Редактирует запись приёма добавки."""
    await callback.answer()
    parts = callback.data.split(":")
    target_date = date.fromisoformat(parts[1])
    sup_idx = int(parts[2]) if len(parts) > 2 else None
    entry_idx = int(parts[3]) if len(parts) > 3 else None
    user_id = str(callback.from_user.id)
    
    if sup_idx is None or entry_idx is None:
        await callback.message.answer("❌ Не найдена запись для редактирования")
        return
    
    supplements_list = SupplementRepository.get_supplements(user_id)
    if sup_idx >= len(supplements_list):
        await callback.message.answer("❌ Не нашёл запись для редактирования")
        return
    
    history = supplements_list[sup_idx].get("history", [])
    if entry_idx >= len(history):
        await callback.message.answer("❌ Не нашёл запись для редактирования")
        return
    
    entry = history[entry_idx]
    entry_id = entry.get("id")
    original_amount = entry.get("amount")
    original_timestamp = entry.get("timestamp")
    
    if isinstance(original_timestamp, str):
        try:
            original_timestamp = datetime.fromisoformat(original_timestamp)
        except (ValueError, TypeError):
            original_timestamp = datetime.combine(target_date, datetime.now().time())
    elif not isinstance(original_timestamp, datetime):
        original_timestamp = datetime.combine(target_date, datetime.now().time())
    
    # Удаляем старую запись
    if entry_id:
        SupplementRepository.delete_entry(user_id, entry_id)
    
    # Начинаем процесс добавления новой записи
    await state.update_data(
        supplement_name=supplements_list[sup_idx].get("name", ""),
        supplement_id=supplements_list[sup_idx].get("id"),
        entry_date=target_date.isoformat(),
        original_amount=original_amount,
        original_timestamp=original_timestamp.isoformat(),
    )
    await state.set_state(SupplementStates.entering_history_time)
    from utils.supplement_keyboards import supplement_history_time_menu
    push_menu_stack(callback.message.bot, supplement_history_time_menu())
    await callback.message.answer(
        f"Редактирование записи на {target_date.strftime('%d.%m.%Y')}.\n\n"
        f"Текущее время: {original_timestamp.strftime('%H:%M')}\n"
        f"Текущее количество: {original_amount or 'не указано'}\n\n"
        "Укажи новое время приёма в формате ЧЧ:ММ\n"
        "или нажми «⏭️ Пропустить», чтобы оставить текущее время.",
        reply_markup=supplement_history_time_menu(),
    )


def register_supplement_handlers(dp):
    """Регистрирует обработчики добавок."""
    dp.include_router(router)
