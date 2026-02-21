import asyncio
import nest_asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
import calendar
from collections import defaultdict
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    PhotoSize,
)
from aiogram.filters import Command
import os
import json
import html
from datetime import date
from dotenv import load_dotenv
import threading
import http.server
import socketserver
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine, Column, Integer, String, Date, Float, func, DateTime, Text, inspect, text, Boolean
from datetime import timedelta
import random
from datetime import datetime
import requests
import re
from google import genai
from google.genai import errors as genai_errors
from io import BytesIO

# Опциональный импорт matplotlib для графиков
try:
    import matplotlib
    matplotlib.use('Agg')  # Используем backend без GUI
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None
    mdates = None

load_dotenv()

# Глобальная переменная для отслеживания последней ошибки API
last_gemini_error = {"is_quota_exceeded": False, "message": ""}

# Создаём клиента Gemini (новый API)
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    print("⚠️ ВНИМАНИЕ: GEMINI_API_KEY не установлен в переменных окружения!")
    print("   Функции анализа через ИИ не будут работать.")
    client = None
else:
    try:
        client = genai.Client(api_key=gemini_api_key)
        print("✅ Gemini API клиент инициализирован")
    except Exception as e:
        print(f"❌ Ошибка при инициализации Gemini клиента: {repr(e)}")
        client = None

# Функция анализа данных через Gemini
def gemini_analyze(text: str) -> str:
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",  # новая рабочая модель
            contents=text
        )
        if not response or not response.text:
            print("❌ Gemini вернул пустой ответ")
            return "Сервис анализа временно недоступен, попробуй позже 🙏"
        return response.text
    except Exception as e:
        print("❌ Ошибка Gemini:", repr(e))
        return "Сервис анализа временно недоступен, попробуй позже 🙏"


def gemini_estimate_kbju(food_text: str) -> dict | None:
    """
    Оценивает КБЖУ через Gemini.

    Возвращает dict вида:
    {
      "items": [
        {"name": "курица", "grams": 100, "kcal": 165, "protein": 31, "fat": 4, "carbs": 0}
      ],
      "total": {"kcal": 165, "protein": 31, "fat": 4, "carbs": 0}
    }
    или None при ошибке.
    """
    global last_gemini_error
    
    if not client:
        print("❌ Gemini клиент не инициализирован (отсутствует API ключ)")
        return None
    
    prompt = f"""
Ты нутрициолог. Твоя задача — ОЦЕНИТЬ калории, белки, жиры и углеводы для списка продуктов.

Пользователь вводит на русском, например:
"200 г курицы, 100 г йогурта, 30 г орехов".

Требования:

1. Если вес не указан, оцени примерный (но лучше всегда использовать граммы из запроса).
2. Используй типичные значения для обычных продуктов (не бренд-специфично).
3. Ответь СТРОГО в формате JSON, БЕЗ объяснений, комментариев и оформления.

ФОРМАТ ОТВЕТА (пример):
{{
  "items": [
    {{
      "name": "курица",
      "grams": 200,
      "kcal": 330,
      "protein": 40,
      "fat": 15,
      "carbs": 0
    }},
    {{
      "name": "йогурт",
      "grams": 100,
      "kcal": 60,
      "protein": 5,
      "fat": 2,
      "carbs": 7
    }}
  ],
  "total": {{
    "kcal": 390,
    "protein": 45,
    "fat": 17,
    "carbs": 7
  }}
}}

Вот данные пользователя: "{food_text}"
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        if not response or not response.text:
            print("❌ Gemini вернул пустой ответ")
            return None
        # Сбрасываем флаг ошибки при успешном запросе
        last_gemini_error["is_quota_exceeded"] = False
        last_gemini_error["message"] = ""
        raw = response.text.strip()
        print("Gemini raw KBJU response:", raw)  # ← увидим в логах, что он реально вернул

        # 1) сначала пробуем распарсить как есть
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 2) если вдруг Gemini добавил лишний текст — вырежем JSON по первой { и последней }
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = raw[start : end + 1]
                return json.loads(snippet)

            # если и так не получилось — кидаем дальше
            raise

    except genai_errors.ClientError as e:
        error_str = str(e)
        is_quota_exceeded = (
            hasattr(e, 'status_code') and e.status_code == 429
        ) or "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower()
        
        # Сохраняем информацию об ошибке для показа пользователю
        last_gemini_error["is_quota_exceeded"] = is_quota_exceeded
        last_gemini_error["message"] = error_str[:500]
        
        if is_quota_exceeded:
            print("❌ Превышен лимит запросов к Gemini API (429 RESOURCE_EXHAUSTED)")
            print("   Лимит бесплатного тарифа: 20 запросов в день")
            print("   Подробности:", error_str[:500])
        else:
            status_code = getattr(e, 'status_code', 'неизвестен')
            print(f"❌ Ошибка Gemini API (код {status_code}):", error_str[:500])
        return None
    except Exception as e:
        print("❌ Ошибка Gemini (КБЖУ):", repr(e))
        import traceback
        traceback.print_exc()
        return None


def gemini_estimate_kbju_from_photo(image_bytes: bytes) -> dict | None:
    """
    Оценивает КБЖУ через Gemini Vision API по фото еды.

    Возвращает dict вида:
    {
      "items": [
        {"name": "курица", "grams": 100, "kcal": 165, "protein": 31, "fat": 4, "carbs": 0}
      ],
      "total": {"kcal": 165, "protein": 31, "fat": 4, "carbs": 0}
    }
    или None при ошибке.
    """
    global last_gemini_error
    
    if not client:
        print("❌ Gemini клиент не инициализирован (отсутствует API ключ)")
        return None
    
    prompt = """
Ты нутрициолог. Твоя задача — ОЦЕНИТЬ калории, белки, жиры и углеводы для еды на фотографии.

Проанализируй изображение и определи:
1. Какие продукты/блюда видны на фото
2. Примерный вес каждого продукта (в граммах)
3. КБЖУ для каждого продукта

Требования:
1. Оценивай вес продуктов визуально, исходя из типичных размеров порций
2. Используй типичные значения КБЖУ для обычных продуктов (не бренд-специфично)
3. Ответь СТРОГО в формате JSON, БЕЗ объяснений, комментариев и оформления

ФОРМАТ ОТВЕТА (пример):
{
  "items": [
    {
      "name": "курица",
      "grams": 200,
      "kcal": 330,
      "protein": 40,
      "fat": 15,
      "carbs": 0
    },
    {
      "name": "рис",
      "grams": 150,
      "kcal": 195,
      "protein": 4,
      "fat": 1,
      "carbs": 42
    }
  ],
  "total": {
    "kcal": 525,
    "protein": 44,
    "fat": 16,
    "carbs": 42
  }
}
"""

    try:
        # Используем Gemini Vision API
        # В новом API нужно передать изображение через Part
        try:
            from google.genai import types
            
            # Определяем MIME тип (по умолчанию jpeg, но можно определить по содержимому)
            mime_type = "image/jpeg"
            if image_bytes.startswith(b'\x89PNG'):
                mime_type = "image/png"
            elif image_bytes.startswith(b'GIF'):
                mime_type = "image/gif"
            elif image_bytes.startswith(b'WEBP'):
                mime_type = "image/webp"
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type
                    ),
                    prompt
                ]
            )
        except (ImportError, AttributeError) as e:
            # Если types не доступен, пробуем альтернативный способ
            print(f"⚠️ Не удалось использовать types.Part, пробуем альтернативный способ: {e}")
            # Пробуем через PIL если доступен
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(image_bytes))
                # Конвертируем в base64 и передаем как текст (не идеально, но работает)
                import base64
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                # Это не будет работать для Vision API, но оставим как fallback
                raise NotImplementedError("Vision API требует types.Part")
            except Exception:
                raise Exception("Не удалось обработать изображение. Убедитесь, что установлен google-genai с поддержкой Vision API")
        
        if not response or not response.text:
            print("❌ Gemini вернул пустой ответ для фото еды")
            return None
        # Сбрасываем флаг ошибки при успешном запросе
        last_gemini_error["is_quota_exceeded"] = False
        last_gemini_error["message"] = ""
        raw = response.text.strip()
        print("Gemini raw KBJU response from photo:", raw[:500])  # первые 500 символов для логов

        # Парсим JSON ответ
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Если Gemini добавил лишний текст — вырежем JSON
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = raw[start : end + 1]
                return json.loads(snippet)
            raise

    except genai_errors.ClientError as e:
        error_str = str(e)
        is_quota_exceeded = (
            hasattr(e, 'status_code') and e.status_code == 429
        ) or "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower()
        
        # Сохраняем информацию об ошибке для показа пользователю
        last_gemini_error["is_quota_exceeded"] = is_quota_exceeded
        last_gemini_error["message"] = error_str[:500]
        
        if is_quota_exceeded:
            print("❌ Превышен лимит запросов к Gemini API (429 RESOURCE_EXHAUSTED)")
            print("   Лимит бесплатного тарифа: 20 запросов в день")
            print("   Подробности:", error_str[:500])
        else:
            status_code = getattr(e, 'status_code', 'неизвестен')
            print(f"❌ Ошибка Gemini API (код {status_code}):", error_str[:500])
        return None
    except Exception as e:
        print("❌ Ошибка Gemini (КБЖУ по фото):", repr(e))
        import traceback
        traceback.print_exc()
        return None


def gemini_extract_kbju_from_label(image_bytes: bytes) -> dict | None:
    """
    Извлекает КБЖУ из текста на этикетке/упаковке через Gemini Vision API.

    Возвращает dict вида:
    {
      "product_name": "название продукта",
      "kbju_per_100g": {
        "kcal": 200,
        "protein": 10,
        "fat": 5,
        "carbs": 30
      },
      "package_weight": 50,  # вес упаковки в граммах, если найден, иначе null
      "found_weight": true/false  # найден ли вес на упаковке
    }
    или None при ошибке.
    """
    global last_gemini_error
    
    if not client:
        print("❌ Gemini клиент не инициализирован (отсутствует API ключ)")
        return None
    
    prompt = """
Ты анализируешь фото этикетки или упаковки продукта. Твоя задача — найти в тексте информацию о КБЖУ (калориях, белках, жирах, углеводах).

ВАЖНО:
1. Прочитай весь текст на этикетке/упаковке
2. Найди таблицу пищевой ценности или информацию о КБЖУ
3. Обычно КБЖУ указывается на 100 грамм продукта
4. Также попробуй найти вес упаковки/порции (может быть указан как "масса нетто", "вес", "порция" и т.д.)

Ответь СТРОГО в формате JSON, БЕЗ объяснений, комментариев и оформления:

{
  "product_name": "название продукта (если видно)",
  "kbju_per_100g": {
    "kcal": число_калорий_на_100г,
    "protein": число_белков_на_100г,
    "fat": число_жиров_на_100г,
    "carbs": число_углеводов_на_100г
  },
  "package_weight": число_грамм_упаковки_или_null,
  "found_weight": true_если_найден_вес_иначе_false
}

Если не нашёл КБЖУ в тексте, верни null для всех значений.
Если нашёл КБЖУ, но не нашёл вес упаковки, установи "package_weight": null и "found_weight": false.
"""

    try:
        from google.genai import types
        
        mime_type = "image/jpeg"
        if image_bytes.startswith(b'\x89PNG'):
            mime_type = "image/png"
        elif image_bytes.startswith(b'GIF'):
            mime_type = "image/gif"
        elif image_bytes.startswith(b'WEBP'):
            mime_type = "image/webp"
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                ),
                prompt
            ]
        )
        
        if not response or not response.text:
            print("❌ Gemini вернул пустой ответ для этикетки")
            return None
        # Сбрасываем флаг ошибки при успешном запросе
        last_gemini_error["is_quota_exceeded"] = False
        last_gemini_error["message"] = ""
        raw = response.text.strip()
        print("Gemini raw label KBJU response:", raw[:500])

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = raw[start : end + 1]
                return json.loads(snippet)
            raise

    except genai_errors.ClientError as e:
        error_str = str(e)
        is_quota_exceeded = (
            hasattr(e, 'status_code') and e.status_code == 429
        ) or "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower()
        
        # Сохраняем информацию об ошибке для показа пользователю
        last_gemini_error["is_quota_exceeded"] = is_quota_exceeded
        last_gemini_error["message"] = error_str[:500]
        
        if is_quota_exceeded:
            print("❌ Превышен лимит запросов к Gemini API (429 RESOURCE_EXHAUSTED)")
            print("   Лимит бесплатного тарифа: 20 запросов в день")
            print("   Подробности:", error_str[:500])
        else:
            status_code = getattr(e, 'status_code', 'неизвестен')
            print(f"❌ Ошибка Gemini API (код {status_code}):", error_str[:500])
        return None
    except Exception as e:
        print("❌ Ошибка Gemini (КБЖУ с этикетки):", repr(e))
        import traceback
        traceback.print_exc()
        return None


def gemini_scan_barcode(image_bytes: bytes) -> str | None:
    """
    Распознаёт штрих-код на фото через Gemini Vision API.
    
    Возвращает строку с номером штрих-кода (EAN-13, UPC и т.д.) или None при ошибке.
    """
    global last_gemini_error
    
    if not client:
        print("❌ Gemini клиент не инициализирован (отсутствует API ключ)")
        return None
    
    prompt = """
Ты видишь фото со штрих-кодом. Твоя задача — прочитать номер штрих-кода.

ВАЖНО:
1. Найди штрих-код на изображении (обычно это вертикальные полоски с цифрами под ними)
2. Прочитай все цифры, которые видны под штрих-кодом
3. Верни ТОЛЬКО номер штрих-кода (цифры), БЕЗ пробелов, дефисов и других символов
4. Если штрих-код не виден или нечитаем, верни "NOT_FOUND"

Примеры правильных ответов:
- 4607025392134
- 3017620422003
- 5449000000996

Ответь ТОЛЬКО номером штрих-кода, без дополнительных объяснений.
"""

    try:
        from google.genai import types
        
        mime_type = "image/jpeg"
        if image_bytes.startswith(b'\x89PNG'):
            mime_type = "image/png"
        elif image_bytes.startswith(b'GIF'):
            mime_type = "image/gif"
        elif image_bytes.startswith(b'WEBP'):
            mime_type = "image/webp"
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                ),
                prompt
            ]
        )
        
        if not response or not response.text:
            print("❌ Gemini вернул пустой ответ для штрих-кода")
            return None
        # Сбрасываем флаг ошибки при успешном запросе
        last_gemini_error["is_quota_exceeded"] = False
        last_gemini_error["message"] = ""
        raw = response.text.strip()
        print("Gemini raw barcode response:", raw)
        
        # Очищаем ответ от лишних символов
        barcode = raw.replace(" ", "").replace("-", "").replace("_", "")
        
        # Проверяем, что это похоже на штрих-код (обычно 8-13 цифр)
        if barcode.isdigit() and 8 <= len(barcode) <= 14:
            return barcode
        elif barcode.upper() == "NOT_FOUND":
            return None
        else:
            # Пробуем извлечь только цифры
            digits = ''.join(filter(str.isdigit, barcode))
            if 8 <= len(digits) <= 14:
                return digits
            return None

    except genai_errors.ClientError as e:
        error_str = str(e)
        is_quota_exceeded = (
            hasattr(e, 'status_code') and e.status_code == 429
        ) or "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower()
        
        # Сохраняем информацию об ошибке для показа пользователю
        last_gemini_error["is_quota_exceeded"] = is_quota_exceeded
        last_gemini_error["message"] = error_str[:500]
        
        if is_quota_exceeded:
            print("❌ Превышен лимит запросов к Gemini API (429 RESOURCE_EXHAUSTED)")
            print("   Лимит бесплатного тарифа: 20 запросов в день")
            print("   Подробности:", error_str[:500])
        else:
            status_code = getattr(e, 'status_code', 'неизвестен')
            print(f"❌ Ошибка Gemini API (код {status_code}):", error_str[:500])
        return None
    except Exception as e:
        print("❌ Ошибка Gemini (распознавание штрих-кода):", repr(e))
        import traceback
        traceback.print_exc()
        return None


def get_product_from_openfoodfacts(barcode: str) -> dict | None:
    """
    Получает информацию о продукте из Open Food Facts API по штрих-коду.
    
    Возвращает dict с информацией о продукте или None при ошибке.
    """
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    
    try:
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            print(f"Open Food Facts API error: HTTP {resp.status_code}")
            return None
        
        data = resp.json()
        
        if data.get("status") != 1:
            print(f"Product not found in Open Food Facts: {barcode}")
            return None
        
        product = data.get("product", {})
        
        # Извлекаем основную информацию
        result = {
            "name": product.get("product_name") or product.get("product_name_ru") or product.get("product_name_en") or "Неизвестный продукт",
            "brand": product.get("brands") or "",
            "barcode": barcode,
            "nutriments": {}
        }
        
        # Извлекаем КБЖУ (на 100г)
        nutriments = product.get("nutriments", {})
        
        # Логируем для отладки - выводим все ключи nutriments
        print(f"DEBUG: Open Food Facts barcode {barcode}")
        print(f"DEBUG: Product name: {result['name']}")
        print(f"DEBUG: All nutriments keys ({len(nutriments)}): {list(nutriments.keys())[:50]}")  # Первые 50 ключей
        
        # Функция для безопасного извлечения числа из разных форматов
        def safe_float(value):
            if value is None:
                return None
            try:
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    # Убираем пробелы и пробуем распарсить
                    cleaned = value.strip().replace(',', '.')
                    return float(cleaned)
                return None
            except (ValueError, TypeError):
                return None
        
        # Калории - проверяем все возможные варианты
        kcal = None
        # Приоритет: сначала ищем на 100г, потом общее значение
        for key in ["energy-kcal_100g", "energy-kcal", "energy_100g", "energy-kcal_value", 
                    "energy-kcal_serving", "energy_serving", "energy"]:
            if key in nutriments:
                kcal = safe_float(nutriments[key])
                if kcal is not None and kcal > 0:
                    print(f"DEBUG: Found kcal from key '{key}': {kcal}")
                    break
        
        # Если не нашли в ккал, пробуем конвертировать из кДж (1 ккал = 4.184 кДж)
        if not kcal or kcal <= 0:
            energy_kj = None
            for key in ["energy-kj_100g", "energy-kj", "energy-kj_value", "energy-kj_serving"]:
                if key in nutriments:
                    energy_kj = safe_float(nutriments[key])
                    if energy_kj is not None and energy_kj > 0:
                        print(f"DEBUG: Found energy in kJ from key '{key}': {energy_kj}")
                        break
            
            if energy_kj and energy_kj > 0:
                try:
                    kcal = energy_kj / 4.184
                    print(f"DEBUG: Converted energy from kJ to kcal: {energy_kj} kJ = {kcal:.2f} kcal")
                except (ValueError, TypeError):
                    pass
        
        if kcal and kcal > 0:
            result["nutriments"]["kcal"] = kcal
        
        # Белки - проверяем все возможные варианты
        protein = None
        for key in ["proteins_100g", "proteins", "protein_100g", "protein", 
                    "proteins_value", "proteins_serving", "protein_serving"]:
            if key in nutriments:
                protein = safe_float(nutriments[key])
                if protein is not None and protein >= 0:
                    print(f"DEBUG: Found protein from key '{key}': {protein}")
                    break
        
        if protein is not None and protein >= 0:
            result["nutriments"]["protein"] = protein
        
        # Жиры - проверяем все возможные варианты
        fat = None
        for key in ["fat_100g", "fat", "fats_100g", "fats", 
                    "fat_value", "fat_serving", "fats_serving"]:
            if key in nutriments:
                fat = safe_float(nutriments[key])
                if fat is not None and fat >= 0:
                    print(f"DEBUG: Found fat from key '{key}': {fat}")
                    break
        
        if fat is not None and fat >= 0:
            result["nutriments"]["fat"] = fat
        
        # Углеводы - проверяем все возможные варианты
        carbs = None
        for key in ["carbohydrates_100g", "carbohydrates", "carbohydrate_100g", "carbohydrate",
                    "carbohydrates_value", "carbohydrates_serving", "carbohydrate_serving", "carbs_100g", "carbs"]:
            if key in nutriments:
                carbs = safe_float(nutriments[key])
                if carbs is not None and carbs >= 0:
                    print(f"DEBUG: Found carbs from key '{key}': {carbs}")
                    break
        
        if carbs is not None and carbs >= 0:
            result["nutriments"]["carbs"] = carbs
        
        # Логируем итоговый результат
        print(f"DEBUG: Final extracted KBJU - kcal: {result['nutriments'].get('kcal')}, "
              f"protein: {result['nutriments'].get('protein')}, "
              f"fat: {result['nutriments'].get('fat')}, "
              f"carbs: {result['nutriments'].get('carbs')}")
        
        # Вес продукта (если указан)
        weight = product.get("quantity") or product.get("product_quantity") or product.get("net_weight") or product.get("weight")
        if weight:
            # Пробуем извлечь число из строки типа "200g" или "200 г"
            import re
            weight_match = re.search(r'(\d+)', str(weight))
            if weight_match:
                result["weight"] = int(weight_match.group(1))
                print(f"DEBUG: Found product weight: {result['weight']} g")
        
        # Дополнительная информация
        result["ingredients"] = product.get("ingredients_text") or product.get("ingredients_text_ru") or product.get("ingredients_text_en") or ""
        result["categories"] = product.get("categories") or ""
        result["image_url"] = product.get("image_url") or product.get("image_front_url") or ""
        
        return result
        
    except Exception as e:
        print(f"❌ Ошибка при запросе к Open Food Facts: {repr(e)}")
        import traceback
        traceback.print_exc()
        return None


def translate_text(text: str, source_lang: str = "ru", target_lang: str = "en") -> str:
    """Переводит текст через публичное API MyMemory.

    При ошибках возвращает исходный текст, чтобы логика не падала.
    """
    if not text:
        return text

    def contains_cyrillic(value: str) -> bool:
        return any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in value)

    url = "https://api.mymemory.translated.net/get"
    params = {"q": text, "langpair": f"{source_lang}|{target_lang}"}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        translated = (
            data.get("responseData", {}).get("translatedText")
            or data.get("matches", [{}])[0].get("translation")
        )
    except Exception as e:
        print("⚠️ Ошибка перевода через MyMemory:", repr(e))
        translated = None

    # CalorieNinjas не понимает кириллицу, поэтому если MyMemory не справился,
    # пробуем резервный вариант через translate.googleapis.com, который обычно
    # устойчивее.
    if (not translated or contains_cyrillic(translated)) and contains_cyrillic(text):
        try:
            g_url = "https://translate.googleapis.com/translate_a/single"
            g_params = {
                "client": "gtx",
                "sl": source_lang,
                "tl": target_lang,
                "dt": "t",
                "q": text,
            }
            g_resp = requests.get(g_url, params=g_params, timeout=10)
            g_resp.raise_for_status()
            g_data = g_resp.json()
            # формат: [[['перевод', 'оригинал', null, null, ...]], ...]
            translated = g_data[0][0][0] if g_data and g_data[0] else translated
        except Exception as e:
            print("⚠️ Ошибка резервного перевода через Google:", repr(e))

    return translated or text




DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # перед запросом проверяет соединение и перевтыкается при обрыве
    pool_recycle=1800,    # переоткрывать коннект раз в ~30 минут
)

Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

MONTH_NAMES = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)

class Workout(Base):
    __tablename__ = "workouts"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    exercise = Column(String, nullable=False)
    variant = Column(String)
    count = Column(Integer)
    date = Column(Date, default=date.today)
    # 🔥 Новое поле — примерные сожжённые калории
    calories = Column(Float, default=0)

class Weight(Base):
    __tablename__ = "weights"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    value = Column(String, nullable=False)
    date = Column(Date, default=date.today)

class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    chest = Column(Float, nullable=True)
    waist = Column(Float, nullable=True)
    hips = Column(Float, nullable=True)
    biceps = Column(Float, nullable=True)
    thigh = Column(Float, nullable=True)
    date = Column(Date, default=date.today)


class Meal(Base):
    __tablename__ = "meals"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    description = Column(String, nullable=True)
    raw_query = Column(String)
    products_json = Column(Text, default="[]")   # 👈 сюда будем класть продукты из API
    api_details = Column(Text, nullable=True)      # текстовая раскладка продуктов
    calories = Column(Float, default=0)
    protein = Column(Float, default=0)
    fat = Column(Float, default=0)
    carbs = Column(Float, default=0)
    date = Column(Date, default=date.today)



class KbjuSettings(Base):
    __tablename__ = "kbju_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, unique=True, index=True)

    calories = Column(Float, nullable=False)
    protein = Column(Float, nullable=False)
    fat = Column(Float, nullable=False)
    carbs = Column(Float, nullable=False)

    goal = Column(String, nullable=True)      # "loss" / "maintain" / "gain"
    activity = Column(String, nullable=True)  # "low" / "medium" / "high"
    updated_at = Column(DateTime, default=datetime.utcnow)


class Supplement(Base):
    __tablename__ = "supplements"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    times_json = Column(Text, default="[]")
    days_json = Column(Text, default="[]")
    duration = Column(String, default="постоянно")
    notifications_enabled = Column(Boolean, default=True, nullable=True)


class SupplementEntry(Base):
    __tablename__ = "supplement_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    supplement_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=True)


class Procedure(Base):
    __tablename__ = "procedures"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)  # название процедуры
    date = Column(Date, default=date.today)
    notes = Column(String, nullable=True)  # дополнительные заметки


class WaterEntry(Base):
    __tablename__ = "water_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False)  # количество воды в мл
    date = Column(Date, default=date.today)
    timestamp = Column(DateTime, default=datetime.utcnow)  # время записи


Base.metadata.create_all(engine)

# Простая миграция для добавления столбцов
with engine.connect() as conn:
    inspector = inspect(conn)

    # supplement_entries.amount
    columns = {col["name"] for col in inspector.get_columns("supplement_entries")}
    if "amount" not in columns:
        conn.execute(text("ALTER TABLE supplement_entries ADD COLUMN amount FLOAT"))
        conn.commit()

    # 🔥 workouts.calories
    workout_columns = {col["name"] for col in inspector.get_columns("workouts")}
    if "calories" not in workout_columns:
        conn.execute(text("ALTER TABLE workouts ADD COLUMN calories FLOAT"))
        conn.commit()


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def start_keepalive_server():
    PORT = 10000
    handler = http.server.SimpleHTTPRequestHandler
    with ReusableTCPServer(("", PORT), handler) as httpd:
        print(f"✅ Keep-alive сервер запущен на порту {PORT}")
        httpd.serve_forever()

# Запуск мини-сервера в отдельном потоке
threading.Thread(target=start_keepalive_server, daemon=True).start()

API_TOKEN = os.getenv("API_TOKEN")
NUTRITION_API_KEY = os.getenv("NUTRITION_API_KEY")  # 🔸 новый ключ CalorieNinjas

if not API_TOKEN:
    raise RuntimeError("API_TOKEN не найден. Установи переменную окружения или создай .env с API_TOKEN.")

if not NUTRITION_API_KEY:
    print("⚠️ ВНИМАНИЕ: NUTRITION_API_KEY не найден. КБЖУ через CalorieNinjas работать не будет.")





bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# -------------------- helpers --------------------


def get_nutrition_from_api(query: str):
    """
    Вызывает CalorieNinjas /v1/nutrition и возвращает (items, totals).
    items — список продуктов (list), totals — суммарные калории и БЖУ.
    """
    if not NUTRITION_API_KEY:
        raise RuntimeError("NUTRITION_API_KEY не задан в переменных окружения")

    url = "https://api.calorieninjas.com/v1/nutrition"
    headers = {"X-Api-Key": NUTRITION_API_KEY}
    params = {"query": query}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    except Exception as e:
        print("❌ Ошибка сети при запросе к CalorieNinjas:", repr(e))
        raise

    print(f"CalorieNinjas status: {resp.status_code}")
    print("CalorieNinjas raw response:", resp.text[:500])

    if resp.status_code != 200:
        print("Ответ от CalorieNinjas (non-200):", resp.text[:500])
        raise RuntimeError(f"CalorieNinjas error: HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception as e:
        print("❌ Не получилось распарсить JSON от CalorieNinjas:", resp.text[:500])
        raise

    # формат: {"items": [ {...}, {...}, ... ]}
    if not isinstance(data, dict) or "items" not in data:
        print("❌ Неожиданный формат ответа от CalorieNinjas:", data)
        raise RuntimeError("Unexpected response format from CalorieNinjas")

    items = data.get("items") or []

    def safe_float(v) -> float:
        try:
            if v is None:
                return 0.0
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    totals = {
        "calories": 0.0,
        "protein_g": 0.0,
        "fat_total_g": 0.0,
        "carbohydrates_total_g": 0.0,
    }

    for item in items:
        cal = safe_float(item.get("calories"))
        p = safe_float(item.get("protein_g"))
        f = safe_float(item.get("fat_total_g"))
        c = safe_float(item.get("carbohydrates_total_g"))

        # кладём приведённые значения обратно, чтобы handle_food_input удобно их читал
        item["_calories"] = cal
        item["_protein_g"] = p
        item["_fat_total_g"] = f
        item["_carbohydrates_total_g"] = c

        totals["calories"] += cal
        totals["protein_g"] += p
        totals["fat_total_g"] += f
        totals["carbohydrates_total_g"] += c

    return items, totals



def save_meal_entry(
    user_id: str, raw_query: str, totals: dict, entry_date: date, api_details: str | None = None
):
    session = SessionLocal()
    try:
        meal = Meal(
            user_id=str(user_id),
            # что вводил пользователь
            raw_query=raw_query,
            # можно пока дублировать сюда
            description=raw_query,
            # суммарные КБЖУ по приёму пищи
            calories=float(totals.get("calories", 0.0)),
            protein=float(totals.get("protein_g", 0.0)),
            fat=float(totals.get("fat_total_g", 0.0)),
            carbs=float(totals.get("carbohydrates_total_g", 0.0)),
            date=entry_date,
            api_details=api_details,
            # сюда позже будем класть подробный список продуктов (если уже сделали products_json)
            products_json=json.dumps(totals.get("products", [])) if "products" in totals else "[]",
        )
        session.add(meal)
        session.commit()
    finally:
        session.close()



def update_meal_entry(
    meal_id: int,
    user_id: str,
    description: str,
    totals: dict,
    api_details: str | None = None,
) -> bool:
    session = SessionLocal()
    try:
        meal = session.query(Meal).filter_by(id=meal_id, user_id=str(user_id)).first()
        if not meal:
            return False

        meal.description = description
        meal.raw_query = description
        meal.calories = float(totals.get("calories", 0.0))
        meal.protein = float(totals.get("protein_g", 0.0))
        meal.fat = float(totals.get("fat_total_g", 0.0))
        meal.carbs = float(totals.get("carbohydrates_total_g", 0.0))
        meal.api_details = api_details
        # Обновляем products_json если есть продукты в totals
        if "products" in totals:
            meal.products_json = json.dumps(totals["products"])
        session.commit()
        return True
    finally:
        session.close()


def delete_meal_entry(meal_id: int, user_id: str):
    session = SessionLocal()
    try:
        meal = session.query(Meal).filter_by(id=meal_id, user_id=str(user_id)).first()
        if not meal:
            return None

        entry_date = meal.date
        description = meal.description
        session.delete(meal)
        session.commit()
        return entry_date, description
    finally:
        session.close()


def delete_user_account(user_id: str) -> bool:
    """
    Удаляет все данные пользователя из базы данных.
    Возвращает True если успешно, False при ошибке.
    """
    session = SessionLocal()
    try:
        # Удаляем все данные пользователя из всех таблиц
        session.query(Workout).filter_by(user_id=user_id).delete()
        session.query(Weight).filter_by(user_id=user_id).delete()
        session.query(Measurement).filter_by(user_id=user_id).delete()
        session.query(Meal).filter_by(user_id=user_id).delete()
        session.query(KbjuSettings).filter_by(user_id=user_id).delete()
        session.query(SupplementEntry).filter_by(user_id=user_id).delete()
        session.query(Supplement).filter_by(user_id=user_id).delete()
        session.query(Procedure).filter_by(user_id=user_id).delete()
        session.query(WaterEntry).filter_by(user_id=user_id).delete()
        session.query(User).filter_by(user_id=user_id).delete()
        
        session.commit()
        return True
    except Exception as e:
        print(f"❌ Ошибка при удалении аккаунта пользователя {user_id}:", repr(e))
        session.rollback()
        return False
    finally:
        session.close()


def get_daily_meal_totals(user_id: str, entry_date: date):
    session = SessionLocal()
    try:
        sums = (
            session.query(
                func.coalesce(func.sum(Meal.calories), 0),
                func.coalesce(func.sum(Meal.protein), 0),
                func.coalesce(func.sum(Meal.fat), 0),
                func.coalesce(func.sum(Meal.carbs), 0),
            )
            .filter(Meal.user_id == str(user_id), Meal.date == entry_date)
            .one()
        )
        return {
            "calories": float(sums[0] or 0),
            "protein_g": float(sums[1] or 0),
            "fat_total_g": float(sums[2] or 0),
            "carbohydrates_total_g": float(sums[3] or 0),
        }
    finally:
        session.close()



def get_daily_workout_calories(user_id: str, entry_date: date) -> float:
    """Получает общее количество сожженных калорий за день от тренировок"""
    workouts = get_workouts_for_day(user_id, entry_date)
    total_calories = 0.0
    for w in workouts:
        entry_calories = w.calories or calculate_workout_calories(
            user_id, w.exercise, w.variant, w.count
        )
        total_calories += entry_calories
    return total_calories


def get_meals_for_date(user_id: str, entry_date: date) -> list[Meal]:
    session = SessionLocal()
    try:
        return (
            session.query(Meal)
            .filter(Meal.user_id == str(user_id), Meal.date == entry_date)
            .order_by(Meal.id.asc())
            .all()
        )
    finally:
        session.close()


 # ---------- КБЖУ: норма / цели ----------

def get_kbju_settings(user_id: str) -> KbjuSettings | None:
    session = SessionLocal()
    try:
        return session.query(KbjuSettings).filter_by(user_id=str(user_id)).first()
    finally:
        session.close()


def save_kbju_settings(
    user_id: str,
    calories: float,
    protein: float,
    fat: float,
    carbs: float,
    goal: str | None = None,
    activity: str | None = None,
) -> None:
    session = SessionLocal()
    try:
        settings = session.query(KbjuSettings).filter_by(user_id=str(user_id)).first()
        if not settings:
            settings = KbjuSettings(user_id=str(user_id))

        settings.calories = float(calories)
        settings.protein = float(protein)
        settings.fat = float(fat)
        settings.carbs = float(carbs)
        settings.goal = goal
        settings.activity = activity
        settings.updated_at = datetime.utcnow()

        session.add(settings)
        session.commit()
    finally:
        session.close()


def format_kbju_goal_text(calories: float, protein: float, fat: float, carbs: float, goal_label: str) -> str:
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
    goal_label = get_kbju_goal_label(settings.goal)
    return (
        "🎯 Твоя текущая цель по КБЖУ:\n\n"
        f"🔥 Калории: <b>{settings.calories:.0f} ккал</b>\n"
        f"💪 Белки: <b>{settings.protein:.0f} г</b>\n"
        f"🧈 Жиры: <b>{settings.fat:.0f} г</b>\n"
        f"🍞 Углеводы: <b>{settings.carbs:.0f} г</b>\n\n"
        f"Цель: <b>{goal_label}</b>"
    )


def get_kbju_test_session(bot, user_id: str) -> dict:
    if not hasattr(bot, "kbju_test_sessions"):
        bot.kbju_test_sessions = {}
    return bot.kbju_test_sessions.setdefault(user_id, {})


def clear_kbju_test_session(bot, user_id: str):
    if hasattr(bot, "kbju_test_sessions"):
        bot.kbju_test_sessions.pop(user_id, None)
    if hasattr(bot, "kbju_test_step"):
        bot.kbju_test_step = None


def calculate_kbju_from_test(data: dict) -> tuple[float, float, float, float, str]:
    """
    data: gender ('male'/'female'), age, height, weight, activity('low'/'medium'/'high'), goal('loss'/'maintain'/'gain')
    Возвращает: (calories, protein, fat, carbs, goal_label)
    """
    gender = data.get("gender")
    age = float(data.get("age", 30))
    height = float(data.get("height", 170))
    weight = float(data.get("weight", 70))
    activity = data.get("activity", "medium")
    goal = data.get("goal", "maintain")

    # BMR по Mifflin-St Jeor
    if gender == "female":
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age + 5

    activity_factor = {
        "low": 1.2,
        "medium": 1.4,
        "high": 1.6,
    }.get(activity, 1.4)

    tdee = bmr * activity_factor

    if goal == "loss":
        calories = tdee * 0.8   # -20%
        goal_label = "Похудение"
    elif goal == "gain":
        calories = tdee * 1.1   # +10%
        goal_label = "Набор массы"
    else:
        calories = tdee
        goal_label = "Поддержание веса"

    # Макросы
    protein = weight * 1.8
    fat = weight * 0.9
    used_kcal = protein * 4 + fat * 9
    carbs = max((calories - used_kcal) / 4, 0)

    return calories, protein, fat, carbs, goal_label
   



def add_workout(user_id, exercise, variant, count):
    session = SessionLocal()
    try:
        calories = calculate_workout_calories(str(user_id), exercise, variant, count)
        workout = Workout(
            user_id=str(user_id),
            exercise=exercise,
            variant=variant,
            count=count,
            date=date.today(),
            calories=calories,
        )
        session.add(workout)
        session.commit()
    finally:
        session.close()


def get_last_weight_kg(user_id: str) -> float | None:
    """Берём последний записанный вес пользователя (кг)."""
    session = SessionLocal()
    try:
        w = (
            session.query(Weight)
            .filter(Weight.user_id == str(user_id))
            .order_by(Weight.date.desc(), Weight.id.desc())
            .first()
        )
        if not w:
            return None
        try:
            return float(str(w.value).replace(",", "."))
        except ValueError:
            return None
    finally:
        session.close()


def estimate_met_for_exercise(exercise: str) -> float:
    """Очень грубая оценка интенсивности упражнения (MET)."""
    name = (exercise or "").lower()
    if "ходь" in name or "walk" in name:
        return 3.5
    if "бег" in name or "run" in name:
        return 7.0
    if "прыж" in name or "jump" in name:
        return 8.0
    if "присед" in name or "squat" in name:
        return 5.0
    if "отжим" in name or "push" in name:
        return 5.0
    # по умолчанию — умеренная нагрузка
    return 4.5


def calculate_workout_calories(
    user_id: str,
    exercise: str,
    variant: str | None,
    count: int | float,
) -> float:
    """
    Грубая оценка калорий по тренировке.
    - Если variant == "Минуты" — считаем по формуле MET.
    - Если variant == "Количество шагов" — переводим шаги в минуты.
    - Иначе считаем по повторам.
    """

    weight = get_last_weight_kg(user_id) or 75.0  # дефолт, если веса нет
    count = float(count or 0)

    # 1️⃣ Упражнения по времени (Минуты)
    if variant == "Минуты":
        minutes = count
        met = estimate_met_for_exercise(exercise)
        # формула: калории = MET * 3.5 * вес(кг) / 200 * минуты
        return met * 3.5 * weight / 200.0 * minutes

    # 2️⃣ Ходьба по шагам
    if variant == "Количество шагов":
        steps = count
        # грубо: ~80 шагов в минуту
        minutes = steps / 80.0
        # Калибруем под ~16k шагов ≈ 528 ккал при весе 75 кг: MET ≈ 2.0
        met = 2.0  # очень лёгкая активность (прогулка)
        return met * 3.5 * weight / 200.0 * minutes

    # 3️⃣ Всё остальное — по повторам
    reps = count
    # базово: ~0.4 ккал за повтор для 70 кг, масштабируем по весу
    base_per_rep = 0.4
    return reps * base_per_rep * (weight / 70.0)

def get_today_summary_text(user_id: str) -> str:
    session = SessionLocal()
    try:
        today = date.today()
        today_str = datetime.now().strftime("%d.%m.%Y")

        greetings = [
            "🔥 Новый день — новые победы!",
            "🚀 Пора действовать!",
            "💪 Сегодня ты становишься сильнее!",
            "🌟 Всё получится, просто начни!",
            "🏁 Вперёд к цели!",
        ]
        motivation = random.choice(greetings)

        # --- записи за сегодня ---
        workouts = session.query(Workout).filter_by(user_id=user_id, date=today).all()
        meals_today = session.query(Meal).filter_by(user_id=user_id, date=today).all()

        # --- последний вес ---
        weight = (
            session.query(Weight)
            .filter_by(user_id=user_id)
            .order_by(Weight.id.desc())
            .first()
        )

        # --- последние замеры ---
        m = (
            session.query(Measurement)
            .filter_by(user_id=user_id)
            .order_by(Measurement.id.desc())
            .first()
        )

        # Есть ли вообще что-то за сегодня
        has_today_anything = bool(workouts or meals_today)

        # 🔹 Полный онбординг, если за сегодня нет ни тренировок, ни еды
        if not has_today_anything:
            summary_lines = [
                f"Сегодня ({today_str}) у тебя пока нет записей 📭\n",
                "🏋️ <b>Тренировки</b>\n"
                "Записывай подходы, время и шаги. Бот считает примерный расход калорий "
                "по типу упражнения, длительности/повторам и твоему весу.",
                "\n🍱 <b>Питание</b>\n"
                "Добавляй приёмы пищи — я посчитаю КБЖУ для каждого приёма и суммарно за день.",
                "\n⚖️ <b>Вес и замеры</b>\n"
                "Фиксируй вес и замеры (грудь, талия, бёдра), чтобы видеть прогресс не только "
                "в цифрах калорий.",
                "\nНачни с любого раздела в меню ниже 👇",
            ]

            # Подсветить историю, если уже что-то есть
            if weight or m:
                summary_lines.append("\n\n<b>Последние данные:</b>")
                if weight:
                    summary_lines.append(
                        f"\n⚖️ Вес: {weight.value} кг (от {weight.date})"
                    )
                if m:
                    parts = []
                    if m.chest:
                        parts.append(f"Грудь {m.chest} см")
                    if m.waist:
                        parts.append(f"Талия {m.waist} см")
                    if m.hips:
                        parts.append(f"Бёдра {m.hips} см")
                    if parts:
                        summary_lines.append(
                            f"\n📏 Замеры: {', '.join(parts)} ({m.date})"
                        )

            summary = "".join(summary_lines)

        else:
            # 🔹 Обычное поведение, когда что-то уже есть
            if not workouts:
                summary = f"Сегодня ({today_str}) тренировок пока нет 💭\n"
            else:
                summary = f"📅 {today_str}\n 🏋️ Тренировка:\n"
                totals: dict[str, int] = {}
                for w in workouts:
                    totals[w.exercise] = totals.get(w.exercise, 0) + w.count
                for ex, total in totals.items():
                    summary += f"• {ex}: {total}\n"

            if weight:
                summary += f"\n⚖️ Вес: {weight.value} кг (от {weight.date})"

            if m:
                parts = []
                if m.chest:
                    parts.append(f"Грудь {m.chest} см")
                if m.waist:
                    parts.append(f"Талия {m.waist} см")
                if m.hips:
                    parts.append(f"Бёдра {m.hips} см")
                if parts:
                    summary += f"\n📏 Замеры: {', '.join(parts)} ({m.date})"

        return f"{motivation}\n\n{summary}"
    finally:
        session.close()


def format_today_workouts_block(user_id: str, include_date: bool = True) -> str:
    today = date.today()
    today_str = today.strftime("%d.%m.%Y")
    workouts = get_workouts_for_day(user_id, today)

    if not workouts:
        return "💪 <b>Тренировки</b>\n—"

    text = ["💪 <b>Тренировки</b>"]
    total_calories = 0.0
    aggregates: dict[tuple[str, str | None], dict[str, float]] = {}

    for w in workouts:
        entry_calories = w.calories or calculate_workout_calories(
            user_id, w.exercise, w.variant, w.count
        )
        total_calories += entry_calories

        key = (w.exercise, w.variant)
        if key not in aggregates:
            aggregates[key] = {"count": 0, "calories": 0.0}

        aggregates[key]["count"] += w.count
        aggregates[key]["calories"] += entry_calories

    for (exercise, variant), data in aggregates.items():
        variant_text = f" ({variant})" if variant else ""
        formatted_count = format_count_with_unit(data["count"], variant)
        text.append(
            f"• {exercise}{variant_text}: {formatted_count} (~{data['calories']:.0f} ккал)"
        )

    text.append(f"🔥 Итого за день: ~{total_calories:.0f} ккал")

    return "\n".join(text)


def build_progress_bar(current: float, target: float, length: int = 10) -> str:
    """
    Строит индикатор прогресса по КБЖУ:
    - ⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ - Пустое значение (target <= 0 или current == 0)
    - 🟩🟩🟩🟩⬜⬜⬜⬜⬜⬜ - Обычный прогресс (0-101%)
    - 🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 - 101% (ровно)
    - 🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨 - 102-135%
    - 🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥 - >135%
    """
    if target <= 0 or current <= 0:
        # Пустое значение
        return "⬜" * length
    
    percent = (current / target) * 100
    
    if percent > 135:
        # >135% - все красные
        return "🟥" * length
    elif percent > 101:
        # 102-135% - все желтые
        return "🟨" * length
    else:
        # 0-101% - зеленые пропорционально + пустые
        filled_blocks = min(int(round((current / target) * length)), length)
        empty_blocks = max(length - filled_blocks, 0)
        return "🟩" * filled_blocks + "⬜" * empty_blocks


def build_water_progress_bar(current: float, target: float, length: int = 10) -> str:
    """
    Строит индикатор прогресса по воде (аналогично build_progress_bar, но с синими кубиками):
    - ⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ - Пустое значение (target <= 0 или current == 0)
    - 🟦🟦🟦🟦⬜⬜⬜⬜⬜⬜ - Обычный прогресс (0-101%)
    - 🟦🟦🟦🟦🟦🟦🟦🟦🟦🟦 - 101% (ровно)
    - 🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨 - 102-135%
    - 🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥 - >135%
    """
    if target <= 0 or current <= 0:
        # Пустое значение
        return "⬜" * length
    
    percent = (current / target) * 100
    
    if percent > 135:
        # >135% - все красные
        return "🟥" * length
    elif percent > 101:
        # 102-135% - все желтые
        return "🟨" * length
    else:
        # 0-101% - синие пропорционально + пустые
        filled_blocks = min(int(round((current / target) * length)), length)
        empty_blocks = max(length - filled_blocks, 0)
        return "🟦" * filled_blocks + "⬜" * empty_blocks


def format_progress_block(user_id: str) -> str:
    settings = get_kbju_settings(user_id)
    if not settings:
        return "🍱 Настрой цель по КБЖУ через «🎯 Цель / Норма КБЖУ», чтобы я показывал прогресс."

    totals = get_daily_meal_totals(user_id, date.today())
    burned_calories = get_daily_workout_calories(user_id, date.today())
    
    # Базовая норма калорий
    base_calories_target = settings.calories
    
    # Норма калорий с учетом сожженных (сожженные добавляются к норме)
    adjusted_calories_target = base_calories_target + burned_calories
    
    # Пропорционально увеличиваем норму БЖУ
    # Формула: новая норма = базовая норма * (новая норма калорий / базовая норма калорий)
    if base_calories_target > 0:
        ratio = adjusted_calories_target / base_calories_target
        adjusted_protein_target = settings.protein * ratio
        adjusted_fat_target = settings.fat * ratio
        adjusted_carbs_target = settings.carbs * ratio
    else:
        adjusted_protein_target = settings.protein
        adjusted_fat_target = settings.fat
        adjusted_carbs_target = settings.carbs
    
    def line(label: str, current: float, target: float, unit: str) -> str:
        percent = 0 if target <= 0 else round((current / target) * 100)
        bar = build_progress_bar(current, target)
        return f"{label}: {current:.0f}/{target:.0f} {unit} ({percent}%)\n{bar}"

    goal_label = get_kbju_goal_label(settings.goal)
    
    lines = ["🍱 <b>КБЖУ</b>"]
    
    # Пояснение о цели, норме и сожженных калориях
    explanation_lines = [
        f"🎯 <b>Цель:</b> {goal_label}",
        f"📊 <b>Базовая норма:</b> {base_calories_target:.0f} ккал, Б {settings.protein:.0f} г, Ж {settings.fat:.0f} г, У {settings.carbs:.0f} г"
    ]
    
    if burned_calories > 0:
        explanation_lines.append(
            f"🔥 <b>Сожжено на тренировках:</b> ~{burned_calories:.0f} ккал"
        )
        explanation_lines.append(
            f"✅ <b>Скорректированная норма:</b> {adjusted_calories_target:.0f} ккал "
            f"(базовая норма + сожженные калории)"
        )
    else:
        explanation_lines.append("💪 Сегодня тренировок не было")
    
    lines.append("\n" + "\n".join(explanation_lines) + "\n")
    
    lines.append(line("🔥 Калории", totals["calories"], adjusted_calories_target, "ккал"))
    lines.append(line("💪 Белки", totals["protein_g"], adjusted_protein_target, "г"))
    lines.append(line("🥑 Жиры", totals["fat_total_g"], adjusted_fat_target, "г"))
    lines.append(line("🍩 Углеводы", totals["carbohydrates_total_g"], adjusted_carbs_target, "г"))

    return "\n".join(lines)


def format_water_progress_block(user_id: str) -> str:
    """
    Форматирует блок прогресса воды для главного меню.
    """
    today = date.today()
    daily_total = get_daily_water_total(user_id, today)
    recommended = get_water_recommended(user_id)
    
    percent = 0 if recommended <= 0 else round((daily_total / recommended) * 100)
    bar = build_water_progress_bar(daily_total, recommended)
    
    return f"💧 <b>Вода</b>: {daily_total:.0f}/{recommended:.0f} мл ({percent}%)\n{bar}"


def add_weight(user_id, value, entry_date):
    session = SessionLocal()
    weight = Weight(
        user_id=str(user_id),
        value=str(value),
        date=entry_date
    )
    session.add(weight)
    session.commit()
    session.close()

def add_measurements(user_id, measurements: dict, entry_date):
    """
    measurements: словарь с ключами среди {'chest','waist','hips','biceps','thigh'}
    """
    session = SessionLocal()
    try:
        m = Measurement(
            user_id=str(user_id),
            chest=measurements.get("chest"),
            waist=measurements.get("waist"),
            hips=measurements.get("hips"),
            biceps=measurements.get("biceps"),
            thigh=measurements.get("thigh"),
            date=entry_date
        )
        session.add(m)
        session.commit()
    finally:
        session.close()


def get_workouts_for_day(user_id: str, target_date: date):
    session = SessionLocal()
    try:
        return (
            session.query(Workout)
            .filter(Workout.user_id == user_id, Workout.date == target_date)
            .order_by(Workout.id)
            .all()
        )
    finally:
        session.close()


def get_procedures_for_day(user_id: str, target_date: date):
    session = SessionLocal()
    try:
        return (
            session.query(Procedure)
            .filter(Procedure.user_id == user_id, Procedure.date == target_date)
            .order_by(Procedure.id)
            .all()
        )
    finally:
        session.close()


def get_month_procedure_days(user_id: str, year: int, month: int):
    first_day = date(year, month, 1)
    _, days_in_month = calendar.monthrange(year, month)
    last_day = date(year, month, days_in_month)

    session = SessionLocal()
    try:
        procedures = (
            session.query(Procedure.date)
            .filter(
                Procedure.user_id == user_id,
                Procedure.date >= first_day,
                Procedure.date <= last_day,
            )
            .all()
        )
        return {p.date.day for p in procedures}
    finally:
        session.close()


def save_procedure(user_id: str, name: str, entry_date: date, notes: str | None = None):
    session = SessionLocal()
    try:
        procedure = Procedure(
            user_id=str(user_id),
            name=name,
            date=entry_date,
            notes=notes,
        )
        session.add(procedure)
        session.commit()
        return procedure.id
    finally:
        session.close()


def get_water_recommended(user_id: str) -> float:
    """
    Рассчитывает рекомендуемую норму воды для пользователя.
    Использует формулу: 30-35 мл на 1 кг веса.
    Если вес не указан, возвращает среднее значение 2000 мл.
    """
    weight = get_last_weight_kg(user_id)
    if weight and weight > 0:
        # Используем 32.5 мл на кг (середина между 30 и 35)
        recommended = weight * 32.5
        # Округляем до ближайших 50 мл для удобства
        return round(recommended / 50) * 50
    else:
        # Если вес не указан, используем среднее значение
        return 2000


def get_daily_water_total(user_id: str, entry_date: date) -> float:
    session = SessionLocal()
    try:
        total = (
            session.query(func.sum(WaterEntry.amount))
            .filter(WaterEntry.user_id == user_id, WaterEntry.date == entry_date)
            .scalar()
        )
        return float(total) if total else 0.0
    finally:
        session.close()


def save_water_entry(user_id: str, amount: float, entry_date: date):
    session = SessionLocal()
    try:
        water_entry = WaterEntry(
            user_id=str(user_id),
            amount=amount,
            date=entry_date,
        )
        session.add(water_entry)
        session.commit()
        return water_entry.id
    finally:
        session.close()


def get_water_entries_for_day(user_id: str, target_date: date):
    session = SessionLocal()
    try:
        return (
            session.query(WaterEntry)
            .filter(WaterEntry.user_id == user_id, WaterEntry.date == target_date)
            .order_by(WaterEntry.timestamp)
            .all()
        )
    finally:
        session.close()


def get_month_workout_days(user_id: str, year: int, month: int):
    first_day = date(year, month, 1)
    _, days_in_month = calendar.monthrange(year, month)
    last_day = date(year, month, days_in_month)

    session = SessionLocal()
    try:
        workouts = (
            session.query(Workout.date)
            .filter(
                Workout.user_id == user_id,
                Workout.date >= first_day,
                Workout.date <= last_day,
            )
            .all()
        )
        return {w.date.day for w in workouts}
    finally:
        session.close()


def get_month_meal_days(user_id: str, year: int, month: int):
    first_day = date(year, month, 1)
    _, days_in_month = calendar.monthrange(year, month)
    last_day = date(year, month, days_in_month)

    session = SessionLocal()
    try:
        meals = (
            session.query(Meal.date)
            .filter(
                Meal.user_id == str(user_id),
                Meal.date >= first_day,
                Meal.date <= last_day,
            )
            .all()
        )
        return {m.date.day for m in meals}
    finally:
        session.close()


def build_calendar_keyboard(user_id: str, year: int, month: int) -> InlineKeyboardMarkup:
    workout_days = get_month_workout_days(user_id, year, month)
    keyboard: list[list[InlineKeyboardButton]] = []

    header = InlineKeyboardButton(text=f"{MONTH_NAMES[month]} {year}", callback_data="noop")
    keyboard.append([header])

    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(text=d, callback_data="noop") for d in week_days])

    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                marker = "💪" if day in workout_days else ""
                row.append(
                    InlineKeyboardButton(
                        text=f"{day}{marker}",
                        callback_data=f"cal_day:{year}-{month:02d}-{day:02d}",
                    )
                )
        keyboard.append(row)

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"cal_nav:{prev_year}-{prev_month:02d}"
            ),
            InlineKeyboardButton(text="Закрыть", callback_data="cal_close"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"cal_nav:{next_year}-{next_month:02d}"
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_kbju_calendar_keyboard(user_id: str, year: int, month: int) -> InlineKeyboardMarkup:
    meal_days = get_month_meal_days(user_id, year, month)
    keyboard: list[list[InlineKeyboardButton]] = []

    header = InlineKeyboardButton(text=f"{MONTH_NAMES[month]} {year}", callback_data="noop")
    keyboard.append([header])

    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(text=d, callback_data="noop") for d in week_days])

    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                marker = "🍱" if day in meal_days else ""
                row.append(
                    InlineKeyboardButton(
                        text=f"{day}{marker}",
                        callback_data=f"meal_cal_day:{year}-{month:02d}-{day:02d}",
                    )
                )
        keyboard.append(row)

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"meal_cal_nav:{prev_year}-{prev_month:02d}"
            ),
            InlineKeyboardButton(text="Закрыть", callback_data="cal_close"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"meal_cal_nav:{next_year}-{next_month:02d}"
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_procedures_calendar_keyboard(user_id: str, year: int, month: int) -> InlineKeyboardMarkup:
    procedure_days = get_month_procedure_days(user_id, year, month)
    keyboard: list[list[InlineKeyboardButton]] = []

    header = InlineKeyboardButton(text=f"{MONTH_NAMES[month]} {year}", callback_data="noop")
    keyboard.append([header])

    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(text=d, callback_data="noop") for d in week_days])

    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                marker = "💆" if day in procedure_days else ""
                row.append(
                    InlineKeyboardButton(
                        text=f"{day}{marker}",
                        callback_data=f"proc_cal_day:{year}-{month:02d}-{day:02d}",
                    )
                )
        keyboard.append(row)

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"proc_cal_nav:{prev_year}-{prev_month:02d}"
            ),
            InlineKeyboardButton(text="Закрыть", callback_data="cal_close"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"proc_cal_nav:{next_year}-{next_month:02d}"
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_procedures_calendar_keyboard(user_id: str, year: int, month: int) -> InlineKeyboardMarkup:
    procedure_days = get_month_procedure_days(user_id, year, month)
    keyboard: list[list[InlineKeyboardButton]] = []

    header = InlineKeyboardButton(text=f"{MONTH_NAMES[month]} {year}", callback_data="noop")
    keyboard.append([header])

    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(text=d, callback_data="noop") for d in week_days])

    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                marker = "💆" if day in procedure_days else ""
                row.append(
                    InlineKeyboardButton(
                        text=f"{day}{marker}",
                        callback_data=f"proc_cal_day:{year}-{month:02d}-{day:02d}",
                    )
                )
        keyboard.append(row)

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️", callback_data=f"proc_cal_nav:{prev_year}-{prev_month:02d}"
            ),
            InlineKeyboardButton(text="Закрыть", callback_data="cal_close"),
            InlineKeyboardButton(
                text="▶️", callback_data=f"proc_cal_nav:{next_year}-{next_month:02d}"
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_day_actions_keyboard(workouts: list[Workout], target_date: date) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for w in workouts:
        label = f"{w.exercise} ({w.count})"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {label}", callback_data=f"wrk_edit:{w.id}"
                ),
                InlineKeyboardButton(
                    text=f"🗑 {label}", callback_data=f"wrk_del:{w.id}"
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить тренировку",
                callback_data=f"wrk_add:{target_date.isoformat()}",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к календарю",
                callback_data=f"cal_back:{target_date.year}-{target_date.month:02d}",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_calendar(message: Message, user_id: str, year: int | None = None, month: int | None = None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    keyboard = build_calendar_keyboard(user_id, year, month)
    await message.answer(
        "📆 Выбери день, чтобы посмотреть, изменить или удалить тренировку:",
        reply_markup=keyboard,
    )


async def show_day_workouts(message: Message, user_id: str, target_date: date):
    workouts = get_workouts_for_day(user_id, target_date)
    if not workouts:
        await message.answer(
            f"{target_date.strftime('%d.%m.%Y')}: нет тренировок.",
            reply_markup=build_day_actions_keyboard([], target_date),
        )
        return

    text = [f"📅 {target_date.strftime('%d.%m.%Y')} — тренировки:"]
    total_calories = 0.0

    for w in workouts:
        variant_text = f" ({w.variant})" if w.variant else ""
        entry_calories = w.calories or calculate_workout_calories(user_id, w.exercise, w.variant, w.count)
        total_calories += entry_calories
        formatted_count = format_count_with_unit(w.count, w.variant)
        text.append(
            f"• {w.exercise}{variant_text}: {formatted_count} (~{entry_calories:.0f} ккал)"
        )

    text.append(f"\n🔥 Итого за день: ~{total_calories:.0f} ккал")

    await message.answer(
        "\n".join(text), reply_markup=build_day_actions_keyboard(workouts, target_date)
    )


async def show_kbju_calendar(
    message: Message, user_id: str, year: int | None = None, month: int | None = None
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    keyboard = build_kbju_calendar_keyboard(user_id, year, month)
    await message.answer(
        "📆 Выбери день, чтобы посмотреть результаты по КБЖУ:",
        reply_markup=keyboard,
    )


def build_kbju_day_actions_keyboard(target_date: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить",
                    callback_data=f"meal_cal_add:{target_date.isoformat()}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад к календарю",
                    callback_data=f"meal_cal_back:{target_date.year}-{target_date.month:02d}",
                )
            ],
        ]
    )


async def show_day_meals(message: Message, user_id: str, target_date: date):
    meals = get_meals_for_date(user_id, target_date)
    if not meals:
        await message.answer(
            f"{target_date.strftime('%d.%m.%Y')}: нет записей по КБЖУ.",
            reply_markup=build_kbju_day_actions_keyboard(target_date),
        )
        return

    daily_totals = get_daily_meal_totals(user_id, target_date)
    day_str = target_date.strftime("%d.%m.%Y")
    text = format_today_meals(meals, daily_totals, day_str)
    keyboard = build_meals_actions_keyboard(meals, target_date, include_back=True)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


def start_date_selection(bot, context: str):
    """Сохраняет контекст выбора даты (тренировка/вес/замеры)."""
    bot.date_selection_context = context
    bot.selected_date = date.today()
    bot.expecting_date_input = False


def get_date_prompt(context: str) -> str:
    prompts = {
        "training": "За какой день добавить тренировку?",
        "weight": "За какой день добавить вес?",
        "measurements": "За какой день добавить замеры?",
        "supplement_log": "Когда был приём добавки?",
    }
    return prompts.get(context, "За какую дату сделать запись?")


def get_other_day_prompt(context: str) -> str:
    prompts = {
        "training": "Выбери день тренировки или введи дату вручную:",
        "weight": "Выбери день для записи веса или введи дату вручную:",
        "measurements": "Выбери день для замеров или введи дату вручную:",
        "supplement_log": "Выбери день приёма или введи дату вручную:",
    }
    return prompts.get(context, "Выбери нужный день или введи дату вручную:")


async def proceed_after_date_selection(message: Message):
    context = getattr(message.bot, "date_selection_context", "training")
    selected_date = getattr(message.bot, "selected_date", date.today())
    date_text = selected_date.strftime("%d.%m.%Y")

    if context == "training":
        await message.answer(f"📅 Выбрана дата: {date_text}")
        message.bot.current_category = None
        message.bot.current_exercise = None
        await answer_with_menu(message, "Выбери категорию упражнений:", reply_markup=exercise_category_menu)
    elif context == "weight":
        message.bot.expecting_weight = True
        await message.answer(f"📅 Выбрана дата: {date_text}")
        await message.answer("Введи свой вес в килограммах (например: 72.5):")
    elif context == "measurements":
        message.bot.expecting_measurements = True
        await message.answer(f"📅 Выбрана дата: {date_text}")
        await message.answer(
            "Введи замеры в формате:\n\n"
            "грудь=100, талия=80, руки=35\n\n"
            "Можно указать только нужные параметры."
        )
    elif context == "supplement_log":
        user_id = str(message.from_user.id)
        if hasattr(message.bot, "supplement_log_choice"):
            supplement_name = message.bot.supplement_log_choice.get(user_id)
        else:
            supplement_name = None

        if not supplement_name:
            await message.answer("Не выбрана добавка для записи приёма.")
            return

        if not hasattr(message.bot, "supplement_log_date"):
            message.bot.supplement_log_date = {}
        message.bot.supplement_log_date[user_id] = selected_date
        message.bot.expecting_supplement_amount = True
        message.bot.expecting_supplement_amount_users = getattr(
            message.bot, "expecting_supplement_amount_users", set()
        )
        message.bot.expecting_supplement_amount_users.add(user_id)

        await message.answer(
            "Укажи количество добавки цифрой (например, 1 или 2.5).",
        )



# -------------------- keyboards --------------------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🏋️ Тренировка"), KeyboardButton(text="🍱 КБЖУ")],
        [KeyboardButton(text="⚖️ Вес / 📏 Замеры"), KeyboardButton(text="💊 Добавки")],
        [KeyboardButton(text="💆 Процедуры"), KeyboardButton(text="💧 Контроль воды")],
        [KeyboardButton(text="🤖 ИИ анализ деятельности")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🔄 Главное меню")],
    ],
    resize_keyboard=True
)

main_menu_button = KeyboardButton(text="🔄 Главное меню")

kbju_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить")],
        [KeyboardButton(text="📊 Дневной отчёт"), KeyboardButton(text="📆 Календарь КБЖУ")],
        [KeyboardButton(text="🎯 Цель / Норма КБЖУ")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

kbju_goal_view_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✏️ Редактировать")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)

kbju_intro_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Пройти быстрый тест КБЖУ")],
        [KeyboardButton(text="✏️ Ввести свою норму")],
        [KeyboardButton(text="➡️ Пока без цели")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

kbju_gender_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🙋‍♂️ Мужчина"), KeyboardButton(text="🙋‍♀️ Женщина")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

kbju_activity_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🪑 Мало движения")],
        [KeyboardButton(text="🚶 Умеренная активность")],
        [KeyboardButton(text="🏋️ Тренировки 3–5 раз/нед")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

kbju_goal_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📉 Похудение")],
        [KeyboardButton(text="⚖️ Поддержание")],
        [KeyboardButton(text="💪 Набор массы")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

kbju_add_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Ввести приём пищи (анализ ИИ)")],
        [KeyboardButton(text="📷 Анализ еды по фото")],
        [KeyboardButton(text="📋 Анализ этикетки"), KeyboardButton(text="📷 Скан штрих-кода")],
        [KeyboardButton(text="➕ Через CalorieNinjas")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)


kbju_after_meal_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="➕ Внести ещё приём"),
            KeyboardButton(text="✏️ Редактировать"),
        ],
        [KeyboardButton(text="📊 Дневной отчёт")],
        [
            KeyboardButton(text="⬅️ Назад"),
            main_menu_button,
        ],
    ],
    resize_keyboard=True,
)


training_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить тренировку")],
        [KeyboardButton(text="📆 Календарь тренировок")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)

settings_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🗑 Удалить аккаунт")],
        [KeyboardButton(text="💬 Поддержка")],
        [KeyboardButton(text="🔒 Политика конфиденциальности")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

delete_account_confirm_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да, удалить аккаунт")],
        [KeyboardButton(text="❌ Отмена")],
        [main_menu_button],
    ],
    resize_keyboard=True,
)

procedures_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить процедуру")],
        [KeyboardButton(text="📆 Календарь процедур")],
        [KeyboardButton(text="📊 Сегодня")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)

water_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить воду")],
        [KeyboardButton(text="📊 Статистика за сегодня")],
        [KeyboardButton(text="📆 История")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)

water_amount_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="250"), KeyboardButton(text="300"), KeyboardButton(text="330")],
        [KeyboardButton(text="500"), KeyboardButton(text="550"), KeyboardButton(text="600")],
        [KeyboardButton(text="650"), KeyboardButton(text="750"), KeyboardButton(text="1000")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True,
)

activity_analysis_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Анализ за день")],
        [KeyboardButton(text="📆 Анализ за неделю")],
        [KeyboardButton(text="📊 Анализ за месяц")],
        [KeyboardButton(text="📈 Анализ за все время")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)


def push_menu_stack(bot, reply_markup):
    if not isinstance(reply_markup, ReplyKeyboardMarkup):
        return

    stack = getattr(bot, "menu_stack", [])
    if not stack:
        stack = [main_menu]

    if stack and stack[-1] is not reply_markup:
        stack.append(reply_markup)

    bot.menu_stack = stack


async def answer_with_menu(message: Message, text: str, reply_markup=None, **kwargs):
    if reply_markup is not None:
        push_menu_stack(message.bot, reply_markup)
    await message.answer(text, reply_markup=reply_markup, **kwargs)

# Меню выбора даты тренировки
training_date_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Другой день")],
        [KeyboardButton(text="⬅️ Назад")]
    ],
    resize_keyboard=True
)

other_day_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Вчера"), KeyboardButton(text="📆 Позавчера")],
        [KeyboardButton(text="✏️ Ввести дату вручную")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True
)


activity_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💪Добавить упражнение")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True
)

exercise_category_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Со своим весом"), KeyboardButton(text="С утяжелителем")],
        [KeyboardButton(text="⬅️ Назад")],
        [main_menu_button],
    ],
    resize_keyboard=True
)

bodyweight_exercises = [
    "Подтягивания",
    "Отжимания",
    "Приседания",
    "Пресс",
    "Берпи",
    "Шаги (Ходьба)",
    "Пробежка",
    "Скакалка",
    "Становая тяга без утяжелителя",
    "Румынская тяга без утяжелителя",
    "Планка",
    "Йога",
    "Другое",
]

weighted_exercises = [
    "Приседания со штангой",
    "Жим штанги лёжа",
    "Становая тяга с утяжелителем",
    "Румынская тяга с утяжелителем",
    "Тяга штанги в наклоне",
    "Жим гантелей лёжа",
    "Жим гантелей сидя",
    "Подъёмы гантелей на бицепс",
    "Тяга верхнего блока",
    "Тяга нижнего блока",
    "Жим ногами",
    "Разведения гантелей",
    "Тяга горизонтального блока",
    "Сгибание ног в тренажёре",
    "Разгибание ног в тренажёре",
    "Гиперэкстензия с утяжелителем",
    "Другое",
]

bodyweight_exercise_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=ex)] for ex in bodyweight_exercises] + [[KeyboardButton(text="⬅️ Назад"), main_menu_button]],
    resize_keyboard=True,
)

weighted_exercise_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=ex)] for ex in weighted_exercises] + [[KeyboardButton(text="⬅️ Назад"), main_menu_button]],
    resize_keyboard=True,
)

count_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=str(n)) for n in range(1, 6)],
        [KeyboardButton(text=str(n)) for n in range(6, 11)],
        [KeyboardButton(text=str(n)) for n in range(11, 16)],
        [KeyboardButton(text=str(n)) for n in range(16, 21)],
        [KeyboardButton(text=str(n)) for n in [25, 30, 35, 40, 50]],
        [KeyboardButton(text="✏️ Ввести вручную")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button],
    ],
    resize_keyboard=True,
)


def format_count_with_unit(count: int | float, variant: str | None) -> str:
    if variant == "Минуты":
        unit = "мин"
    elif variant == "Количество шагов":
        unit = "шагов"
    elif variant == "Количество прыжков":
        unit = "раз"
    else:
        unit = "повторений"
    return f"{count} {unit}"


my_data_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⚖️ Вес")],
        [KeyboardButton(text="📏 Замеры")],
        [main_menu_button]
    ],
    resize_keyboard=True
)


my_workouts_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Сегодня")],
        [KeyboardButton(text="В другие дни")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button]
    ],
    resize_keyboard=True
)

today_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Удалить запись")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button]
    ],
    resize_keyboard=True
)

history_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Удалить запись из истории")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button]
    ],
    resize_keyboard=True
)

weight_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить вес")],
        [KeyboardButton(text="🗑 Удалить вес")],
        [KeyboardButton(text="📊 График")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button]
    ],
    resize_keyboard=True
)

weight_chart_period_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Неделя")],
        [KeyboardButton(text="📅 Месяц")],
        [KeyboardButton(text="📅 Полгода")],
        [KeyboardButton(text="📅 Все время")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)


measurements_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить замеры")],
        [KeyboardButton(text="🗑 Удалить замеры")],
        [KeyboardButton(text="⬅️ Назад"), main_menu_button]
    ],
    resize_keyboard=True
)



# -------------------- handlers --------------------
@dp.message(Command("start"))
async def start(message: Message):
    user_id = str(message.from_user.id)
    progress_text = format_progress_block(user_id)
    water_progress_text = format_water_progress_block(user_id)
    workouts_text = format_today_workouts_block(user_id, include_date=False)
    today_line = f"📅 <b>{date.today().strftime('%d.%m.%Y')}</b>"
    
    welcome = f"{today_line}\n\n{progress_text}\n\n{water_progress_text}\n\n{workouts_text}"
    await answer_with_menu(message, welcome, reply_markup=main_menu, parse_mode="HTML")


async def generate_activity_analysis(user_id: str, start_date: date, end_date: date, period_name: str):
    """Генерирует анализ активности за указанный период"""
    session = SessionLocal()
    try:
        # 🔹 Тренировки за период
        workouts = (
            session.query(Workout)
            .filter(
                Workout.user_id == user_id,
                Workout.date >= start_date,
                Workout.date <= end_date
            )
            .all()
        )

        workouts_by_ex = {}
        total_workout_calories = 0.0

        for w in workouts:
            key = (w.exercise, w.variant)
            entry = workouts_by_ex.setdefault(
                key, {"count": 0, "calories": 0.0}
            )
            entry["count"] += w.count
            cals = w.calories or calculate_workout_calories(
                user_id, w.exercise, w.variant, w.count
            )
            entry["calories"] += cals
            total_workout_calories += cals

        if workouts_by_ex:
            workout_lines = []
            for (exercise, variant), data in workouts_by_ex.items():
                formatted_count = format_count_with_unit(
                    data["count"], variant
                )
                variant_text = f" ({variant})" if variant else ""
                workout_lines.append(
                    f"- {exercise}{variant_text}: {formatted_count}, ~{data['calories']:.0f} ккал"
                )
            workout_summary = "\n".join(workout_lines)
        else:
            workout_summary = f"За {period_name.lower()} тренировки не записаны."

        # 🔹 КБЖУ за период
        meals = (
            session.query(Meal)
            .filter(
                Meal.user_id == user_id,
                Meal.date >= start_date,
                Meal.date <= end_date
            )
            .all()
        )

        total_calories = sum(m.calories or 0 for m in meals)
        total_protein = sum(m.protein or 0 for m in meals)
        total_fat = sum(m.fat or 0 for m in meals)
        total_carbs = sum(m.carbs or 0 for m in meals)

        meals_summary = (
            f"Калории: {total_calories:.0f} ккал, "
            f"Белки: {total_protein:.1f} г, "
            f"Жиры: {total_fat:.1f} г, "
            f"Углеводы: {total_carbs:.1f} г."
        )

        # 🔹 Цель / норма КБЖУ
        settings = get_kbju_settings(user_id)
        if settings:
            goal_label = get_kbju_goal_label(settings.goal)
            days_count = (end_date - start_date).days + 1
            kbju_goal_summary = (
                f"Цель: {goal_label}. "
                f"Норма за период: {settings.calories * days_count:.0f} ккал, "
                f"Б {settings.protein * days_count:.0f} г, "
                f"Ж {settings.fat * days_count:.0f} г, "
                f"У {settings.carbs * days_count:.0f} г."
            )
        else:
            kbju_goal_summary = "Цель по КБЖУ ещё не настроена."

        # 🔹 Вес и история веса
        weights = (
            session.query(Weight)
            .filter(
                Weight.user_id == user_id,
                Weight.date >= start_date,
                Weight.date <= end_date
            )
            .order_by(Weight.date.desc(), Weight.id.desc())
            .all()
        )

        if weights:
            current_weight = weights[0]
            if len(weights) > 1:
                first_weight = weights[-1]
                change = current_weight.value - first_weight.value
                change_text = f" ({'+' if change >= 0 else ''}{change:.1f} кг)"
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
            all_weights = (
                session.query(Weight)
                .filter(Weight.user_id == user_id)
                .order_by(Weight.date.desc(), Weight.id.desc())
                .limit(1)
                .all()
            )
            if all_weights:
                w = all_weights[0]
                weight_summary = f"Последний зафиксированный вес: {w.value} кг (от {w.date.strftime('%d.%m.%Y')}). За {period_name.lower()} новых измерений не было."
            else:
                weight_summary = "Записей по весу ещё нет."

    finally:
        session.close()

    # 🔹 Собираем summary для Gemini
    date_range_str = f"{start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"
    summary = f"""
Период: {period_name} ({date_range_str}).

Тренировки за период:
{workout_summary}
Всего ориентировочно израсходовано: ~{total_workout_calories:.0f} ккал.

Питание (КБЖУ) за период:
{meals_summary}

Норма / цель КБЖУ:
{kbju_goal_summary}

Вес:
{weight_summary}
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
В блоке "Общий прогресс и мотивация" дай конкретные рекомендации на основе данных: что улучшить, что работает хорошо, на что обратить внимание.
"""

    result = gemini_analyze(prompt)
    
    # Заменяем markdown звездочки на HTML-теги для жирного шрифта
    # Заменяем **текст** на <b>текст</b>
    result = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', result)
    # Заменяем оставшиеся одиночные звездочки в конце (если есть)
    result = re.sub(r'\*+$', '', result)
    
    return result


@dp.message(F.text == "🤖 ИИ анализ деятельности")
async def analyze_activity(message: Message):
    """Показывает меню выбора периода для анализа"""
    await answer_with_menu(
        message,
        "🤖 <b>ИИ анализ деятельности</b>\n\nВыбери период для анализа:",
        reply_markup=activity_analysis_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "📅 Анализ за день")
async def analyze_activity_day(message: Message):
    """Анализ активности за сегодня"""
    user_id = str(message.from_user.id)
    today = date.today()
    result = await generate_activity_analysis(user_id, today, today, "за день")
    await message.answer(result, parse_mode="HTML")


@dp.message(F.text == "📆 Анализ за неделю")
async def analyze_activity_week(message: Message):
    """Анализ активности за последние 7 дней"""
    user_id = str(message.from_user.id)
    today = date.today()
    week_ago = today - timedelta(days=6)
    result = await generate_activity_analysis(user_id, week_ago, today, "за неделю")
    await message.answer(result, parse_mode="HTML")


@dp.message(F.text == "📊 Анализ за месяц")
async def analyze_activity_month(message: Message):
    """Анализ активности за последние 30 дней"""
    user_id = str(message.from_user.id)
    today = date.today()
    month_ago = today - timedelta(days=29)
    result = await generate_activity_analysis(user_id, month_ago, today, "за месяц")
    await message.answer(result, parse_mode="HTML")


@dp.message(F.text == "📈 Анализ за все время")
async def analyze_activity_all_time(message: Message):
    """Анализ активности за все время"""
    user_id = str(message.from_user.id)
    session = SessionLocal()
    try:
        # Находим самую раннюю дату с данными
        first_workout = session.query(func.min(Workout.date)).filter(Workout.user_id == user_id).scalar()
        first_meal = session.query(func.min(Meal.date)).filter(Meal.user_id == user_id).scalar()
        first_weight = session.query(func.min(Weight.date)).filter(Weight.user_id == user_id).scalar()
        
        dates = [d for d in [first_workout, first_meal, first_weight] if d is not None]
        if dates:
            start_date = min(dates)
        else:
            start_date = date.today()
        
        today = date.today()
        result = await generate_activity_analysis(user_id, start_date, today, "за все время")
        await message.answer(result, parse_mode="HTML")
    finally:
        session.close()


@dp.message(F.text == "🏋️ Тренировка")
async def show_training_menu(message: Message):
    reset_user_state(message, keep_supplements=True)
    workouts_text = format_today_workouts_block(str(message.from_user.id))
    await answer_with_menu(
        message,
        f"Что делаем?\n\n{workouts_text}",
        reply_markup=training_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "➕ Добавить тренировку")
async def add_training_entry(message: Message):
    # Для тренировок всегда используем сегодняшнюю дату
    # Другой день можно выбрать только через календарь
    message.bot.selected_date = date.today()
    await proceed_after_date_selection(message)

@dp.message(F.text == "Со своим весом")
async def choose_bodyweight_category(message: Message):
    message.bot.current_category = "bodyweight"
    await answer_with_menu(message, "Выбери упражнение:", reply_markup=bodyweight_exercise_menu)


@dp.message(F.text == "С утяжелителем")
async def choose_weighted_category(message: Message):
    message.bot.current_category = "weighted"
    await answer_with_menu(message, "Выбери упражнение:", reply_markup=weighted_exercise_menu)

@dp.message(F.text == "📅 Сегодня")
async def add_training_today(message: Message):
    message.bot.selected_date = date.today()
    await proceed_after_date_selection(message)

@dp.message(F.text == "📆 Другой день")
async def add_training_other_day(message: Message):
    context = getattr(message.bot, "date_selection_context", "training")
    await answer_with_menu(message, get_other_day_prompt(context), reply_markup=other_day_menu)

@dp.message(F.text == "📅 Вчера")
async def training_yesterday(message: Message):
    message.bot.selected_date = date.today() - timedelta(days=1)
    await proceed_after_date_selection(message)


@dp.message(F.text == "📆 Позавчера")
async def training_day_before_yesterday(message: Message):
    message.bot.selected_date = date.today() - timedelta(days=2)
    await proceed_after_date_selection(message)


@dp.message(F.text == "✏️ Ввести дату вручную")
async def enter_custom_date(message: Message):
    message.bot.expecting_date_input = True
    await message.answer("Введи дату в формате ДД.ММ.ГГГГ:")

@dp.message(F.text.regexp(r"^\d{2}\.\d{2}\.\d{4}$"), lambda m: getattr(m.bot, "expecting_date_input", False))
async def handle_custom_date(message: Message):
    try:
        entered_date = datetime.strptime(message.text, "%d.%m.%Y").date()
        message.bot.selected_date = entered_date
        message.bot.expecting_date_input = False
        await proceed_after_date_selection(message)
    except ValueError:
        await message.answer("⚠️ Неверный формат. Попробуй так: 31.10.2025")


@dp.message(lambda m: m.text in bodyweight_exercises + weighted_exercises)
async def choose_exercise(message: Message):
    category = getattr(message.bot, "current_category", None)
    if message.text in bodyweight_exercises:
        category = "bodyweight"
    elif message.text in weighted_exercises:
        category = "weighted"

    message.bot.current_category = category
    message.bot.current_exercise = message.text

    # обрабатываем "Другое"
    if message.text == "Другое":
        message.bot.current_variant = "С утяжелителем" if category == "weighted" else "Со своим весом"
        await message.answer("Введи название упражнения:")
        message.bot.expecting_custom_exercise = True
        return

    # особые случаи (оставляем как есть)
    if message.text in {"Шаги", "Шаги (Ходьба)"}:
        message.bot.current_variant = "Количество шагов"
        await message.answer("Сколько шагов сделал? Введи число:")
        return
    elif message.text == "Пробежка":
        message.bot.current_variant = "Минуты"
        await message.answer("Сколько минут пробежал? Введи число:")
        return
    elif message.text == "Скакалка":
        message.bot.current_variant = "Количество прыжков"
        await message.answer("Сколько раз прыгал на скакалке? Введи число:")
        return
    elif message.text == "Йога":
        message.bot.current_variant = "Минуты"
        await message.answer("Сколько минут занимался йогой? Введи число:")
        return
    elif message.text == "Планка":
        message.bot.current_variant = "Минуты"
        await message.answer("Сколько минут стоял в планке? Введи число:")
        return

    # обычные упражнения
    if category == "weighted":
        message.bot.current_variant = "С утяжелителем"
    else:
        message.bot.current_variant = "Со своим весом"
    await answer_with_menu(message, "Выбери количество повторений:", reply_markup=count_menu)

@dp.message(F.text == "✏️ Ввести вручную")
async def enter_manual_count(message: Message):
    await message.answer("Введи количество повторений числом:")


# пользователь ввёл название упражнения в "Другое"
@dp.message(F.text, lambda m: getattr(m.bot, "expecting_custom_exercise", False))
async def handle_custom_exercise(message: Message):
    message.bot.current_exercise = message.text
    category = getattr(message.bot, "current_category", None)
    message.bot.current_variant = "С утяжелителем" if category == "weighted" else "Со своим весом"
    message.bot.expecting_custom_exercise = False
    await message.answer("Отлично! Теперь введи количество раз:")





@dp.message(F.text == "Удалить запись")
async def delete_entry_start(message: Message):
    if not hasattr(message.bot, "todays_workouts") or not message.bot.todays_workouts:
        await answer_with_menu(message, "Сегодня ещё нет записей для удаления.", reply_markup=my_workouts_menu)
        return

    message.bot.expecting_delete = True
    await message.answer("Введи номер записи, которую хочешь удалить:")


@dp.message(lambda m: getattr(m.bot, "expecting_water_amount", False))
async def process_water_amount(message: Message):
    user_id = str(message.from_user.id)
    text = message.text.strip()
    
    # Проверяем, не является ли это кнопкой меню
    if text in ["⬅️ Назад", "🔄 Главное меню", "🏠 Главное меню", "📊 Статистика за сегодня", "📆 История", "➕ Добавить воду"]:
        message.bot.expecting_water_amount = False
        if text == "⬅️ Назад":
            # Возвращаемся в меню воды
            await water(message)
        return
    
    try:
        amount = float(text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await answer_with_menu(
            message,
            "Пожалуйста, введи число (количество миллилитров) или выбери из предложенных.",
            reply_markup=water_amount_menu,
        )
        return
    
    entry_date = date.today()
    save_water_entry(user_id, amount, entry_date)
    
    message.bot.expecting_water_amount = False
    
    daily_total = get_daily_water_total(user_id, entry_date)
    
    await answer_with_menu(
        message,
        f"✅ Добавил {amount:.0f} мл воды\n\n"
        f"💧 Всего за сегодня: {daily_total:.0f} мл",
        reply_markup=water_menu,
    )


@dp.message(
    F.text.regexp(r"^\d+$"),
    # не срабатываем, если ждём ввод веса
    lambda m: not getattr(m.bot, "expecting_weight", False),
    # не срабатываем, если идёт тест КБЖУ
    lambda m: getattr(m.bot, "kbju_test_step", None) is None,
    lambda m: not getattr(m.bot, "expecting_supplement_history_amount", False),
    # не срабатываем, если ожидается ввод веса для этикетки
    lambda m: not getattr(m.bot, "expecting_label_weight_input", False),
    # не срабатываем, если ожидается ввод количества воды
    lambda m: not getattr(m.bot, "expecting_water_amount", False),
)
async def process_number(message: Message):
    # Проверяем, не ожидается ли ввод веса для этикетки
    if getattr(message.bot, "expecting_label_weight_input", False):
        return
    
    # Проверяем, не ожидается ли ввод количества воды
    if getattr(message.bot, "expecting_water_amount", False):
        return

    # Если пользователь вводит число в процессе отметки добавки, перенаправляем
    # в соответствующий обработчик и не создаём тренировочную запись.
    if has_pending_supplement_amount(message):
        await set_supplement_amount(message)
        return

    user_id = str(message.from_user.id)
    number = int(message.text)


    if getattr(message.bot, "expecting_edit_workout_id", False):
        workout_id = message.bot.expecting_edit_workout_id
        session = SessionLocal()
        try:
            workout = session.query(Workout).filter_by(id=workout_id, user_id=user_id).first()
            if not workout:
                await message.answer("Не нашёл тренировку для изменения.")
            else:
                workout.count = number
                workout.calories = calculate_workout_calories(
                    user_id, workout.exercise, workout.variant, number
                )
                session.commit()
                target_date = workout.date
                await message.answer(
                    f"✏️ Обновил: {workout.exercise} — теперь {number} (от {target_date.strftime('%d.%m.%Y')})"
                )
                await show_day_workouts(message, user_id, target_date)
        finally:
            session.close()

        message.bot.expecting_edit_workout_id = False
        return


    # --- режим удаления веса ---
    if getattr(message.bot, "expecting_weight_delete", False):
        index = number - 1
        if 0 <= index < len(message.bot.user_weights):
            entry = message.bot.user_weights[index]

            session = SessionLocal()
            weight = session.query(Weight).filter_by(
                user_id=user_id,
                value=entry.value,
                date=entry.date
            ).first()

            if weight:
                session.delete(weight)
                session.commit()
                session.close()
                message.bot.user_weights.pop(index)
                await message.answer(f"✅ Удалил запись: {entry.date.strftime('%d.%m.%Y')} — {entry.value} кг")
            else:
                session.close()
                await message.answer("❌ Не нашёл такую запись в базе.")

        else:
            await message.answer("⚠️ Нет такой записи.")
        message.bot.expecting_weight_delete = False
        return

    # --- режим удаления замеров ---
    if getattr(message.bot, "expecting_measurement_delete", False):
        index = number - 1
        if 0 <= index < len(message.bot.user_measurements):
            entry = message.bot.user_measurements[index]

            session = SessionLocal()
            m = session.query(Measurement).filter_by(
                user_id=user_id,
                date=entry.date
            ).first()

            if m:
                session.delete(m)
                session.commit()
                session.close()
                message.bot.user_measurements.pop(index)
                await message.answer(f"✅ Удалил замеры от {entry.date.strftime('%d.%m.%Y')}")
            else:
                session.close()
                await message.answer("❌ Не нашёл такие замеры в базе.")

        else:
            await message.answer("⚠️ Нет такой записи.")
        message.bot.expecting_measurement_delete = False
        return


    # --- режим удаления сегодняшних тренировок ---
    if getattr(message.bot, "expecting_delete", False):
        index = number - 1

        if 0 <= index < len(message.bot.todays_workouts):
            entry = message.bot.todays_workouts[index]

            session = SessionLocal()
            # Удаляем запись из базы, совпадающую по всем полям
            workout = session.query(Workout).filter_by(
                user_id=user_id,
                exercise=entry.exercise,
                variant=entry.variant,
                count=entry.count,
                date=entry.date
            ).first()

            if workout:
                session.delete(workout)
                session.commit()
                session.close()
                message.bot.todays_workouts.pop(index)
                await message.answer(f"Удалил: {entry.exercise} ({entry.variant}) - {entry.count}")
            else:
                session.close()
                await message.answer("Не нашёл такую запись в базе.")

        else:
            await message.answer("Нет такой записи.")

        message.bot.expecting_delete = False
        return


    # --- режим удаления из всей истории ---
    if getattr(message.bot, "expecting_history_delete", False):
        index = number - 1
        if 0 <= index < len(message.bot.history_workouts):
            entry = message.bot.history_workouts[index]

            session = SessionLocal()
            workout = session.query(Workout).filter_by(
                user_id=user_id,
                exercise=entry.exercise,
                variant=entry.variant,
                count=entry.count,
                date=entry.date
            ).first()

            if workout:
                session.delete(workout)
                session.commit()
                message.bot.history_workouts.pop(index)
                await message.answer(
                    f"Удалил из истории: {entry.date} — {entry.exercise} ({entry.variant}) - {entry.count}"
            )
            else:
                await message.answer("Не нашёл такую запись в базе.")

            session.close()
        else:
            await message.answer("Нет такой записи.")

        message.bot.expecting_history_delete = False
        return




   

    # --- режим добавления подхода ---
    # Проверяем, не ожидается ли ввод количества воды
    if getattr(message.bot, "expecting_water_amount", False):
        return
    
    if not hasattr(message.bot, "current_exercise"):
        await message.answer("Сначала выбери упражнение из меню.")
        return

    count = number
    exercise = message.bot.current_exercise
    variant = message.bot.current_variant

    session = SessionLocal()
    try:
        selected_date = getattr(message.bot, "selected_date", date.today())
        calories = calculate_workout_calories(user_id, exercise, variant, count)

        new_workout = Workout(
            user_id=user_id,
            exercise=exercise,
            variant=variant,
            count=count,
            date=selected_date,
            calories=calories,
        )

        session.add(new_workout)
        session.commit()

        # Считаем общее количество по выбранной дате
        total_for_date = (
            session.query(Workout)
            .filter_by(user_id=user_id, exercise=exercise, date=selected_date)
            .with_entities(func.sum(Workout.count))
            .scalar()
        ) or 0
    finally:
        session.close()

    date_label = (
        "сегодня" if selected_date == date.today() else selected_date.strftime("%d.%m.%Y")
    )

    await message.answer(
        f"Записал! 👍\nВсего {exercise} за {date_label}: {format_count_with_unit(total_for_date, variant)}"
    )
    await message.answer("Если хочешь — введи ещё количество или вернись через '⬅️ Назад'")



@dp.message(F.text == "⚖️ Вес")
async def my_weight(message: Message):
    user_id = str(message.from_user.id)
    session = SessionLocal()

    weights = (
        session.query(Weight)
        .filter_by(user_id=user_id)
        .order_by(Weight.date.desc())
        .all()
    )
    session.close()

    if not weights:
        await answer_with_menu(message, "⚖️ У тебя пока нет записей веса.", reply_markup=weight_menu)
        return

    text = "📊 История твоего веса:\n\n"
    for i, w in enumerate(weights, 1):
        text += f"{i}. {w.date.strftime('%d.%m.%Y')} — {w.value} кг\n"

    await answer_with_menu(message, text, reply_markup=weight_menu)


@dp.message(F.text == "➕ Добавить вес")
async def add_weight_start(message: Message):
    start_date_selection(message.bot, "weight")
    await answer_with_menu(message, get_date_prompt("weight"), reply_markup=training_date_menu)


def get_weights_for_period(user_id: str, period: str) -> list:
    """Получает веса пользователя за указанный период."""
    session = SessionLocal()
    try:
        today = date.today()
        
        if period == "week":
            start_date = today - timedelta(days=7)
        elif period == "month":
            start_date = today - timedelta(days=30)
        elif period == "half_year":
            start_date = today - timedelta(days=180)
        else:  # all_time
            start_date = date(2000, 1, 1)  # Очень старая дата
        
        weights = (
            session.query(Weight)
            .filter_by(user_id=user_id)
            .filter(Weight.date >= start_date)
            .order_by(Weight.date.asc())
            .all()
        )
        
        result = []
        for w in weights:
            try:
                value = float(str(w.value).replace(",", "."))
                result.append({"date": w.date, "value": value})
            except (ValueError, TypeError):
                continue
        
        return result
    finally:
        session.close()


def create_weight_chart(weights: list, period: str) -> BytesIO | None:
    """Создает график веса и возвращает его как BytesIO."""
    if not weights:
        return None
    
    if not MATPLOTLIB_AVAILABLE:
        return None
    
    try:
        # Подготовка данных
        dates = [w["date"] for w in weights]
        values = [w["value"] for w in weights]
        
        # Создание графика
        plt.figure(figsize=(12, 6))
        plt.plot(dates, values, marker='o', linestyle='-', linewidth=2, markersize=6, color='#2E86AB')
        plt.fill_between(dates, values, alpha=0.3, color='#2E86AB')
        
        # Настройка осей
        plt.xlabel('Дата', fontsize=12, fontweight='bold')
        plt.ylabel('Вес (кг)', fontsize=12, fontweight='bold')
        
        # Название периода
        period_names = {
            "week": "За неделю",
            "month": "За месяц",
            "half_year": "За полгода",
            "all_time": "За все время"
        }
        plt.title(f'📊 График веса - {period_names.get(period, "За все время")}', fontsize=14, fontweight='bold', pad=20)
        
        # Настройка формата дат на оси X
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates) // 10)))
        plt.xticks(rotation=45, ha='right')
        
        # Сетка
        plt.grid(True, alpha=0.3, linestyle='--')
        
        # Минимальные и максимальные значения с небольшим отступом
        if values:
            min_val = min(values)
            max_val = max(values)
            range_val = max_val - min_val
            plt.ylim(max(0, min_val - range_val * 0.1), max_val + range_val * 0.1)
        
        # Добавляем значения на точки
        for i, (d, v) in enumerate(zip(dates, values)):
            if i == 0 or i == len(dates) - 1 or i % max(1, len(dates) // 5) == 0:
                plt.annotate(f'{v:.1f}', (d, v), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9)
        
        plt.tight_layout()
        
        # Сохранение в BytesIO
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
    except Exception as e:
        print(f"❌ Ошибка при создании графика: {repr(e)}")
        return None


@dp.message(F.text == "📊 График")
async def show_weight_chart_menu(message: Message):
    user_id = str(message.from_user.id)
    session = SessionLocal()
    try:
        weights_count = session.query(Weight).filter_by(user_id=user_id).count()
        session.close()
        
        if weights_count == 0:
            await answer_with_menu(message, "⚖️ У тебя пока нет записей веса для графика.", reply_markup=weight_menu)
            return
        
        # Сохраняем текущее меню в стек
        push_menu_stack(message.bot, weight_menu)
        
        await answer_with_menu(
            message,
            "📊 Выбери период для графика веса:",
            reply_markup=weight_chart_period_menu
        )
    except Exception as e:
        session.close()
        print(f"❌ Ошибка при проверке весов: {repr(e)}")
        await answer_with_menu(message, "Произошла ошибка. Попробуйте позже.", reply_markup=weight_menu)


@dp.message(F.text == "📅 Неделя")
async def show_weight_chart_week(message: Message):
    await show_weight_chart(message, "week")


@dp.message(F.text == "📅 Месяц")
async def show_weight_chart_month(message: Message):
    await show_weight_chart(message, "month")


@dp.message(F.text == "📅 Полгода")
async def show_weight_chart_half_year(message: Message):
    await show_weight_chart(message, "half_year")


@dp.message(F.text == "📅 Все время")
async def show_weight_chart_all_time(message: Message):
    await show_weight_chart(message, "all_time")


async def show_weight_chart(message: Message, period: str):
    user_id = str(message.from_user.id)
    
    try:
        weights = get_weights_for_period(user_id, period)
        
        if not weights:
            period_names = {
                "week": "неделю",
                "month": "месяц",
                "half_year": "полгода",
                "all_time": "все время"
            }
            await answer_with_menu(
                message,
                f"⚖️ Нет записей веса за {period_names.get(period, 'этот период')}.",
                reply_markup=weight_menu
            )
            return
        
        # Создаем график
        if not MATPLOTLIB_AVAILABLE:
            await answer_with_menu(
                message,
                "📊 График веса временно недоступен.\n\n"
                "Для работы графиков необходимо установить библиотеку matplotlib.\n"
                "Пока что вы можете просмотреть историю веса в текстовом виде.",
                reply_markup=weight_menu
            )
            return
        
        chart_buffer = create_weight_chart(weights, period)
        
        if chart_buffer:
            # Отправляем график
            chart_buffer.name = "weight_chart.png"
            await message.answer_photo(
                photo=chart_buffer,
                caption=f"📊 График веса ({len(weights)} записей)",
                reply_markup=weight_menu
            )
            chart_buffer.close()
        else:
            await answer_with_menu(
                message,
                "Не удалось создать график. Попробуйте позже.",
                reply_markup=weight_menu
            )
            
    except Exception as e:
        print(f"❌ Ошибка при создании графика веса: {repr(e)}")
        import traceback
        traceback.print_exc()
        await answer_with_menu(message, "Произошла ошибка при создании графика. Попробуйте позже.", reply_markup=weight_menu)


@dp.message(F.text == "🗑 Удалить вес")
async def delete_weight_start(message: Message):
    user_id = str(message.from_user.id)
    session = SessionLocal()
    weights = (
        session.query(Weight)
        .filter_by(user_id=user_id)
        .order_by(Weight.date.desc())
        .all()
    )
    session.close()

    if not weights:
        await answer_with_menu(message, "⚖️ У тебя нет записей веса для удаления.", reply_markup=weight_menu)
        return

    # сохраняем в оперативную память
    message.bot.expecting_weight_delete = True
    message.bot.user_weights = weights

    text = "Выбери номер веса для удаления:\n\n"
    for i, w in enumerate(weights, 1):
        text += f"{i}. {w.date.strftime('%d.%m.%Y')} — {w.value} кг\n"

    await message.answer(text)


@dp.message(lambda m: getattr(m.bot, "expecting_label_weight_input", False))
async def kbju_label_weight_input(message: Message):
    """Обработчик ввода веса пользователем для этикетки"""
    user_id = str(message.from_user.id)
    
    if not hasattr(message.bot, "label_kbju_cache") or user_id not in message.bot.label_kbju_cache:
        await message.answer("Что-то пошло не так. Начни заново с отправки фото этикетки или штрих-кода.")
        message.bot.expecting_label_weight_input = False
        return

    try:
        weight = float(message.text.replace(",", "."))
        if weight <= 0:
            await message.answer("Вес должен быть больше нуля. Введи правильное число (например: 50 или 100):")
            return
    except ValueError:
        await message.answer("Пожалуйста, введи число (например: 50 или 100):")
        return

    cache = message.bot.label_kbju_cache[user_id]
    entry_date = cache.get("entry_date", date.today())

    # Пересчитываем пропорционально указанному весу
    multiplier = weight / 100.0
    totals_for_db = {
        "calories": cache["kcal_100g"] * multiplier,
        "protein_g": cache["protein_100g"] * multiplier,
        "fat_total_g": cache["fat_100g"] * multiplier,
        "carbohydrates_total_g": cache["carbs_100g"] * multiplier,
        "products": [],
    }

    product_name = cache.get("product_name", "Продукт")
    source = cache.get("source", "label")  # По умолчанию этикетка

    # Формируем заголовок в зависимости от источника
    if source == "barcode":
        barcode = cache.get("barcode", "")
        lines = [f"📷 Сканирование штрих-кода: {product_name}\n"]
        raw_query = f"[Штрих-код: {barcode}]"
    else:
        lines = [f"📋 Анализ этикетки: {product_name}\n"]
        raw_query = f"[Этикетка: {product_name}]"
    
    lines.append(f"📦 Вес: {weight:.0f} г\n")
    lines.append("КБЖУ:")
    lines.append(
        f"🔥 Калории: {totals_for_db['calories']:.0f} ккал\n"
        f"💪 Белки: {totals_for_db['protein_g']:.1f} г\n"
        f"🥑 Жиры: {totals_for_db['fat_total_g']:.1f} г\n"
        f"🍩 Углеводы: {totals_for_db['carbohydrates_total_g']:.1f} г"
    )

    api_details = f"{product_name} ({weight:.0f} г) — {totals_for_db['calories']:.0f} ккал (Б {totals_for_db['protein_g']:.1f} / Ж {totals_for_db['fat_total_g']:.1f} / У {totals_for_db['carbohydrates_total_g']:.1f})"

    save_meal_entry(
        user_id=user_id,
        raw_query=raw_query,
        totals=totals_for_db,
        entry_date=entry_date,
        api_details=api_details,
    )

    daily_totals = get_daily_meal_totals(user_id, entry_date)

    lines.append("\nСУММА ЗА СЕГОДНЯ:")
    lines.append(
        f"🔥 Калории: {daily_totals['calories']:.0f} ккал\n"
        f"💪 Белки: {daily_totals['protein_g']:.1f} г\n"
        f"🥑 Жиры: {daily_totals['fat_total_g']:.1f} г\n"
        f"🍩 Углеводы: {daily_totals['carbohydrates_total_g']:.1f} г"
    )

    message.bot.expecting_label_weight_input = False
    del message.bot.label_kbju_cache[user_id]
    if hasattr(message.bot, "meal_entry_dates"):
        message.bot.meal_entry_dates.pop(user_id, None)

    await answer_with_menu(
        message,
        "\n".join(lines),
        reply_markup=kbju_after_meal_menu,
    )


@dp.message(F.text.regexp(r"^\d+([.,]\d+)?$"))
async def process_weight_or_number(message: Message):
    user_id = str(message.from_user.id)

    # 1️⃣ Сначала проверяем, не идёт ли сейчас тест КБЖУ
    step = getattr(message.bot, "kbju_test_step", None)
    # В тесте через числа мы обрабатываем шаги: возраст, рост и вес
    if step in {"age", "height", "weight"}:
        await handle_kbju_test_number(message, step)
        return

    # 1.5️⃣ Если ожидается ввод веса для этикетки - пропускаем (обработается в kbju_label_weight_input)
    if getattr(message.bot, "expecting_label_weight_input", False):
        return
    
    # 1.6️⃣ Если ожидается ввод количества воды - пропускаем (обработается в process_water_amount)
    if getattr(message.bot, "expecting_water_amount", False):
        return

    # 2️⃣ Если сейчас ждём ввод веса
    if getattr(message.bot, "expecting_weight", False):
        weight_value = float(message.text.replace(",", "."))  # поддержка 72,5
        selected_date = getattr(message.bot, "selected_date", date.today())
        add_weight(user_id, weight_value, selected_date)
        message.bot.expecting_weight = False
        await message.answer(
            f"✅ Записал вес {weight_value} кг за {selected_date.strftime('%d.%m.%Y')}",
            reply_markup=weight_menu,
        )
        return

    # 3️⃣ Во всех остальных случаях — обычная логика чисел (подходы/повторы и т.п.)
    await process_number(message)




@dp.message(F.text == "📏 Замеры")
async def my_measurements(message: Message):
    user_id = str(message.from_user.id)
    session = SessionLocal()

    measurements = (
        session.query(Measurement)
        .filter_by(user_id=user_id)
        .order_by(Measurement.date.desc())
        .all()
    )
    session.close()

    if not measurements:
        await answer_with_menu(message, "📐 У тебя пока нет замеров.", reply_markup=measurements_menu)
        return

    text = "📊 История замеров:\n\n"
    for i, m in enumerate(measurements, 1):
        parts = []
        if m.chest:
            parts.append(f"Грудь: {m.chest} см")
        if m.waist:
            parts.append(f"Талия: {m.waist} см")
        if m.hips:
            parts.append(f"Бёдра: {m.hips} см")
        if m.biceps:
            parts.append(f"Бицепс: {m.biceps} см")
        if m.thigh:
            parts.append(f"Бедро: {m.thigh} см")

        text += f"{i}. {m.date.strftime('%d.%m.%Y')} — {', '.join(parts)}\n"

    await answer_with_menu(message, text, reply_markup=measurements_menu)


@dp.message(F.text == "➕ Добавить замеры")
async def add_measurements_start(message: Message):
    start_date_selection(message.bot, "measurements")
    await answer_with_menu(message, get_date_prompt("measurements"), reply_markup=training_date_menu)

@dp.message(F.text == "🗑 Удалить замеры")
async def delete_measurements_start(message: Message):
    user_id = str(message.from_user.id)
    session = SessionLocal()
    measurements = (
        session.query(Measurement)
        .filter_by(user_id=user_id)
        .order_by(Measurement.date.desc())
        .all()
    )
    session.close()

    if not measurements:
        await answer_with_menu(message, "📏 У тебя нет замеров для удаления.", reply_markup=measurements_menu)
        return

    message.bot.expecting_measurement_delete = True
    message.bot.user_measurements = measurements

    text = "Выбери номер замеров для удаления:\n\n"
    for i, m in enumerate(measurements, 1):
        parts = []
        if m.chest:
            parts.append(f"Грудь: {m.chest}")
        if m.waist:
            parts.append(f"Талия: {m.waist}")
        if m.hips:
            parts.append(f"Бёдра: {m.hips}")
        if m.biceps:
            parts.append(f"Бицепс: {m.biceps}")
        if m.thigh:
            parts.append(f"Бедро: {m.thigh}")

        summary = ", ".join(parts) if parts else "нет данных"
        text += f"{i}. {m.date.strftime('%d.%m.%Y')} — {summary}\n"

    await message.answer(text)


@dp.message(F.text, lambda m: getattr(m.bot, "expecting_measurements", False))
async def process_measurements(message: Message):
    user_id = str(message.from_user.id)
    raw = message.text

    try:
        # разбиваем на части: "грудь=100, талия=80, руки=35"
        parts = [p.strip() for p in raw.replace(",", " ").split()]
        if not parts:
            raise ValueError

        # нормализация и маппинг ключей к полям модели
        key_map = {
            "грудь": "chest", "груд": "chest",
            "талия": "waist", "талияю": "waist",
            "бёдра": "hips", "бедра": "hips", "бёдро": "thigh", "бедро": "thigh",
            "руки": "biceps", "бицепс": "biceps", "бицепсы": "biceps",
            "бедро": "thigh"
        }

        measurements_mapped = {}
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                k = k.strip().lower()
                v = v.strip()
                if not v:
                    continue
                # заменить запятую на точку для чисел
                val = float(v.replace(",", "."))
                field = key_map.get(k, None)
                if field:
                    measurements_mapped[field] = val
                else:
                    # если ключ не в маппинге — пробуем использовать как есть (безопасно)
                    measurements_mapped[k] = val

        if not measurements_mapped:
            raise ValueError
    except Exception:
        await message.answer("⚠️ Неверный формат. Попробуй так: грудь=100, талия=80, руки=35")
        return

    # сохраняем в базу (функция ниже принимает маппинг полей модели)
    try:
        selected_date = getattr(message.bot, "selected_date", date.today())
        add_measurements(user_id, measurements_mapped, selected_date)
    except Exception as e:
        # на случай неожиданной ошибки — лог в консоль и сообщение пользователю
        print("Error saving measurements:", e)
        await message.answer("⚠️ Ошибка при сохранении. Повтори попытку позже.")
        message.bot.expecting_measurements = False
        return

    message.bot.expecting_measurements = False
    await answer_with_menu(
        "✅ Замеры сохранены: {data} ({date})".format(
            data=measurements_mapped,
            date=getattr(message.bot, "selected_date", date.today()).strftime("%d.%m.%Y")
        ),
        reply_markup=measurements_menu
    )



@dp.message(F.text == "📊 История событий")
async def my_data(message: Message):
    await answer_with_menu(message, "Выбери, что посмотреть:", reply_markup=my_data_menu)


def reset_user_state(message: Message, *, keep_supplements: bool = False):
    user_id = str(message.from_user.id)

    for attr in [
        "expecting_measurements",
        "expecting_weight",
        "expecting_delete",
        "expecting_history_delete",
        "expecting_weight_delete",
        "expecting_measurement_delete",
        "expecting_custom_exercise",
        "expecting_date_input",
        "expecting_edit_workout_id",
        "expecting_supplement_name",
        "expecting_supplement_time",
        "selecting_days",
        "expecting_supplement_log",
        "choosing_supplement_for_edit",
        "expecting_supplement_history_choice",
        "expecting_supplement_history_time",
        "expecting_photo_input",
        "expecting_label_photo_input",
        "expecting_barcode_photo_input",
        "expecting_label_weight_input",
        "expecting_food_input",
        "expecting_ai_food_input",
        "kbju_menu_open",
        "awaiting_kbju_choice",
        "expecting_kbju_manual_norm",
        "awaiting_kbju_goal_edit",
        "expecting_account_deletion_confirm",
        "expecting_procedure_name",
        "expecting_water_amount",
        "procedures_menu_open",
        "water_menu_open",

    ]:
        if hasattr(message.bot, attr):
            try:
                setattr(message.bot, attr, False)
            except Exception:
                pass

    for list_attr in ["user_weights", "user_measurements", "todays_workouts", "history_workouts"]:
        if hasattr(message.bot, list_attr):
            try:
                delattr(message.bot, list_attr)
            except Exception:
                pass
        # КБЖУ-тест: очищаем сессию для пользователя
    user_id = str(message.from_user.id)
    if hasattr(message.bot, "kbju_test_sessions"):
        try:
            message.bot.kbju_test_sessions.pop(user_id, None)
        except Exception:
            pass
    if hasattr(message.bot, "kbju_test_step"):
        try:
            message.bot.kbju_test_step = None
        except Exception:
            pass
    
    if hasattr(message.bot, "meal_edit_context"):
        try:
            message.bot.meal_edit_context.pop(user_id, None)
        except Exception:
            pass

    if hasattr(message.bot, "meal_entry_dates"):
        try:
            message.bot.meal_entry_dates.pop(user_id, None)
        except Exception:
            pass

    for context_attr in ["date_selection_context", "selected_date"]:
        if hasattr(message.bot, context_attr):
            try:
                delattr(message.bot, context_attr)
            except Exception:
                pass

    for exercise_attr in ["current_category", "current_exercise", "current_variant"]:
        if hasattr(message.bot, exercise_attr):
            try:
                delattr(message.bot, exercise_attr)
            except Exception:
                pass

    for calendar_attr in ["edit_workout_date", "edit_calendar_month"]:
        if hasattr(message.bot, calendar_attr):
            try:
                delattr(message.bot, calendar_attr)
            except Exception:
                pass

    if hasattr(message.bot, "active_supplement") and not keep_supplements:
        try:
            message.bot.active_supplement.pop(user_id, None)
        except Exception:
            pass
    if hasattr(message.bot, "supplement_edit_index") and not keep_supplements:
        try:
            message.bot.supplement_edit_index.pop(user_id, None)
        except Exception:
            pass
    if hasattr(message.bot, "supplement_log_choice"):
        try:
            message.bot.supplement_log_choice.pop(user_id, None)
        except Exception:
            pass
    if hasattr(message.bot, "supplement_history_action"):
        try:
            message.bot.supplement_history_action.pop(user_id, None)
        except Exception:
            pass


@dp.message(F.text.in_(["🔄 Главное меню", "🏠 Главное меню"]))
async def go_main_menu(message: Message):
    reset_user_state(message)
    message.bot.menu_stack = [main_menu]
    
    # Отдельное сообщение "Возвращаю в главное меню"
    await message.answer("🔄 Возвращаю в главное меню")
    
    # Главное меню
    progress_text = format_progress_block(str(message.from_user.id))
    water_progress_text = format_water_progress_block(str(message.from_user.id))
    workouts_text = format_today_workouts_block(str(message.from_user.id), include_date=False)
    today_line = f"📅 <b>{date.today().strftime('%d.%m.%Y')}</b>"
    
    main_menu_text = f"{today_line}\n\n{progress_text}\n\n{water_progress_text}\n\n{workouts_text}"
    await answer_with_menu(
        message,
        main_menu_text,
        reply_markup=main_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "⬅️ Назад")
async def go_back(message: Message):
    # запоминаем, была ли открыта КБЖУ-сессия, чтобы не терять флаг при возврате
    kbju_was_open = getattr(message.bot, "kbju_menu_open", False)

    # Сбрасываем все флаги добавок при нажатии "Назад"
    reset_supplement_state(message)
    
    reset_user_state(message, keep_supplements=True)

    stack = getattr(message.bot, "menu_stack", [main_menu])
    if not stack:
        stack = [main_menu]

    if len(stack) > 1:
        stack.pop()

    previous_menu = stack[-1] if stack else main_menu
    message.bot.menu_stack = stack

    # если были в разделе КБЖУ, возвращая меню снова включаем обработчики этого раздела
    kbju_menus = {kbju_menu, kbju_intro_menu, kbju_add_menu, kbju_after_meal_menu}
    if kbju_was_open or previous_menu in kbju_menus:
        message.bot.kbju_menu_open = True

    await answer_with_menu(message, "⬅️ Возвращаюсь назад", reply_markup=previous_menu)


@dp.message(F.text == "⚖️ Вес / 📏 Замеры")
async def weight_and_measurements(message: Message):
    await answer_with_menu(message, "Выбери, что хочешь посмотреть:", reply_markup=my_data_menu)


def get_supplements_for_user(bot, user_id: str) -> list[dict]:
    if not hasattr(bot, "supplements"):
        bot.supplements = {}
    if user_id not in bot.supplements:
        bot.supplements[user_id] = load_supplements_from_db(user_id)

    supplements_list = bot.supplements[user_id]
    for item in supplements_list:
        item.setdefault("history", [])
    return supplements_list


def get_user_supplements(message: Message) -> list[dict]:
    return get_supplements_for_user(message.bot, str(message.from_user.id))


def parse_supplement_amount(text: str) -> float | None:
    normalized = text.replace(",", ".").strip()
    try:
        return float(normalized)
    except ValueError:
        return None


def has_pending_supplement_amount(message: Message) -> bool:
    """Понимаем, что пользователь находится в потоке отметки приёма добавки.

    Иногда флаг ``expecting_supplement_amount`` может сбрасываться другими
    обработчиками. Чтобы пользователь не попадал в тренировочный сценарий,
    дополнительно проверяем, что для него выбрана добавка или дата приёма.
    """

    user_id = str(message.from_user.id)
    context_is_supplement = getattr(message.bot, "date_selection_context", None) == "supplement_log"
    awaiting_amount = getattr(message.bot, "expecting_supplement_amount", False)
    awaiting_for_user = (
        user_id
        in getattr(message.bot, "expecting_supplement_amount_users", set())
    )
    choice = getattr(message.bot, "supplement_log_choice", {}).get(user_id)
    selected_date = getattr(message.bot, "supplement_log_date", {}).get(user_id)
    return (
        awaiting_amount
        or awaiting_for_user
        or context_is_supplement
        or bool(choice)
        or selected_date is not None
    )


def load_supplements_from_db(user_id: str) -> list[dict]:
    session = SessionLocal()
    try:
        supplements = session.query(Supplement).filter_by(user_id=user_id).all()
        ids = [sup.id for sup in supplements]
        entries_map: dict[int, list[dict]] = {sup_id: [] for sup_id in ids}

        if ids:
            all_entries = (
                session.query(SupplementEntry)
                .filter(
                    SupplementEntry.user_id == user_id,
                    SupplementEntry.supplement_id.in_(ids),
                )
                .order_by(SupplementEntry.timestamp.asc())
                .all()
            )
            for entry in all_entries:
                entries_map.setdefault(entry.supplement_id, []).append(
                    {"id": entry.id, "timestamp": entry.timestamp, "amount": entry.amount}
                )

        result: list[dict] = []
        for sup in supplements:
            # Безопасно получаем notifications_enabled, если поле не существует в БД
            notifications_enabled = True
            try:
                # Проверяем наличие атрибута в объекте модели
                if hasattr(sup, 'notifications_enabled'):
                    try:
                        notifications_enabled = sup.notifications_enabled
                    except (AttributeError, KeyError):
                        # Если поле есть в модели, но не в БД, используем значение по умолчанию
                        notifications_enabled = True
            except Exception:
                # В случае любой ошибки используем значение по умолчанию
                notifications_enabled = True
            
            result.append({
                "id": sup.id,
                "name": sup.name,
                "times": json.loads(sup.times_json or "[]"),
                "days": json.loads(sup.days_json or "[]"),
                "duration": sup.duration or "постоянно",
                "history": entries_map.get(sup.id, []).copy(),
                "ready": True,
                "notifications_enabled": notifications_enabled,
            })

        return result
    except Exception as e:
        print(f"❌ Ошибка при загрузке добавок из БД: {repr(e)}")
        return []
    finally:
        session.close()


def refresh_supplements_cache(bot, user_id: str):
    if not hasattr(bot, "supplements"):
        bot.supplements = {}
    bot.supplements[user_id] = load_supplements_from_db(user_id)


def persist_supplement_record(user_id: str, payload: dict, supplement_id: int | None) -> int | None:
    session = SessionLocal()
    try:
        if supplement_id:
            sup = session.query(Supplement).filter_by(id=supplement_id, user_id=user_id).first()
            if not sup:
                return None
        else:
            sup = Supplement(user_id=user_id)

        sup.name = payload.get("name", sup.name)
        sup.times_json = json.dumps(payload.get("times", []), ensure_ascii=False)
        sup.days_json = json.dumps(payload.get("days", []), ensure_ascii=False)
        sup.duration = payload.get("duration", sup.duration or "постоянно")
        # Безопасно устанавливаем notifications_enabled, если поле существует в модели
        if hasattr(sup, 'notifications_enabled'):
            sup.notifications_enabled = payload.get("notifications_enabled", True)

        session.add(sup)
        session.commit()
        session.refresh(sup)
        return sup.id
    finally:
        session.close()


def delete_supplement_record(user_id: str, supplement_id: int | None) -> None:
    if not supplement_id:
        return

    session = SessionLocal()
    try:
        session.query(SupplementEntry).filter_by(
            user_id=user_id, supplement_id=supplement_id
        ).delete()
        session.query(Supplement).filter_by(id=supplement_id, user_id=user_id).delete()
        session.commit()
    finally:
        session.close()


def reset_supplement_state(message: Message):
    for flag in [
        "expecting_supplement_name",
        "expecting_supplement_time",
        "selecting_days",
        "expecting_supplement_log",
        "choosing_supplement_for_edit",
        "choosing_supplement_for_view",
        "viewing_supplement_details",
        "expecting_supplement_history_choice",
        "expecting_supplement_history_time",
        "expecting_supplement_history_amount",
        "expecting_supplement_amount",
    ]:
        if hasattr(message.bot, flag):
            setattr(message.bot, flag, False)

    if hasattr(message.bot, "active_supplement"):
        message.bot.active_supplement.pop(str(message.from_user.id), None)
    if hasattr(message.bot, "supplement_edit_index"):
        message.bot.supplement_edit_index.pop(str(message.from_user.id), None)
    if hasattr(message.bot, "supplement_log_choice"):
        message.bot.supplement_log_choice.pop(str(message.from_user.id), None)
    if hasattr(message.bot, "supplement_log_date"):
        message.bot.supplement_log_date.pop(str(message.from_user.id), None)
    if hasattr(message.bot, "supplement_history_action"):
        message.bot.supplement_history_action.pop(str(message.from_user.id), None)
    if hasattr(message.bot, "expecting_supplement_amount_users"):
        message.bot.expecting_supplement_amount_users.discard(str(message.from_user.id))
    if hasattr(message.bot, "current_supplement_view"):
        message.bot.current_supplement_view.pop(str(message.from_user.id), None)


def get_active_supplement(message: Message) -> dict:
    user_id = str(message.from_user.id)
    if not hasattr(message.bot, "active_supplement"):
        message.bot.active_supplement = {}
    return message.bot.active_supplement.setdefault(
        user_id,
        {
            "id": None,
            "name": "",
            "times": [],
            "days": [],
            "duration": "постоянно",
            "history": [],
            "ready": False,
            "notifications_enabled": True,
        },
    )


def get_supplement_edit_index(message: Message):
    user_id = str(message.from_user.id)
    if not hasattr(message.bot, "supplement_edit_index"):
        message.bot.supplement_edit_index = {}
    return message.bot.supplement_edit_index.get(user_id)


def set_supplement_edit_index(message: Message, index: int | None):
    user_id = str(message.from_user.id)
    if not hasattr(message.bot, "supplement_edit_index"):
        message.bot.supplement_edit_index = {}
    if index is None:
        message.bot.supplement_edit_index.pop(user_id, None)
    else:
        message.bot.supplement_edit_index[user_id] = index


def set_current_supplement_view(message: Message, index: int | None):
    user_id = str(message.from_user.id)
    if not hasattr(message.bot, "current_supplement_view"):
        message.bot.current_supplement_view = {}
    if index is None:
        message.bot.current_supplement_view.pop(user_id, None)
    else:
        message.bot.current_supplement_view[user_id] = index


def get_current_supplement_view(message: Message) -> int | None:
    user_id = str(message.from_user.id)
    if not hasattr(message.bot, "current_supplement_view"):
        return None
    return message.bot.current_supplement_view.get(user_id)


def supplements_main_menu(has_items: bool = False) -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="➕ Создать добавку")]]
    if has_items:
        buttons.append([KeyboardButton(text="📋 Мои добавки"), KeyboardButton(text="📅 Календарь добавок")])
        buttons.append([KeyboardButton(text="✅ Отметить приём")])
    buttons.append([main_menu_button])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def supplements_choice_menu(supplements: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=item["name"])] for item in supplements]
    rows.append([KeyboardButton(text="⬅️ Назад"), main_menu_button])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def supplements_view_menu(supplements: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=item["name"])] for item in supplements]
    rows.append([KeyboardButton(text="⬅️ Назад"), main_menu_button])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def supplement_details_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Редактировать добавку")],
            [KeyboardButton(text="🗑 Удалить добавку"), KeyboardButton(text="✅ Отметить добавку")],
            [KeyboardButton(text="⬅️ Назад"), main_menu_button],
        ],
        resize_keyboard=True,
    )


def normalize_history_entry(entry) -> datetime | None:
    if isinstance(entry, dict):
        return normalize_history_entry(entry.get("timestamp"))
    if isinstance(entry, datetime):
        return entry
    if isinstance(entry, date):
        return datetime.combine(entry, datetime.min.time())
    if isinstance(entry, str):
        for fmt in ["%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(entry, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(entry)
        except (ValueError, TypeError):
            return None
    return None


def get_supplement_history_days(bot, user_id: str, year: int, month: int) -> set[int]:
    supplements_list = get_supplements_for_user(bot, user_id)
    days: set[int] = set()

    for sup in supplements_list:
        for entry in sup.get("history", []):
            ts = normalize_history_entry(entry)
            if ts and ts.year == year and ts.month == month:
                days.add(ts.day)

    return days


def get_supplement_entries_for_day(bot, user_id: str, target_date: date) -> list[dict]:
    supplements_list = get_supplements_for_user(bot, user_id)
    entries: list[dict] = []

    for sup_idx, sup in enumerate(supplements_list):
        for entry_idx, raw_entry in enumerate(sup.get("history", [])):
            ts = normalize_history_entry(raw_entry)
            if ts and ts.date() == target_date:
                entries.append(
                    {
                        "supplement_name": sup.get("name", "Добавка"),
                        "supplement_index": sup_idx,
                        "entry_index": entry_idx,
                        "timestamp": ts,
                        "time_text": ts.strftime("%H:%M"),
                        "amount": raw_entry.get("amount") if isinstance(raw_entry, dict) else None,
                    }
                )

    return entries


def set_supplement_history_action(bot, user_id: str, action: dict | None):
    if not hasattr(bot, "supplement_history_action"):
        bot.supplement_history_action = {}

    if action is None:
        bot.supplement_history_action.pop(user_id, None)
    else:
        bot.supplement_history_action[user_id] = action


def build_supplement_calendar_keyboard(bot, user_id: str, year: int, month: int) -> InlineKeyboardMarkup:
    days_with_history = get_supplement_history_days(bot, user_id, year, month)
    keyboard: list[list[InlineKeyboardButton]] = []

    header = InlineKeyboardButton(text=f"{MONTH_NAMES[month]} {year}", callback_data="noop")
    keyboard.append([header])

    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(text=d, callback_data="noop") for d in week_days])

    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                marker = "💊" if day in days_with_history else ""
                row.append(
                    InlineKeyboardButton(
                        text=f"{day}{marker}",
                        callback_data=f"supcal_day:{year}-{month:02d}-{day:02d}",
                    )
                )
        keyboard.append(row)

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    keyboard.append(
        [
            InlineKeyboardButton(text="◀️", callback_data=f"supcal_nav:{prev_year}-{prev_month:02d}"),
            InlineKeyboardButton(text="Закрыть", callback_data="supcal_close"),
            InlineKeyboardButton(text="▶️", callback_data=f"supcal_nav:{next_year}-{next_month:02d}"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_supplement_day_actions_keyboard(entries: list[dict], target_date: date) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for entry in entries:
        amount_text = f" — {entry['amount']}" if entry.get("amount") is not None else ""
        label = f"{entry['supplement_name']} ({entry['time_text']}{amount_text})"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {label}",
                    callback_data=(
                        f"supcal_edit:{target_date.isoformat()}:{entry['supplement_index']}:{entry['entry_index']}"
                    ),
                ),
                InlineKeyboardButton(
                    text=f"🗑 {label}",
                    callback_data=(
                        f"supcal_del:{target_date.isoformat()}:{entry['supplement_index']}:{entry['entry_index']}"
                    ),
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить ещё" if entries else "➕ Добавить приём",
                callback_data=f"supcal_add:{target_date.isoformat()}",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к календарю",
                callback_data=f"supcal_back:{target_date.year}-{target_date.month:02d}",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_supplement_calendar(message: Message, user_id: str, year: int | None = None, month: int | None = None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    keyboard = build_supplement_calendar_keyboard(message.bot, user_id, year, month)
    await message.answer(
        "📅 Календарь добавок. Выберите день, чтобы посмотреть, добавить или изменить приёмы:",
        reply_markup=keyboard,
    )


async def show_supplement_day_entries(message: Message, user_id: str, target_date: date):
    entries = get_supplement_entries_for_day(message.bot, user_id, target_date)
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
        "\n".join(lines), reply_markup=build_supplement_day_actions_keyboard(entries, target_date)
    )


def format_supplement_history_lines(sup: dict) -> list[str]:
    history = sup.get("history", [])
    if not history:
        return ["Отметок пока нет."]

    sorted_history = sorted(
        history,
        key=lambda entry: normalize_history_entry(entry) or datetime.min,
        reverse=True,
    )

    lines: list[str] = []
    for entry in sorted_history:
        ts = normalize_history_entry(entry)
        if not ts:
            continue
        amount = entry.get("amount") if isinstance(entry, dict) else None
        amount_text = f" — {amount}" if amount is not None else ""
        lines.append(f"{ts.strftime('%d.%m.%Y %H:%M')}{amount_text}")

    return lines or ["Отметок пока нет."]


async def show_supplement_details(message: Message, sup: dict, index: int):
    set_current_supplement_view(message, index)
    message.bot.viewing_supplement_details = True
    history_lines = format_supplement_history_lines(sup)

    lines = [f"💊 {sup.get('name', 'Добавка')}", "", "Отметки:"]
    lines.extend([f"• {item}" for item in history_lines])

    await answer_with_menu(message, "\n".join(lines), reply_markup=supplement_details_menu())


async def show_my_supplements_list(message: Message):
    supplements_list = get_user_supplements(message)
    if not supplements_list:
        await answer_with_menu(
            message,
            "Пока нет созданных добавок.",
            reply_markup=supplements_main_menu(has_items=False),
        )
        return

    message.bot.choosing_supplement_for_view = True
    message.bot.viewing_supplement_details = False
    set_current_supplement_view(message, None)

    await answer_with_menu(
        message,
        "Выбери добавку из списка:",
        reply_markup=supplements_view_menu(supplements_list),
    )


@dp.callback_query(F.data == "supcal_close")
async def close_supplement_calendar(callback: CallbackQuery):
    await callback.answer("Календарь закрыт")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@dp.callback_query(F.data.startswith("supcal_nav:"))
async def navigate_supplement_calendar(callback: CallbackQuery):
    await callback.answer()
    _, ym = callback.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    user_id = str(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=build_supplement_calendar_keyboard(callback.bot, user_id, year, month)
    )


@dp.callback_query(F.data.startswith("supcal_back:"))
async def back_to_supplement_calendar(callback: CallbackQuery):
    await callback.answer()
    _, ym = callback.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    user_id = str(callback.from_user.id)
    await show_supplement_calendar(callback.message, user_id, year, month)


@dp.callback_query(F.data.startswith("supcal_day:"))
async def open_supplement_day(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    user_id = str(callback.from_user.id)
    await show_supplement_day_entries(callback.message, user_id, target_date)


@dp.callback_query(F.data.startswith("supcal_add:"))
async def add_supplement_from_calendar(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    user_id = str(callback.from_user.id)

    set_supplement_history_action(
        callback.bot,
        user_id,
        {"mode": "add", "date": target_date, "original": None, "supplement_name": None},
    )
    callback.bot.expecting_supplement_history_choice = True

    supplements_list = get_supplements_for_user(callback.bot, user_id)
    await answer_with_menu(
        callback.message,
        f"Выбери добавку для отметки на {target_date.strftime('%d.%m.%Y')}:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@dp.callback_query(F.data.startswith("supcal_del:"))
async def delete_supplement_entry(callback: CallbackQuery):
    await callback.answer()
    _, payload = callback.data.split(":", 1)
    date_str, sup_idx_str, entry_idx_str = payload.split(":")
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    sup_idx = int(sup_idx_str)
    entry_idx = int(entry_idx_str)
    user_id = str(callback.from_user.id)

    supplements_list = get_supplements_for_user(callback.bot, user_id)
    if sup_idx >= len(supplements_list):
        await callback.message.answer("Не нашёл запись для удаления.")
        return

    history = supplements_list[sup_idx].get("history", [])
    if entry_idx >= len(history):
        await callback.message.answer("Не нашёл запись для удаления.")
        return

    removed = history.pop(entry_idx)
    entry_id = removed.get("id") if isinstance(removed, dict) else None
    if entry_id:
        session = SessionLocal()
        try:
            session.query(SupplementEntry).filter_by(id=entry_id, user_id=user_id).delete()
            session.commit()
        finally:
            session.close()
    await callback.message.answer("🗑 Приём удалён.")
    await show_supplement_day_entries(callback.message, user_id, target_date)


@dp.callback_query(F.data.startswith("supcal_edit:"))
async def edit_supplement_entry(callback: CallbackQuery):
    await callback.answer()
    _, payload = callback.data.split(":", 1)
    date_str, sup_idx_str, entry_idx_str = payload.split(":")
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    sup_idx = int(sup_idx_str)
    entry_idx = int(entry_idx_str)
    user_id = str(callback.from_user.id)

    supplements_list = get_supplements_for_user(callback.bot, user_id)
    if sup_idx >= len(supplements_list):
        await callback.message.answer("Не нашёл запись для редактирования.")
        return

    history = supplements_list[sup_idx].get("history", [])
    if entry_idx >= len(history):
        await callback.message.answer("Не нашёл запись для редактирования.")
        return

    callback.bot.expecting_supplement_history_choice = True
    set_supplement_history_action(
        callback.bot,
        user_id,
        {
            "mode": "edit",
            "date": target_date,
            "original": {"supplement_index": sup_idx, "entry_index": entry_idx},
            "supplement_name": None,
            "original_amount": history[entry_idx].get("amount")
            if isinstance(history[entry_idx], dict)
            else None,
        },
    )

    supplements_list = get_supplements_for_user(callback.bot, user_id)
    await answer_with_menu(
        callback.message,
        f"Выбери новую добавку или оставь прежнюю для приёма {target_date.strftime('%d.%m.%Y')}:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@dp.message(F.text == "💊 Добавки")
async def supplements(message: Message):
    try:
        supplements_list = get_user_supplements(message)
    except Exception as e:
        print(f"❌ Ошибка при загрузке добавок: {repr(e)}")
        await message.answer("Произошла ошибка при загрузке добавок. Попробуйте позже.")
        return
    
    # Описание раздела от робота Дайри
    dairi_description = (
        "Привет, это Дайри на связи! 🤖\n\n"
        "💊 Раздел «Добавки»\n\n"
        "Здесь ты можешь записывать свои добавки: лекарства, витамины, БАДы и любые другие препараты. "
        "Я помогу тебе отслеживать их приём, настроить расписание и получать статистику.\n\n"
        "⚠️ Важно: протеин нужно вписывать в раздел КБЖУ, потому что там подсчитывается количество белков "
        "для твоей дневной нормы. Этот раздел предназначен для лекарств и добавок, которые не влияют на калорийность и БЖУ.\n\n"
        "Готов начать? Создай свою первую добавку!"
    )
    
    if not supplements_list:
        await answer_with_menu(
            message,
            dairi_description,
            reply_markup=supplements_main_menu(has_items=False),
        )
        return

    # Если добавки есть, показываем описание и список
    lines = [
        "Привет, это Дайри на связи! 🤖\n\n"
        "💊 Раздел «Добавки»\n\n"
        "Здесь ты можешь записывать свои добавки: лекарства, витамины, БАДы и любые другие препараты. "
        "Я помогу тебе отслеживать их приём, настроить расписание и получать статистику.\n\n"
        "⚠️ Важно: протеин нужно вписывать в раздел КБЖУ, потому что там подсчитывается количество белков "
        "для твоей дневной нормы. Этот раздел предназначен для лекарств и добавок, которые не влияют на калорийность и БЖУ.\n\n"
        "📋 Твои добавки:\n"
    ]
    for item in supplements_list:
        days = ", ".join(item["days"]) if item["days"] else "не выбрано"
        times = ", ".join(item["times"]) if item["times"] else "не выбрано"
        lines.append(
            f"\n💊 {item['name']} \n⏰ Время приема: {times}\n📅 Дни приема: {days}\n⏳ Длительность: {item['duration']}"
        )
    await answer_with_menu(message, "\n".join(lines), reply_markup=supplements_main_menu(has_items=True))


@dp.message(F.text == "📋 Мои добавки")
async def supplements_list_view(message: Message):
    await show_my_supplements_list(message)


@dp.message(lambda m: getattr(m.bot, "choosing_supplement_for_view", False))
async def choose_supplement_for_view(message: Message):
    # Проверяем, не является ли это кнопкой меню
    menu_buttons = ["⬅️ Назад", "🍱 КБЖУ", "📆 Календарь", "💆 Процедуры", "💧 Контроль воды", 
                    "🏋️ Тренировка", "⚖️ Вес / 📏 Замеры", "💊 Добавки", "🤖 ИИ анализ деятельности", 
                    "⚙️ Настройки", "🔄 Главное меню", "📆 Календарь добавок", "✅ Отметить приём",
                    "➕ Создать добавку", "✏️ Редактировать добавку", "📅 Редактировать дни",
                    "✏️ Редактировать время"]
    
    if message.text in menu_buttons:
        # Сбрасываем флаг и позволяем другим обработчикам обработать кнопку
        message.bot.choosing_supplement_for_view = False
        # Не обрабатываем сообщение здесь, позволяем другим обработчикам обработать его
        return
    
    if message.text == "⬅️ Назад":
        message.bot.choosing_supplement_for_view = False
        await answer_with_menu(
            message,
            "Возвращаю в меню добавок.",
            reply_markup=supplements_main_menu(has_items=bool(get_user_supplements(message))),
        )
        return

    supplements_list = get_user_supplements(message)
    target_index = next(
        (idx for idx, item in enumerate(supplements_list) if item["name"].lower() == message.text.lower()),
        None,
    )

    if target_index is None:
        # Сбрасываем флаг, если добавка не найдена, чтобы не блокировать другие действия
        message.bot.choosing_supplement_for_view = False
        await message.answer("Не нашёл такую добавку. Выбери название из списка.")
        return

    message.bot.choosing_supplement_for_view = False
    await show_supplement_details(message, supplements_list[target_index], target_index)


@dp.message(lambda m: getattr(m.bot, "viewing_supplement_details", False) and m.text == "⬅️ Назад")
async def back_from_supplement_details(message: Message):
    message.bot.viewing_supplement_details = False
    await show_my_supplements_list(message)


@dp.message(F.text == "✅ Отметить приём")
async def start_log_supplement(message: Message):
    supplements_list = get_user_supplements(message)
    if not supplements_list:
        await answer_with_menu(message, "Сначала создай добавку, чтобы отмечать приём.", reply_markup=supplements_main_menu(False))
        return

    message.bot.expecting_supplement_log = True
    await answer_with_menu(
        message,
        "Выбери добавку, приём которой нужно отметить:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@dp.message(F.text == "➕ Создать добавку")
async def start_create_supplement(message: Message):
    reset_supplement_state(message)
    message.bot.expecting_supplement_name = True
    set_supplement_edit_index(message, None)
    sup = get_active_supplement(message)
    sup.update(
        {"id": None, "name": "", "times": [], "days": [], "duration": "постоянно", "ready": False}
    )
    await message.answer("Введите название добавки.")


@dp.message(lambda m: getattr(m.bot, "expecting_supplement_name", False))
async def handle_supplement_name(message: Message):
    sup = get_active_supplement(message)
    sup["name"] = message.text.strip()
    sup["ready"] = False
    message.bot.expecting_supplement_name = False
    await answer_with_menu(
        message,
        "Выберите время, дни, длительность приема добавки и уведомления (по желанию):",
        reply_markup=supplement_edit_menu(show_save=True),
    )


@dp.message(F.text == "✏️ Изменить название")
async def rename_supplement(message: Message):
    sup = get_active_supplement(message)
    if not sup["name"]:
        await message.answer("Сначала выберите или создайте добавку, чтобы изменить название.")
        return
    message.bot.expecting_supplement_name = True
    sup["ready"] = False
    await message.answer("Введите новое название добавки.")


@dp.message(F.text == "✏️ Редактировать время")
async def edit_supplement_time(message: Message):
    sup = get_active_supplement(message)
    sup["ready"] = False
    message.bot.expecting_supplement_time = True

    current_times = ", ".join(sup["times"]) if sup["times"] else "пока не добавлено"
    await message.answer(
        "Введите время приема в формате ЧЧ:ММ (например, 09:00).\n"
        f"Текущее расписание: {current_times}"
    )


@dp.message(lambda m: m.text == "➕ Добавить" and not getattr(m.bot, "kbju_menu_open", False))
async def ask_time_value(message: Message):
    if getattr(message.bot, "selecting_days", False):
        return
    sup = get_active_supplement(message)
    if not sup.get("name"):
        await message.answer("Ошибка: добавка не найдена. Начните создание заново.")
        return
    sup["ready"] = False
    # Явно устанавливаем флаг ожидания времени
    message.bot.expecting_supplement_time = True
    await message.answer("Введите время приема в формате ЧЧ:ММ\nНапример: 09:00")



@dp.message(lambda m: getattr(m.bot, "expecting_supplement_time", False))
async def handle_time_value(message: Message):
    text = message.text.strip()
    import re

    # Проверяем, не является ли это кнопкой меню
    menu_buttons = ["⬅️ Назад", "💾 Сохранить", "➕ Добавить", "❌"]
    if any(text.startswith(btn) for btn in menu_buttons):
        # Если это кнопка меню, не обрабатываем как время
        return

    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", text):
        await message.answer("Пожалуйста, укажите время в формате ЧЧ:ММ. Например: 09:00")
        # Флаг остается установленным, чтобы пользователь мог попробовать снова
        return

    sup = get_active_supplement(message)
    if not sup.get("name"):
        message.bot.expecting_supplement_time = False
        await message.answer("Ошибка: добавка не найдена. Начните создание заново.")
        return
    
    sup["ready"] = False
    if text not in sup["times"]:
        sup["times"].append(text)
    sup["times"].sort()
    message.bot.expecting_supplement_time = False

    times_list = "\n".join(sup["times"])
    await message.answer(
        f"💊 {sup['name']}\n\nРасписание приема:\n{times_list}\n\nℹ️ Нажмите ❌ чтобы удалить время",
        reply_markup=time_edit_menu(sup["times"]),
    )


@dp.message(lambda m: getattr(m.bot, "expecting_supplement_log", False))
async def log_supplement_intake(message: Message):
    supplements_list = get_user_supplements(message)
    target = next(
        (item for item in supplements_list if item["name"].lower() == message.text.lower()),
        None,
    )

    if not target:
        await message.answer("Не нашёл такую добавку. Выбери название из списка или вернись назад.")
        return

    message.bot.expecting_supplement_log = False
    if not hasattr(message.bot, "supplement_log_choice"):
        message.bot.supplement_log_choice = {}
    message.bot.supplement_log_choice[str(message.from_user.id)] = target["name"]

    start_date_selection(message.bot, "supplement_log")
    await answer_with_menu(message, get_date_prompt("supplement_log"), reply_markup=training_date_menu)


@dp.message(
    lambda m: getattr(m.bot, "expecting_supplement_amount", False)
    or has_pending_supplement_amount(m)
)
async def set_supplement_amount(message: Message):
    user_id = str(message.from_user.id)
    if not hasattr(message.bot, "supplement_log_choice"):
        message.bot.expecting_supplement_amount = False
        await message.answer("Не выбрана добавка для записи приёма.")
        return

    supplement_name = message.bot.supplement_log_choice.get(user_id)
    if not supplement_name:
        message.bot.expecting_supplement_amount = False
        await message.answer("Не выбрана добавка для записи приёма.")
        return

    amount = parse_supplement_amount(message.text)
    if amount is None:
        await message.answer("Пожалуйста, укажи количество числом, например: 1 или 2.5")
        return

    selected_date = getattr(message.bot, "supplement_log_date", {}).get(user_id, date.today())
    supplements_list = get_supplements_for_user(message.bot, user_id)
    target = next(
        (item for item in supplements_list if item["name"].lower() == supplement_name.lower()),
        None,
    )

    timestamp = datetime.combine(selected_date, datetime.now().time())
    new_entry_id: int | None = None
    if target and target.get("id") is not None:
        session = SessionLocal()
        try:
            new_entry = SupplementEntry(
                user_id=user_id,
                supplement_id=target["id"],
                timestamp=timestamp,
                amount=amount,
            )
            session.add(new_entry)
            session.commit()
            session.refresh(new_entry)
            new_entry_id = new_entry.id
        finally:
            session.close()

    if target is not None:
        target.setdefault("history", []).append(
            {"id": new_entry_id, "timestamp": timestamp, "amount": amount}
        )
        await answer_with_menu(
            message,
            f"Записал приём {target['name']} ({amount}) на {timestamp.strftime('%d.%m.%Y %H:%M')}.",
            reply_markup=supplements_main_menu(has_items=True),
        )
    else:
        await message.answer("Не нашёл выбранную добавку для записи приёма.")

    message.bot.expecting_supplement_amount = False
    if hasattr(message.bot, "expecting_supplement_amount_users"):
        message.bot.expecting_supplement_amount_users.discard(user_id)
    if hasattr(message.bot, "supplement_log_choice"):
        message.bot.supplement_log_choice.pop(user_id, None)
    if hasattr(message.bot, "supplement_log_date"):
        message.bot.supplement_log_date.pop(user_id, None)


@dp.message(lambda m: getattr(m.bot, "expecting_supplement_history_choice", False))
async def choose_supplement_for_history(message: Message):
    # Проверяем, не является ли это кнопкой меню
    menu_buttons = ["⬅️ Назад", "🍱 КБЖУ", "📆 Календарь", "💆 Процедуры", "💧 Контроль воды", 
                    "🏋️ Тренировка", "⚖️ Вес / 📏 Замеры", "💊 Добавки", "🤖 ИИ анализ деятельности", 
                    "⚙️ Настройки", "🔄 Главное меню", "📆 Календарь добавок", "✅ Отметить приём",
                    "➕ Создать добавку", "✏️ Редактировать добавку", "📅 Редактировать дни",
                    "✏️ Редактировать время"]
    
    if message.text in menu_buttons:
        # Сбрасываем флаг и позволяем другим обработчикам обработать кнопку
        message.bot.expecting_supplement_history_choice = False
        # Не обрабатываем сообщение здесь, позволяем другим обработчикам обработать его
        return
    
    user_id = str(message.from_user.id)
    action = getattr(message.bot, "supplement_history_action", {}).get(user_id)
    supplements_list = get_user_supplements(message)
    target = next(
        (item for item in supplements_list if item["name"].lower() == message.text.lower()),
        None,
    )

    if not action:
        message.bot.expecting_supplement_history_choice = False
        await message.answer("Не получилось определить запрошенное действие.")
        return

    if not target:
        # Сбрасываем флаг, если добавка не найдена, чтобы не блокировать другие действия
        message.bot.expecting_supplement_history_choice = False
        await message.answer("Не нашёл такую добавку. Выбери название из списка.")
        return

    message.bot.expecting_supplement_history_choice = False
    message.bot.expecting_supplement_history_time = True
    action["supplement_name"] = target["name"]
    set_supplement_history_action(message.bot, user_id, action)

    await message.answer(
        "Укажи время приёма в формате ЧЧ:ММ. Например: 09:30",
    )


@dp.message(lambda m: getattr(m.bot, "expecting_supplement_history_time", False))
async def set_history_entry_time(message: Message):
    import re

    time_text = message.text.strip()
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", time_text):
        await message.answer("Пожалуйста, укажи время в формате ЧЧ:ММ (например, 08:15)")
        return

    user_id = str(message.from_user.id)
    action = getattr(message.bot, "supplement_history_action", {}).get(user_id)
    if not action:
        message.bot.expecting_supplement_history_time = False
        await message.answer("Не получилось сохранить приём: не найдено действие.")
        return

    supplement_name = action.get("supplement_name")
    if not supplement_name:
        message.bot.expecting_supplement_history_time = False
        await message.answer("Не выбрана добавка для записи.")
        return

    supplements_list = get_user_supplements(message)
    target = next(
        (item for item in supplements_list if item["name"].lower() == supplement_name.lower()),
        None,
    )

    if not target:
        message.bot.expecting_supplement_history_time = False
        await message.answer("Не нашёл выбранную добавку для записи.")
        return

    timestamp = datetime.combine(action["date"], datetime.strptime(time_text, "%H:%M").time())
    action["time"] = timestamp.time()
    message.bot.expecting_supplement_history_time = False
    message.bot.expecting_supplement_history_amount = True
    set_supplement_history_action(message.bot, user_id, action)

    hint = ""
    if action.get("original_amount") is not None:
        hint = f" Текущее значение: {action['original_amount']}"

    await message.answer(
        f"Укажи количество для приёма.{hint}".strip()
    )


@dp.message(lambda m: getattr(m.bot, "expecting_supplement_history_amount", False))
async def set_history_entry_amount(message: Message):
    user_id = str(message.from_user.id)
    action = getattr(message.bot, "supplement_history_action", {}).get(user_id)
    amount = parse_supplement_amount(message.text)

    if amount is None:
        await message.answer("Пожалуйста, укажи количество числом, например: 1 или 2.5")
        return

    if not action:
        message.bot.expecting_supplement_history_amount = False
        await message.answer("Не получилось сохранить приём: не найдено действие.")
        return

    supplement_name = action.get("supplement_name")
    if not supplement_name:
        message.bot.expecting_supplement_history_amount = False
        await message.answer("Не выбрана добавка для записи.")
        return

    supplements_list = get_user_supplements(message)
    target = next(
        (item for item in supplements_list if item["name"].lower() == supplement_name.lower()),
        None,
    )

    if not target:
        message.bot.expecting_supplement_history_amount = False
        await message.answer("Не нашёл выбранную добавку для записи.")
        return

    timestamp = datetime.combine(action["date"], action.get("time") or datetime.now().time())

    if action.get("mode") == "edit" and action.get("original"):
        original = action["original"]
        orig_idx = original.get("supplement_index")
        orig_entry_idx = original.get("entry_index")
        if orig_idx is not None and orig_entry_idx is not None and orig_idx < len(supplements_list):
            orig_history = supplements_list[orig_idx].get("history", [])
            if orig_entry_idx < len(orig_history):
                to_remove = orig_history.pop(orig_entry_idx)
                entry_id = to_remove.get("id") if isinstance(to_remove, dict) else None
                if entry_id:
                    session = SessionLocal()
                    try:
                        session.query(SupplementEntry).filter_by(
                            id=entry_id, user_id=user_id
                        ).delete()
                        session.commit()
                    finally:
                        session.close()

    new_entry_id: int | None = None
    if target.get("id") is not None:
        session = SessionLocal()
        try:
            new_entry = SupplementEntry(
                user_id=user_id,
                supplement_id=target["id"],
                timestamp=timestamp,
                amount=amount,
            )
            session.add(new_entry)
            session.commit()
            session.refresh(new_entry)
            new_entry_id = new_entry.id
        finally:
            session.close()

    target.setdefault("history", []).append(
        {"id": new_entry_id, "timestamp": timestamp, "amount": amount}
    )

    message.bot.expecting_supplement_history_amount = False
    set_supplement_history_action(message.bot, user_id, None)

    await message.answer(
        f"Записал приём {target['name']} ({amount}) на {timestamp.strftime('%d.%m.%Y %H:%M')}.",
    )
    await show_supplement_day_entries(message, user_id, action["date"])


@dp.message(F.text.startswith("❌ "))
async def delete_time(message: Message):
    sup = get_active_supplement(message)
    sup["ready"] = False
    time_value = message.text.replace("❌ ", "").strip()
    if time_value in sup["times"]:
        sup["times"].remove(time_value)
    
    # Сбрасываем флаг ожидания времени, чтобы пользователь мог добавить новое время
    message.bot.expecting_supplement_time = False

    if sup["times"]:
        await message.answer(
            f"Обновленное расписание:\n{chr(10).join(sup['times'])}",
            reply_markup=time_edit_menu(sup["times"]),
        )
    else:
        await answer_with_menu(
            message,
            f"ℹ️ Добавьте первое время приема для {sup['name']}",
            reply_markup=time_first_menu(),
        )


@dp.message(F.text == "💾 Сохранить")
async def save_time_or_supplement(message: Message):
    sup = get_active_supplement(message)
    
    # Проверяем, что есть хотя бы название
    if not sup.get("name") or not sup["name"].strip():
        await message.answer("Пожалуйста, укажите название добавки перед сохранением.")
        return
    
    if getattr(message.bot, "expecting_supplement_time", False):
        message.bot.expecting_supplement_time = False

    if getattr(message.bot, "selecting_days", False):
        message.bot.selecting_days = False
        sup["ready"] = True
        await answer_with_menu(message, supplement_schedule_prompt(sup), reply_markup=supplement_edit_menu(show_save=True))
        return

    if not sup.get("ready"):
        sup["ready"] = True
        await answer_with_menu(
            message,
            supplement_schedule_prompt(sup),
            reply_markup=supplement_edit_menu(show_save=True),
        )
        return

    supplements_list = get_user_supplements(message)
    edit_index = get_supplement_edit_index(message)
    supplement_payload = {
        "id": sup.get("id"),
        "name": sup["name"],
        "times": sup["times"].copy(),
        "days": sup["days"].copy(),
        "duration": sup["duration"],
        "history": sup.get("history", []).copy(),
        "notifications_enabled": sup.get("notifications_enabled", True),
    }

    user_id = str(message.from_user.id)
    existing_id = None
    if edit_index is not None and 0 <= edit_index < len(supplements_list):
        existing_id = supplements_list[edit_index].get("id")

    saved_id = persist_supplement_record(user_id, supplement_payload, existing_id)
    if saved_id is not None:
        supplement_payload["id"] = saved_id

    if edit_index is not None and 0 <= edit_index < len(supplements_list):
        supplements_list[edit_index] = supplement_payload
    else:
        supplements_list.append(supplement_payload)

    refresh_supplements_cache(message.bot, user_id)

    reset_supplement_state(message)

    notifications_status = "включены" if supplement_payload.get("notifications_enabled", True) else "выключены"
    await answer_with_menu(
        message,
        "Мои добавки\n\n"
        f"💊 {supplement_payload['name']} \n"
        f"⏰ Время приема: {', '.join(supplement_payload['times']) or 'не выбрано'}\n"
        f"📅 Дни приема: {', '.join(supplement_payload['days']) or 'не выбрано'}\n"
        f"⏳ Длительность: {supplement_payload['duration']}\n"
        f"🔔 Уведомления: {notifications_status}",
        reply_markup=supplements_main_menu(has_items=True),
    )


@dp.message(F.text == "📅 Редактировать дни")
async def edit_days(message: Message):
    sup = get_active_supplement(message)
    message.bot.selecting_days = True
    await answer_with_menu(
        message,
        "Выберите дни приема:\nНажмите на день для выбора",
        reply_markup=days_menu(sup["days"]),
    )


@dp.message(lambda m: getattr(m.bot, "selecting_days", False) and m.text.replace("✅ ", "") in {"Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"})
async def toggle_day(message: Message):
    sup = get_active_supplement(message)
    sup["ready"] = False
    day = message.text.replace("✅ ", "")
    if day in sup["days"]:
        sup["days"].remove(day)
    else:
        sup["days"].append(day)

    await answer_with_menu(message, "Дни обновлены", reply_markup=days_menu(sup["days"]))


@dp.message(lambda m: getattr(m.bot, "selecting_days", False) and m.text == "Выбрать все")
async def select_all_days(message: Message):
    sup = get_active_supplement(message)
    sup["ready"] = False
    sup["days"] = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    await answer_with_menu(message, "Все дни выбраны", reply_markup=days_menu(sup["days"]))


@dp.message(F.text == "⏳ Длительность приема")
async def choose_duration(message: Message):
    await answer_with_menu(message, "Выберите длительность приема", reply_markup=duration_menu())


@dp.message(lambda m: m.text in {"Постоянно", "14 дней", "30 дней"})
async def set_duration(message: Message):
    sup = get_active_supplement(message)
    sup["duration"] = message.text.lower()
    sup["ready"] = True
    await answer_with_menu(
        message,
        supplement_schedule_prompt(sup),
        reply_markup=supplement_edit_menu(show_save=True),
    )


@dp.message(F.text == "🔔 Уведомления")
async def toggle_notifications(message: Message):
    sup = get_active_supplement(message)
    current_status = sup.get("notifications_enabled", True)
    sup["notifications_enabled"] = not current_status
    sup["ready"] = False
    
    status_text = "включены" if sup["notifications_enabled"] else "выключены"
    await answer_with_menu(
        message,
        f"🔔 Уведомления {status_text}\n\n"
        f"Уведомления будут приходить в указанное время приема добавки.",
        reply_markup=supplement_edit_menu(show_save=True),
    )


@dp.message(F.text == "⬅️ Отменить")
async def cancel_supplement(message: Message):
    reset_supplement_state(message)
    await supplements(message)


async def start_editing_supplement(message: Message, target_index: int):
    supplements_list = get_user_supplements(message)
    if not supplements_list or target_index < 0 or target_index >= len(supplements_list):
        await answer_with_menu(message, "Не нашёл такую добавку. Выбери название из списка.")
        return

    message.bot.choosing_supplement_for_edit = False
    set_supplement_edit_index(message, target_index)
    selected = supplements_list[target_index]
    sup = get_active_supplement(message)
    sup.update({
        "id": selected.get("id"),
        "name": selected.get("name", ""),
        "times": selected.get("times", []).copy(),
        "days": selected.get("days", []).copy(),
        "duration": selected.get("duration", "постоянно"),
        "history": [dict(entry) for entry in selected.get("history", [])],
        "ready": True,
        "notifications_enabled": selected.get("notifications_enabled", True),
    })

    await answer_with_menu(
        message,
        supplement_schedule_prompt(sup),
        reply_markup=supplement_edit_menu(show_save=True),
    )


@dp.message(F.text == "✏️ Редактировать добавку")
async def edit_supplement_placeholder(message: Message):
    view_index = get_current_supplement_view(message)
    if view_index is not None:
        message.bot.viewing_supplement_details = False
        await start_editing_supplement(message, view_index)
        return

    supplements_list = get_user_supplements(message)
    if not supplements_list:
        await answer_with_menu(message, "Пока нет добавок для редактирования.", reply_markup=supplements_main_menu(False))
        return

    message.bot.choosing_supplement_for_edit = True
    await answer_with_menu(
        message,
        "Выбери добавку, которую нужно отредактировать:",
        reply_markup=supplements_choice_menu(supplements_list),
    )


@dp.message(lambda m: getattr(m.bot, "choosing_supplement_for_edit", False))
async def choose_supplement_to_edit(message: Message):
    # Проверяем, не является ли это кнопкой меню
    menu_buttons = ["⬅️ Назад", "🍱 КБЖУ", "📆 Календарь", "💆 Процедуры", "💧 Контроль воды", 
                    "🏋️ Тренировка", "⚖️ Вес / 📏 Замеры", "💊 Добавки", "🤖 ИИ анализ деятельности", 
                    "⚙️ Настройки", "🔄 Главное меню", "📆 Календарь добавок", "✅ Отметить приём",
                    "➕ Создать добавку", "✏️ Редактировать добавку", "📅 Редактировать дни",
                    "✏️ Редактировать время"]
    
    if message.text in menu_buttons:
        # Сбрасываем флаг и позволяем другим обработчикам обработать кнопку
        message.bot.choosing_supplement_for_edit = False
        # Не обрабатываем сообщение здесь, позволяем другим обработчикам обработать его
        return
    
    supplements_list = get_user_supplements(message)
    target_index = next(
        (idx for idx, item in enumerate(supplements_list) if item["name"].lower() == message.text.lower()),
        None,
    )

    if target_index is None:
        # Сбрасываем флаг, если добавка не найдена, чтобы не блокировать другие действия
        message.bot.choosing_supplement_for_edit = False
        await message.answer("Не нашёл такую добавку. Выбери название из списка.")
        return

    await start_editing_supplement(message, target_index)


@dp.message(F.text == "🗑 Удалить добавку")
async def delete_supplement(message: Message):
    current_index = get_current_supplement_view(message)
    supplements_list = get_user_supplements(message)
    user_id = str(message.from_user.id)

    if current_index is None or current_index >= len(supplements_list):
        await message.answer("Сначала выбери добавку в списке 'Мои добавки'.")
        return

    target = supplements_list[current_index]
    delete_supplement_record(user_id, target.get("id"))
    refresh_supplements_cache(message.bot, user_id)

    await message.answer(f"🗑 Добавка {target.get('name', 'без названия')} удалена.")
    message.bot.viewing_supplement_details = False
    await show_my_supplements_list(message)


@dp.message(F.text == "✅ Отметить добавку")
async def mark_supplement_from_details(message: Message):
    current_index = get_current_supplement_view(message)
    supplements_list = get_user_supplements(message)
    user_id = str(message.from_user.id)

    if current_index is None or current_index >= len(supplements_list):
        await answer_with_menu(
            message,
            "Сначала выбери добавку в списке 'Мои добавки'.",
            reply_markup=supplements_main_menu(has_items=bool(supplements_list)),
        )
        return

    target = supplements_list[current_index]
    if not hasattr(message.bot, "supplement_log_choice"):
        message.bot.supplement_log_choice = {}

    message.bot.supplement_log_choice[user_id] = target.get("name", "")
    message.bot.expecting_supplement_log = False
    message.bot.viewing_supplement_details = False

    start_date_selection(message.bot, "supplement_log")
    await answer_with_menu(
        message,
        get_date_prompt("supplement_log"),
        reply_markup=training_date_menu,
    )


@dp.message(F.text == "📅 Календарь добавок")
async def supplements_history(message: Message):
    # Сбрасываем флаги выбора добавки, если они были установлены
    if getattr(message.bot, "choosing_supplement_for_view", False):
        message.bot.choosing_supplement_for_view = False
    if getattr(message.bot, "choosing_supplement_for_edit", False):
        message.bot.choosing_supplement_for_edit = False
    if getattr(message.bot, "expecting_supplement_history_choice", False):
        message.bot.expecting_supplement_history_choice = False
    
    supplements_list = get_user_supplements(message)
    if not supplements_list:
        await answer_with_menu(
            message,
            "Календарь добавок пока пуст. Сначала создай добавку, чтобы отмечать приёмы.",
            reply_markup=supplements_main_menu(False),
        )
        return
    user_id = str(message.from_user.id)
    await show_supplement_calendar(message, user_id)


def supplement_schedule_prompt(sup: dict) -> str:
    times = ", ".join(sup["times"]) if sup["times"] else "не выбрано"
    days = ", ".join(sup["days"]) if sup["days"] else "не выбрано"
    notifications_status = "включены" if sup.get("notifications_enabled", True) else "выключены"
    return (
        f"💊 {sup['name']}\n\n"
        f"⏰ Время приема: {times}\n"
        f"📅 Дни приема: {days}\n"
        f"⏳ Длительность: {sup['duration']}\n"
        f"🔔 Уведомления: {notifications_status}\n\n"
        "ℹ️ Можно сохранить добавку в любой момент"
    )


def supplement_edit_menu(show_save: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="✏️ Редактировать время"), KeyboardButton(text="📅 Редактировать дни")],
        [KeyboardButton(text="⏳ Длительность приема"), KeyboardButton(text="✏️ Изменить название")],
        [KeyboardButton(text="🔔 Уведомления")],
    ]
    if show_save:
        buttons.append([KeyboardButton(text="💾 Сохранить")])
    buttons.append([KeyboardButton(text="⬅️ Отменить")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def time_edit_menu(times: list[str]) -> ReplyKeyboardMarkup:
    buttons: list[list[KeyboardButton]] = []
    for t in times:
        buttons.append([KeyboardButton(text=f"❌ {t}")])
    buttons.append([KeyboardButton(text="➕ Добавить"), KeyboardButton(text="💾 Сохранить")])
    buttons.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def time_first_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="➕ Добавить"), KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
    )


def days_menu(selected: list[str]) -> ReplyKeyboardMarkup:
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    rows = []
    for day in week_days:
        prefix = "✅ " if day in selected else ""
        rows.append([KeyboardButton(text=f"{prefix}{day}")])
    rows.append([KeyboardButton(text="Выбрать все"), KeyboardButton(text="💾 Сохранить")])
    rows.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def duration_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Постоянно"), KeyboardButton(text="14 дней")],
            [KeyboardButton(text="30 дней")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def build_meals_actions_keyboard(
    meals: list[Meal], target_date: date, *, include_back: bool = False
) -> InlineKeyboardMarkup:
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


def format_today_meals(meals, daily_totals, day_str: str) -> str:
    lines: list[str] = []
    lines.append(f"Приём пищи за {day_str}:\n")

    for idx, meal in enumerate(meals, start=1):
        # что вводил пользователь
        user_text = getattr(meal, "raw_query", None) or meal.description or "Без описания"

        # 👉 заголовок "Ты ввёл(а):" жирным через HTML
        lines.append(f"{idx}) 📝 <b>Ты ввёл(а):</b> {html.escape(user_text)}")

        api_details = getattr(meal, "api_details", None)

        if api_details:
            # 👉 "Результат:" жирным
            lines.append("🔍 <b>Результат:</b>")
            # тут api_details уже готовый текст, не экранируем
            lines.append(api_details)
        else:
            # что мы показывали раньше как распознанный текст
            api_text_fallback = meal.description or "нет описания"

            # пробуем достать продукты из JSON (на случай старых записей)
            products = []
            raw_products = getattr(meal, "products_json", None)
            if raw_products:
                try:
                    products = json.loads(raw_products)
                except Exception as e:
                    print("⚠️ Не смог распарсить products_json:", repr(e))

            if products:
                lines.append("🔍 <b>Результат:</b>")
                for p in products:
                    name = p.get("name_ru") or p.get("name") or "продукт"
                    cal = p.get("calories") or p.get("_calories") or 0
                    prot = p.get("protein_g") or p.get("_protein_g") or 0
                    fat = p.get("fat_total_g") or p.get("_fat_total_g") or 0
                    carb = p.get("carbohydrates_total_g") or p.get("_carbohydrates_total_g") or 0

                    lines.append(
                        f"• {html.escape(name)} — {cal:.0f} ккал "
                        f"(Б {prot:.1f} / Ж {fat:.1f} / У {carb:.1f})"
                    )
            else:
                # старый вариант без products_json
                lines.append(
                    f"🔍 <b>Результат:</b> {html.escape(api_text_fallback)}"
                )

        # Итого по этому приёму
        lines.append(f"🔥 Калории: {meal.calories:.0f} ккал")
        lines.append(f"💪 Белки: {meal.protein:.1f} г")
        lines.append(f"🥑 Жиры: {meal.fat:.1f} г")
        lines.append(f"🍩 Углеводы: {meal.carbs:.1f} г")
        lines.append("— — — — —")

    # 👉 Итоги за день — тоже жирным
    lines.append("\n<b>Итого за день:</b>")
    lines.append(f"🔥 Калории: {daily_totals['calories']:.0f} ккал")
    lines.append(f"💪 Белки: {daily_totals['protein_g']:.1f} г")
    lines.append(f"🥑 Жиры: {daily_totals['fat_total_g']:.1f} г")
    lines.append(f"🍩 Углеводы: {daily_totals['carbohydrates_total_g']:.1f} г")

    return "\n".join(lines)






async def send_today_results(message: Message, user_id: str):
    today = date.today()
    meals = get_meals_for_date(user_id, today)

    if not meals:
        await answer_with_menu(
            message,
            "Пока нет записей за сегодня. Добавь приём пищи, и я посчитаю КБЖУ!",
            reply_markup=kbju_menu,
        )
        return

    daily_totals = get_daily_meal_totals(user_id, today)
    day_str = today.strftime("%d.%m.%Y")
    text = format_today_meals(meals, daily_totals, day_str)
    keyboard = build_meals_actions_keyboard(meals, today)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(F.text == "🍱 КБЖУ")
async def calories(message: Message):
    # Сбрасываем флаги выбора добавки, если они были установлены
    if getattr(message.bot, "choosing_supplement_for_view", False):
        message.bot.choosing_supplement_for_view = False
    if getattr(message.bot, "choosing_supplement_for_edit", False):
        message.bot.choosing_supplement_for_edit = False
    if getattr(message.bot, "expecting_supplement_history_choice", False):
        message.bot.expecting_supplement_history_choice = False
    
    reset_user_state(message, keep_supplements=True)
    user_id = str(message.from_user.id)

    settings = get_kbju_settings(user_id)

    # если норма ещё не настроена — предлагаем тест / ручной ввод / пропустить
    if not settings:
        message.bot.awaiting_kbju_choice = True
        await answer_with_menu(
            message,
            "🍱 Раздел КБЖУ\n\n"
            "Давай один раз настроим твою дневную норму КБЖУ — так я смогу не просто считать калории, "
            "а сравнивать их с твоей целью.\n\n"
            "Выбери вариант:",
            reply_markup=kbju_intro_menu,
        )
        return

    # если норма уже есть — просто открываем меню КБЖУ
    message.bot.kbju_menu_open = True
    progress_text = format_progress_block(user_id)
    await answer_with_menu(
        message,
        f"🍱 Раздел КБЖУ\n\n{progress_text}\n\nВыбери действие:",
        reply_markup=kbju_menu,
        parse_mode="HTML",
    )

@dp.message(lambda m: getattr(m.bot, "awaiting_kbju_choice", False))
async def kbju_intro_choice(message: Message):
    user_id = str(message.from_user.id)
    choice = message.text.strip()

    if choice == "✅ Пройти быстрый тест КБЖУ":
        message.bot.awaiting_kbju_choice = False
        clear_kbju_test_session(message.bot, user_id)
        session = get_kbju_test_session(message.bot, user_id)
        message.bot.kbju_test_step = "gender"

        await answer_with_menu(
            message,
            "Окей, пройдём небольшой тест 💪\n\n"
            "Для начала — укажи пол:",
            reply_markup=kbju_gender_menu,
        )
        return

    if choice == "✏️ Ввести свою норму":
        message.bot.awaiting_kbju_choice = False
        message.bot.expecting_kbju_manual_norm = True
        await answer_with_menu(
            message,
            "Напиши свою дневную норму в формате, например:\n\n"
            "<code>2000 ккал, Б 140, Ж 70, У 220</code>\n\n"
            "Я просто возьму первые четыре числа: калории, белки, жиры, углеводы.",
            reply_markup=kbju_menu,
        )
        return

    if choice == "➡️ Пока без цели":
        message.bot.awaiting_kbju_choice = False
        message.bot.kbju_menu_open = True
        await answer_with_menu(
            message,
            "Ок, буду просто считать КБЖУ без цели 🎯\n\nВыбери действие:",
            reply_markup=kbju_menu,
        )
        return

    await message.answer("Пожалуйста, выбери вариант из кнопок ниже 😊")


async def start_kbju_add_flow(message: Message, entry_date: date):
    user_id = str(message.from_user.id)

    message.bot.kbju_menu_open = True
    message.bot.expecting_food_input = False
    message.bot.expecting_ai_food_input = False
    message.bot.expecting_photo_input = False
    message.bot.expecting_label_photo_input = False
    message.bot.expecting_barcode_photo_input = False

    if not hasattr(message.bot, "meal_entry_dates"):
        message.bot.meal_entry_dates = {}
    message.bot.meal_entry_dates[user_id] = entry_date

    text = (
        "🍱 Раздел КБЖУ\n\n"
        "Выбери, как добавить приём пищи:\n"
        "• 📝 Ввести приём пищи (анализ ИИ) — умный анализ на основе типичных значений (рекомендуется)\n"
        "• 📷 Анализ еды по фото — отправь фото еды\n"
        "• 📋 Анализ этикетки — отправь фото этикетки/упаковки\n"
        "• 📷 Скан штрих-кода — отправь фото штрих-кода\n"
        "• ➕ Через CalorieNinjas — альтернативный вариант"
    )

    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_add_menu,
    )



@dp.message(lambda m: m.text == "🎯 Цель / Норма КБЖУ" and getattr(m.bot, "kbju_menu_open", False))
async def kbju_goal_menu_entry(message: Message):
    reset_user_state(message, keep_supplements=True)
    user_id = str(message.from_user.id)
    message.bot.kbju_menu_open = True
    message.bot.awaiting_kbju_goal_edit = False

    settings = get_kbju_settings(user_id)

    if settings:
        message.bot.awaiting_kbju_choice = False
        message.bot.awaiting_kbju_goal_edit = True
        text = format_current_kbju_goal(settings)
        await answer_with_menu(
            message,
            text,
            parse_mode="HTML",
            reply_markup=kbju_goal_view_menu,
        )
        return
    else:
        message.bot.awaiting_kbju_choice = True
        await answer_with_menu(
            message,
            "🍱 Раздел КБЖУ\n\n",
            "Давай один раз настроим твою дневную норму КБЖУ — так я смогу не просто считать калории, ",
            "а сравнивать их с твоей целью.\n\n",
            "Выбери вариант:",
            reply_markup=kbju_intro_menu,
        )
        return


@dp.message(
    lambda m: m.text == "✏️ Редактировать" and getattr(m.bot, "awaiting_kbju_goal_edit", False)
)
async def kbju_goal_edit(message: Message):
    reset_user_state(message, keep_supplements=True)
    user_id = str(message.from_user.id)
    message.bot.kbju_menu_open = True
    message.bot.awaiting_kbju_choice = True

    settings = get_kbju_settings(user_id)
    intro_text = (
        "🍱 Раздел КБЖУ\n\n"
        "Можно пересчитать норму через тест или задать свои числа вручную.\n\n"
        "Что выбираешь?"
    )

    if not settings:
        await kbju_goal_menu_entry(message)
        return

    await answer_with_menu(
        message,
        intro_text,
        reply_markup=kbju_intro_menu,
    )



@dp.message(lambda m: m.text == "➕ Добавить" and getattr(m.bot, "kbju_menu_open", False))
async def calories_add(message: Message):
    reset_user_state(message)
    await start_kbju_add_flow(message, date.today())


@dp.message(lambda m: m.text == "📊 Дневной отчёт" and getattr(m.bot, "kbju_menu_open", False))
async def calories_today_results(message: Message):
    reset_user_state(message)
    message.bot.kbju_menu_open = True
    await send_today_results(message, str(message.from_user.id))


@dp.message(lambda m: m.text == "➕ Через CalorieNinjas" and getattr(m.bot, "kbju_menu_open", False))
async def kbju_add_via_calorieninjas(message: Message):
    message.bot.expecting_food_input = True
    message.bot.expecting_ai_food_input = False

    text = (
        "Напиши, что ты съел(а) одним сообщением.\n\n"
        "Например:\n"
        "• 100 г овсянки, 2 яйца, 1 банан\n"
        "• 150 г куриной грудки и 200 г риса\n\n"
        "Важно: сначала указывай количество (например: 100 г или 2 шт), "
        "а после — сам продукт."
    )

    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_add_menu,
    )


@dp.message(lambda m: m.text == "📝 Ввести приём пищи (анализ ИИ)" and getattr(m.bot, "kbju_menu_open", False))
async def kbju_add_via_ai(message: Message):
    message.bot.expecting_food_input = False
    message.bot.expecting_ai_food_input = True

    text = (
        "📝 Ввести приём пищи (анализ ИИ)\n\n"
        "Напиши, что ты съел, с примерным весом в одном сообщении.\n\n"
        "Например: 200 г курицы, 100 г йогурта, 30 г орехов.\n\n"
        "ИИ автоматически определит КБЖУ на основе типичных значений продуктов."
    )

    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_add_menu,
    )


@dp.message(lambda m: m.text == "📷 Анализ еды по фото" and getattr(m.bot, "kbju_menu_open", False))
async def kbju_add_via_photo(message: Message):
    """Обработчик кнопки анализа еды по фото"""
    reset_user_state(message)
    message.bot.kbju_menu_open = True
    message.bot.expecting_food_input = False
    message.bot.expecting_ai_food_input = False
    message.bot.expecting_photo_input = True
    
    text = (
        "📷 Анализ еды по фото\n\n"
        "Отправь мне фото еды, и я определю КБЖУ с помощью ИИ! 🤖\n\n"
        "Сделай фото так, чтобы еда была хорошо видна на изображении."
    )
    
    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_add_menu,
    )


@dp.message(lambda m: m.text == "📋 Анализ этикетки" and getattr(m.bot, "kbju_menu_open", False))
async def kbju_add_via_label(message: Message):
    """Обработчик кнопки анализа этикетки"""
    reset_user_state(message)
    message.bot.kbju_menu_open = True
    message.bot.expecting_food_input = False
    message.bot.expecting_ai_food_input = False
    message.bot.expecting_photo_input = False
    message.bot.expecting_label_photo_input = True
    
    text = (
        "📋 Анализ этикетки/упаковки\n\n"
        "Отправь мне фото этикетки или упаковки продукта, и я найду КБЖУ в тексте! 📸\n\n"
        "Я прочитаю информацию о пищевой ценности и извлеку точные данные о калориях, белках, жирах и углеводах.\n\n"
        "Если на этикетке указан вес упаковки — использую его автоматически. "
        "Если нет — спрошу у тебя, сколько грамм ты съел(а)."
    )
    
    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_add_menu,
    )


@dp.message(lambda m: m.text == "📷 Скан штрих-кода" and getattr(m.bot, "kbju_menu_open", False))
async def kbju_add_via_barcode(message: Message):
    """Обработчик кнопки сканирования штрих-кода"""
    reset_user_state(message)
    message.bot.kbju_menu_open = True
    message.bot.expecting_food_input = False
    message.bot.expecting_ai_food_input = False
    message.bot.expecting_photo_input = False
    message.bot.expecting_label_photo_input = False
    message.bot.expecting_barcode_photo_input = True
    
    text = (
        "📷 Сканирование штрих-кода\n\n"
        "Отправь мне фото штрих-кода продукта, и я найду информацию о нём в базе Open Food Facts! 📸\n\n"
        "Я распознаю штрих-код с помощью ИИ и получу точные данные о продукте: название, КБЖУ и другие факты."
    )
    
    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_add_menu,
    )


@dp.message(lambda m: m.text == "📆 Календарь КБЖУ" and getattr(m.bot, "kbju_menu_open", False))
async def calories_calendar(message: Message):
    reset_user_state(message)
    message.bot.kbju_menu_open = True
    await show_kbju_calendar(message, str(message.from_user.id))


@dp.message(lambda m: getattr(m.bot, "expecting_kbju_manual_norm", False))
async def kbju_manual_norm_input(message: Message):
    user_id = str(message.from_user.id)
    text = message.text

    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    if len(numbers) < 4:
        await message.answer(
            "Мне нужно хотя бы четыре числа: калории, белки, жиры, углеводы.\n\n"
            "Пример: <code>2000 ккал, Б 140, Ж 70, У 220</code>"
        )
        return

    calories, protein, fat, carbs = [float(n.replace(",", ".")) for n in numbers[:4]]

    save_kbju_settings(user_id, calories, protein, fat, carbs, goal=None, activity=None)
    message.bot.expecting_kbju_manual_norm = False

    text = format_kbju_goal_text(calories, protein, fat, carbs, goal_label="Своя норма")
    message.bot.kbju_menu_open = True
    await message.answer(text, parse_mode="HTML")
    await message.answer("Теперь можешь пользоваться разделом КБЖУ 👇", reply_markup=kbju_menu)


@dp.message(lambda m: getattr(m.bot, "expecting_ai_food_input", False))
async def kbju_ai_process(message: Message):
    global last_gemini_error
    
    user_id = str(message.from_user.id)
    food_text = (message.text or "").strip()

    if not food_text:
        await message.answer("Напиши продукты одной строкой, например: 200 г курицы, 100 г йогурта")
        return

    entry_date = getattr(message.bot, "meal_entry_dates", {}).get(user_id, date.today())

    await message.answer("Считаю КБЖУ с помощью ИИ, секунду... 🤖")

    data = gemini_estimate_kbju(food_text)

    if not data:
        # Проверяем, была ли ошибка связана с превышением квоты
        if last_gemini_error.get("is_quota_exceeded", False):
            await message.answer(
                "⚠️ Превышен дневной лимит запросов к ИИ 😔\n\n"
                "Бесплатный тариф Gemini API позволяет только 20 запросов в день.\n"
                "Лимит будет сброшен через 24 часа.\n\n"
                "Попробуй использовать другие способы добавления КБЖУ:\n"
                "• 📋 Фото этикетки\n"
                "• 📷 Сканирование штрих-кода\n"
                "• ✏️ Ручной ввод"
            )
        else:
            await message.answer(
                "Не удалось оценить КБЖУ через ИИ 😔\n"
                "Попробуй переформулировать описание или отправь фото еды."
            )
        message.bot.expecting_ai_food_input = False
        if hasattr(message.bot, "meal_entry_dates"):
            message.bot.meal_entry_dates.pop(user_id, None)
        return

    items = data.get("items") or []
    total = data.get("total") or {}

    def safe_float(value) -> float:
        try:
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    totals_for_db = {
        "calories": safe_float(total.get("kcal")),
        "protein_g": safe_float(total.get("protein")),
        "fat_total_g": safe_float(total.get("fat")),
        "carbohydrates_total_g": safe_float(total.get("carbs")),
        "products": [],
    }

    lines = ["🤖 Оценка по ИИ для этого приёма пищи:\n"]
    api_details_lines: list[str] = []

    for item in items:
        name = item.get("name") or "продукт"
        grams = safe_float(item.get("grams"))
        cal = safe_float(item.get("kcal"))
        p = safe_float(item.get("protein"))
        f = safe_float(item.get("fat"))
        c = safe_float(item.get("carbs"))

        lines.append(
            f"• {name} ({grams:.0f} г) — {cal:.0f} ккал (Б {p:.1f} / Ж {f:.1f} / У {c:.1f})"
        )
        api_details_lines.append(
            f"• {name} ({grams:.0f} г) — {cal:.0f} ккал (Б {p:.1f} / Ж {f:.1f} / У {c:.1f})"
        )

        # Вычисляем КБЖУ на 100г для удобного пересчета при редактировании
        calories_per_100g = (cal / grams) * 100 if grams > 0 else 0
        protein_per_100g = (p / grams) * 100 if grams > 0 else 0
        fat_per_100g = (f / grams) * 100 if grams > 0 else 0
        carbs_per_100g = (c / grams) * 100 if grams > 0 else 0
        
        totals_for_db["products"].append(
            {
                "name": name,
                "grams": grams,
                "calories": cal,
                "protein_g": p,
                "fat_total_g": f,
                "carbohydrates_total_g": c,
                "calories_per_100g": calories_per_100g,
                "protein_per_100g": protein_per_100g,
                "fat_per_100g": fat_per_100g,
                "carbs_per_100g": carbs_per_100g,
            }
        )

    lines.append("\nИТОГО:")
    lines.append(
        f"🔥 Калории: {totals_for_db['calories']:.0f} ккал\n"
        f"💪 Белки: {totals_for_db['protein_g']:.1f} г\n"
        f"🥑 Жиры: {totals_for_db['fat_total_g']:.1f} г\n"
        f"🍩 Углеводы: {totals_for_db['carbohydrates_total_g']:.1f} г"
    )

    api_details = "\n".join(api_details_lines) if api_details_lines else None

    save_meal_entry(
        user_id=user_id,
        raw_query=food_text,
        totals=totals_for_db,
        entry_date=entry_date,
        api_details=api_details,
    )

    daily_totals = get_daily_meal_totals(user_id, entry_date)

    lines.append("\nСУММА ЗА СЕГОДНЯ:")
    lines.append(
        f"🔥 Калории: {daily_totals['calories']:.0f} ккал\n"
        f"💪 Белки: {daily_totals['protein_g']:.1f} г\n"
        f"🥑 Жиры: {daily_totals['fat_total_g']:.1f} г\n"
        f"🍩 Углеводы: {daily_totals['carbohydrates_total_g']:.1f} г"
    )


    message.bot.expecting_ai_food_input = False
    if hasattr(message.bot, "meal_entry_dates"):
        message.bot.meal_entry_dates.pop(user_id, None)

    await answer_with_menu(
        message,
        "\n".join(lines),
        reply_markup=kbju_after_meal_menu,
    )


@dp.message(lambda m: getattr(m.bot, "expecting_photo_input", False) and m.photo is not None)
async def kbju_photo_process(message: Message):
    """Обработчик анализа еды по фото"""
    global last_gemini_error
    
    user_id = str(message.from_user.id)
    entry_date = getattr(message.bot, "meal_entry_dates", {}).get(user_id, date.today())

    # Получаем фото наибольшего размера
    photo = message.photo[-1]  # последний элемент - самое большое фото
    
    await message.answer("📷 Анализирую фото с помощью ИИ, секунду... 🤖")
    
    try:
        # Скачиваем фото
        file_info = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file_info.file_path)
        image_data = image_bytes.read()
        
        # Анализируем фото через Gemini
        data = gemini_estimate_kbju_from_photo(image_data)
        
        if not data:
            # Проверяем, была ли ошибка связана с превышением квоты
            if last_gemini_error.get("is_quota_exceeded", False):
                await message.answer(
                    "⚠️ Превышен дневной лимит запросов к ИИ 😔\n\n"
                    "Бесплатный тариф Gemini API позволяет только 20 запросов в день.\n"
                    "Лимит будет сброшен через 24 часа.\n\n"
                    "Попробуй использовать другие способы добавления КБЖУ:\n"
                    "• 📋 Фото этикетки\n"
                    "• 📷 Сканирование штрих-кода\n"
                    "• ✏️ Ручной ввод"
                )
            else:
                await message.answer(
                    "Не удалось проанализировать фото 😔\n"
                    "Попробуй сделать фото ещё раз, убедись что еда хорошо видна, "
                    "или используй другие способы добавления КБЖУ."
                )
            message.bot.expecting_photo_input = False
            if hasattr(message.bot, "meal_entry_dates"):
                message.bot.meal_entry_dates.pop(user_id, None)
            return

        items = data.get("items") or []
        total = data.get("total") or {}

        def safe_float(value) -> float:
            try:
                if value is None:
                    return 0.0
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        totals_for_db = {
            "calories": safe_float(total.get("kcal")),
            "protein_g": safe_float(total.get("protein")),
            "fat_total_g": safe_float(total.get("fat")),
            "carbohydrates_total_g": safe_float(total.get("carbs")),
            "products": [],
        }

        lines = ["📷 Анализ фото еды (ИИ):\n"]
        api_details_lines: list[str] = []

        for item in items:
            name = item.get("name") or "продукт"
            grams = safe_float(item.get("grams"))
            cal = safe_float(item.get("kcal"))
            p = safe_float(item.get("protein"))
            f = safe_float(item.get("fat"))
            c = safe_float(item.get("carbs"))

            lines.append(
                f"• {name} ({grams:.0f} г) — {cal:.0f} ккал (Б {p:.1f} / Ж {f:.1f} / У {c:.1f})"
            )
            api_details_lines.append(
                f"• {name} ({grams:.0f} г) — {cal:.0f} ккал (Б {p:.1f} / Ж {f:.1f} / У {c:.1f})"
            )

            totals_for_db["products"].append(
                {
                    "name": name,
                    "grams": grams,
                    "calories": cal,
                    "protein_g": p,
                    "fat_total_g": f,
                    "carbohydrates_total_g": c,
                }
            )

        lines.append("\nИТОГО:")
        lines.append(
            f"🔥 Калории: {totals_for_db['calories']:.0f} ккал\n"
            f"💪 Белки: {totals_for_db['protein_g']:.1f} г\n"
            f"🥑 Жиры: {totals_for_db['fat_total_g']:.1f} г\n"
            f"🍩 Углеводы: {totals_for_db['carbohydrates_total_g']:.1f} г"
        )

        api_details = "\n".join(api_details_lines) if api_details_lines else None

        save_meal_entry(
            user_id=user_id,
            raw_query="[Анализ по фото]",
            totals=totals_for_db,
            entry_date=entry_date,
            api_details=api_details,
        )

        daily_totals = get_daily_meal_totals(user_id, entry_date)

        lines.append("\nСУММА ЗА СЕГОДНЯ:")
        lines.append(
            f"🔥 Калории: {daily_totals['calories']:.0f} ккал\n"
            f"💪 Белки: {daily_totals['protein_g']:.1f} г\n"
            f"🥑 Жиры: {daily_totals['fat_total_g']:.1f} г\n"
            f"🍩 Углеводы: {daily_totals['carbohydrates_total_g']:.1f} г"
        )


        message.bot.expecting_photo_input = False
        if hasattr(message.bot, "meal_entry_dates"):
            message.bot.meal_entry_dates.pop(user_id, None)

        await answer_with_menu(
            message,
            "\n".join(lines),
            reply_markup=kbju_after_meal_menu,
        )
        
    except Exception as e:
        print("❌ Ошибка при обработке фото:", repr(e))
        await message.answer(
            "Произошла ошибка при обработке фото 😔\n"
            "Попробуй отправить фото ещё раз или используй другие способы добавления КБЖУ."
        )
        message.bot.expecting_photo_input = False
        if hasattr(message.bot, "meal_entry_dates"):
            message.bot.meal_entry_dates.pop(user_id, None)


@dp.message(lambda m: getattr(m.bot, "expecting_photo_input", False) and m.photo is None)
async def kbju_photo_expected_but_text_received(message: Message):
    """Обработчик случая, когда ожидается фото, но получен текст"""
    await message.answer(
        "📷 Я ожидаю фото еды для анализа!\n\n"
        "Пожалуйста, отправь фото еды, которую хочешь проанализировать. "
        "Убедись, что еда хорошо видна на изображении.\n\n"
        "Если хочешь добавить КБЖУ другим способом, используй кнопки меню."
    )


@dp.message(lambda m: getattr(m.bot, "expecting_label_photo_input", False) and m.photo is not None)
async def kbju_label_photo_process(message: Message):
    """Обработчик анализа этикетки по фото"""
    global last_gemini_error
    
    user_id = str(message.from_user.id)
    entry_date = getattr(message.bot, "meal_entry_dates", {}).get(user_id, date.today())

    photo = message.photo[-1]
    
    await message.answer("📋 Анализирую этикетку с помощью ИИ, секунду... 🤖")
    
    try:
        file_info = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file_info.file_path)
        image_data = image_bytes.read()
        
        data = gemini_extract_kbju_from_label(image_data)
        
        if not data or not data.get("kbju_per_100g"):
            # Проверяем, была ли ошибка связана с превышением квоты
            if last_gemini_error.get("is_quota_exceeded", False):
                await message.answer(
                    "⚠️ Превышен дневной лимит запросов к ИИ 😔\n\n"
                    "Бесплатный тариф Gemini API позволяет только 20 запросов в день.\n"
                    "Лимит будет сброшен через 24 часа.\n\n"
                    "Попробуй использовать другие способы добавления КБЖУ:\n"
                    "• 📷 Сканирование штрих-кода\n"
                    "• ✏️ Ручной ввод"
                )
            else:
                await message.answer(
                    "Не удалось найти КБЖУ на этикетке 😔\n"
                    "Убедись, что фото этикетки/упаковки чёткое и видна таблица пищевой ценности.\n\n"
                    "Попробуй отправить фото ещё раз или используй другие способы добавления КБЖУ."
                )
            # Оставляем флаг активным, чтобы пользователь мог отправить новое фото
            # message.bot.expecting_label_photo_input остается True
            return

        kbju_100g = data.get("kbju_per_100g", {})
        package_weight = data.get("package_weight")
        found_weight = data.get("found_weight", False)
        product_name = data.get("product_name", "Продукт")

        def safe_float(value) -> float:
            try:
                if value is None:
                    return 0.0
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        kcal_100g = safe_float(kbju_100g.get("kcal"))
        protein_100g = safe_float(kbju_100g.get("protein"))
        fat_100g = safe_float(kbju_100g.get("fat"))
        carbs_100g = safe_float(kbju_100g.get("carbs"))

        # Всегда спрашиваем у пользователя, сколько он съел
        message.bot.expecting_label_photo_input = False
        message.bot.expecting_label_weight_input = True
        # Сохраняем данные КБЖУ на 100г для пересчёта (используем тот же кэш, что и для этикетки)
        if not hasattr(message.bot, "label_kbju_cache"):
            message.bot.label_kbju_cache = {}
        message.bot.label_kbju_cache[user_id] = {
            "kcal_100g": kcal_100g,
            "protein_100g": protein_100g,
            "fat_100g": fat_100g,
            "carbs_100g": carbs_100g,
            "product_name": product_name,
            "entry_date": entry_date,
            "source": "label",  # Указываем источник - этикетка
        }

        # Формируем сообщение в зависимости от того, найден ли вес
        if found_weight and package_weight is not None:
            weight = safe_float(package_weight)
            if weight > 0:
                await message.answer(
                    f"✅ Нашёл КБЖУ на этикетке!\n\n"
                    f"📦 Продукт: {product_name}\n"
                    f"📊 КБЖУ на 100 г:\n"
                    f"🔥 Калории: {kcal_100g:.0f} ккал\n"
                    f"💪 Белки: {protein_100g:.1f} г\n"
                    f"🥑 Жиры: {fat_100g:.1f} г\n"
                    f"🍩 Углеводы: {carbs_100g:.1f} г\n\n"
                    f"📦 В упаковке {weight:.0f} г, сколько Вы съели?"
                )
            else:
                await message.answer(
                    f"✅ Нашёл КБЖУ на этикетке!\n\n"
                    f"📦 Продукт: {product_name}\n"
                    f"📊 КБЖУ на 100 г:\n"
                    f"🔥 Калории: {kcal_100g:.0f} ккал\n"
                    f"💪 Белки: {protein_100g:.1f} г\n"
                    f"🥑 Жиры: {fat_100g:.1f} г\n"
                    f"🍩 Углеводы: {carbs_100g:.1f} г\n\n"
                    f"❓ Вес в упаковке не найден, сколько вы съели?"
                )
        else:
            await message.answer(
                f"✅ Нашёл КБЖУ на этикетке!\n\n"
                f"📦 Продукт: {product_name}\n"
                f"📊 КБЖУ на 100 г:\n"
                f"🔥 Калории: {kcal_100g:.0f} ккал\n"
                f"💪 Белки: {protein_100g:.1f} г\n"
                f"🥑 Жиры: {fat_100g:.1f} г\n"
                f"🍩 Углеводы: {carbs_100g:.1f} г\n\n"
                f"❓ Вес в упаковке не найден, сколько вы съели?"
            )
        
    except Exception as e:
        print("❌ Ошибка при обработке фото этикетки:", repr(e))
        await message.answer(
            "Произошла ошибка при обработке фото этикетки 😔\n"
            "Попробуй отправить фото ещё раз или используй другие способы добавления КБЖУ."
        )
        # Оставляем флаг активным, чтобы пользователь мог отправить новое фото
        # message.bot.expecting_label_photo_input остается True


@dp.message(lambda m: getattr(m.bot, "expecting_label_photo_input", False) and m.photo is None)
async def kbju_label_photo_expected_but_text_received(message: Message):
    """Обработчик случая, когда ожидается фото этикетки, но получен текст"""
    await message.answer(
        "📋 Я ожидаю фото этикетки или упаковки продукта!\n\n"
        "Пожалуйста, отправь фото этикетки, где видна таблица пищевой ценности. "
        "Убедись, что текст хорошо читается.\n\n"
        "Если хочешь добавить КБЖУ другим способом, используй кнопки меню."
    )


@dp.message(lambda m: getattr(m.bot, "expecting_barcode_photo_input", False) and m.photo is not None)
async def kbju_barcode_photo_process(message: Message):
    """Обработчик сканирования штрих-кода"""
    user_id = str(message.from_user.id)
    entry_date = getattr(message.bot, "meal_entry_dates", {}).get(user_id, date.today())

    photo = message.photo[-1]
    
    await message.answer("📷 Распознаю штрих-код, секунду... 🤖")
    
    try:
        # Скачиваем фото
        file_info = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file_info.file_path)
        image_data = image_bytes.read()
        
        # Распознаём штрих-код через Gemini
        barcode = gemini_scan_barcode(image_data)
        
        if not barcode:
            await message.answer(
                "Не удалось распознать штрих-код на фото 😔\n\n"
                "Попробуй сделать фото ещё раз:\n"
                "• Убедись, что штрих-код хорошо виден\n"
                "• Сделай фото при хорошем освещении\n"
                "• Штрих-код должен быть в фокусе\n\n"
                "Или используй другие способы добавления КБЖУ."
            )
            # Оставляем флаг активным для повторной попытки
            return
        
        await message.answer(f"✅ Штрих-код распознан: {barcode}\n\n🔍 Ищу информацию о продукте...")
        
        # Получаем данные из Open Food Facts
        product_data = get_product_from_openfoodfacts(barcode)
        
        if not product_data:
            await message.answer(
                f"❌ Продукт со штрих-кодом {barcode} не найден в базе Open Food Facts.\n\n"
                "Попробуй другой способ добавления КБЖУ или используй фото этикетки."
            )
            message.bot.expecting_barcode_photo_input = False
            if hasattr(message.bot, "meal_entry_dates"):
                message.bot.meal_entry_dates.pop(user_id, None)
            return
        
        # Формируем информацию о продукте
        product_name = product_data.get("name", "Неизвестный продукт")
        brand = product_data.get("brand", "")
        nutriments = product_data.get("nutriments", {})
        weight = product_data.get("weight")
        
        def safe_float(value) -> float:
            try:
                if value is None:
                    return 0.0
                return float(value)
            except (TypeError, ValueError):
                return 0.0
        
        # КБЖУ на 100г
        kcal_100g = safe_float(nutriments.get("kcal", 0))
        protein_100g = safe_float(nutriments.get("protein", 0))
        fat_100g = safe_float(nutriments.get("fat", 0))
        carbs_100g = safe_float(nutriments.get("carbs", 0))
        
        # Проверяем, есть ли хотя бы какое-то КБЖУ
        if not (kcal_100g or protein_100g or fat_100g or carbs_100g):
            await message.answer(
                f"❌ В базе Open Food Facts нет информации о КБЖУ для продукта со штрих-кодом {barcode}.\n\n"
                "Попробуй использовать фото этикетки или другие способы добавления КБЖУ."
            )
            message.bot.expecting_barcode_photo_input = False
            if hasattr(message.bot, "meal_entry_dates"):
                message.bot.meal_entry_dates.pop(user_id, None)
            return
        
        # Всегда показываем КБЖУ на 100г и спрашиваем вес (как при анализе этикетки)
        message.bot.expecting_barcode_photo_input = False
        message.bot.expecting_label_weight_input = True
        
        # Сохраняем данные КБЖУ на 100г для пересчёта (используем тот же кэш, что и для этикетки)
        if not hasattr(message.bot, "label_kbju_cache"):
            message.bot.label_kbju_cache = {}
        message.bot.label_kbju_cache[user_id] = {
            "kcal_100g": kcal_100g,
            "protein_100g": protein_100g,
            "fat_100g": fat_100g,
            "carbs_100g": carbs_100g,
            "product_name": product_name,
            "entry_date": entry_date,
            "source": "barcode",  # Указываем источник - штрих-код
            "barcode": barcode  # Сохраняем штрих-код для raw_query
        }
        
        # Формируем сообщение с информацией о продукте
        text_parts = [f"✅ Нашёл продукт в базе Open Food Facts!\n\n"]
        text_parts.append(f"📦 Продукт: <b>{product_name}</b>\n")
        
        if brand:
            text_parts.append(f"🏷 Бренд: {brand}\n")
        
        text_parts.append(f"🔢 Штрих-код: {barcode}\n")
        text_parts.append(f"\n📊 КБЖУ на 100 г:\n")
        text_parts.append(f"🔥 Калории: {kcal_100g:.0f} ккал\n")
        text_parts.append(f"💪 Белки: {protein_100g:.1f} г\n")
        text_parts.append(f"🥑 Жиры: {fat_100g:.1f} г\n")
        text_parts.append(f"🍩 Углеводы: {carbs_100g:.1f} г\n")
        
        # Если есть вес упаковки в базе, упоминаем его, но все равно спрашиваем
        if weight:
            text_parts.append(f"\n📦 В базе указан вес упаковки: {weight} г\n")
            text_parts.append(f"Сколько грамм вы съели? (можно ввести {weight} или другое значение)")
        else:
            text_parts.append(f"\n❓ Сколько грамм вы съели?")
        
        await answer_with_menu(
            message,
            "".join(text_parts),
            reply_markup=kbju_add_menu,
        )
        
    except Exception as e:
        print("❌ Ошибка при обработке фото штрих-кода:", repr(e))
        await message.answer(
            "Произошла ошибка при обработке фото штрих-кода 😔\n"
            "Попробуй отправить фото ещё раз или используй другие способы добавления КБЖУ."
        )
        message.bot.expecting_barcode_photo_input = False
        if hasattr(message.bot, "meal_entry_dates"):
            message.bot.meal_entry_dates.pop(user_id, None)


@dp.message(lambda m: getattr(m.bot, "expecting_barcode_photo_input", False) and m.photo is None)
async def kbju_barcode_photo_expected_but_text_received(message: Message):
    """Обработчик случая, когда ожидается фото штрих-кода, но получен текст"""
    await message.answer(
        "📷 Я ожидаю фото штрих-кода!\n\n"
        "Пожалуйста, отправь фото штрих-кода продукта. "
        "Убедись, что штрих-код хорошо виден и в фокусе.\n\n"
        "Если хочешь добавить КБЖУ другим способом, используй кнопки меню."
    )


@dp.message(lambda m: getattr(m.bot, "kbju_test_step", None) == "gender")
async def kbju_test_gender(message: Message):
    user_id = str(message.from_user.id)
    session = get_kbju_test_session(message.bot, user_id)
    txt = message.text.strip()

    if txt == "🙋‍♂️ Мужчина":
        session["gender"] = "male"
    elif txt == "🙋‍♀️ Женщина":
        session["gender"] = "female"
    else:
        await message.answer("Пожалуйста, выбери вариант с кнопки 🙂")
        return

    message.bot.kbju_test_step = "age"
    await message.answer("Сколько тебе лет? (например: 28)")


async def handle_kbju_test_number(message: Message, step: str):
    user_id = str(message.from_user.id)
    session = get_kbju_test_session(message.bot, user_id)

    try:
        value = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Нужно ввести число, попробуй ещё раз 🙂")
        return

    if step == "age":
        session["age"] = value
        message.bot.kbju_test_step = "height"
        await message.answer("Какой у тебя рост в сантиметрах? (например: 171)")
        return

    if step == "height":
        session["height"] = value
        message.bot.kbju_test_step = "weight"
        await message.answer("Сколько ты весишь сейчас? В кг (например: 86.5)")
        return

    if step == "weight":
        session["weight"] = value
        message.bot.kbju_test_step = "activity"
        await answer_with_menu(
            message,
            "Опиши свой обычный уровень активности:",
            reply_markup=kbju_activity_menu,
        )
        return


@dp.message(lambda m: getattr(m.bot, "kbju_test_step", None) == "activity")
async def kbju_test_activity(message: Message):
    user_id = str(message.from_user.id)
    session = get_kbju_test_session(message.bot, user_id)
    txt = message.text.strip()

    if txt == "🪑 Мало движения":
        session["activity"] = "low"
    elif txt == "🚶 Умеренная активность":
        session["activity"] = "medium"
    elif txt == "🏋️ Тренировки 3–5 раз/нед":
        session["activity"] = "high"
    else:
        await message.answer("Выбери вариант с кнопки, пожалуйста 🙂")
        return

    message.bot.kbju_test_step = "goal"
    await answer_with_menu(
        message,
        "Какая у тебя сейчас цель?",
        reply_markup=kbju_goal_menu,
    )


@dp.message(lambda m: getattr(m.bot, "kbju_test_step", None) == "goal")
async def kbju_test_goal(message: Message):
    user_id = str(message.from_user.id)
    session = get_kbju_test_session(message.bot, user_id)
    txt = message.text.strip()

    if txt == "📉 Похудение":
        session["goal"] = "loss"
    elif txt == "⚖️ Поддержание":
        session["goal"] = "maintain"
    elif txt == "💪 Набор массы":
        session["goal"] = "gain"
    else:
        await message.answer("Выбери вариант с кнопки, пожалуйста 🙂")
        return

    # считаем норму
    calories, protein, fat, carbs, goal_label = calculate_kbju_from_test(session)
    save_kbju_settings(user_id, calories, protein, fat, carbs, goal=session["goal"], activity=session.get("activity"))
    clear_kbju_test_session(message.bot, user_id)

    text = format_kbju_goal_text(calories, protein, fat, carbs, goal_label)
    message.bot.kbju_menu_open = True
    await message.answer(text, parse_mode="HTML")
    await message.answer("Теперь можешь пользоваться разделом КБЖУ 👇", reply_markup=kbju_menu)


@dp.message(lambda m: getattr(m.bot, "expecting_food_input", False))
async def handle_food_input(message: Message):
    user_text = message.text.strip()
    if not user_text:
        await message.answer("Напиши, пожалуйста, что ты съел(а) 🙏")
        return

    user_id = str(message.from_user.id)
    entry_date = getattr(message.bot, "meal_entry_dates", {}).get(user_id, date.today())

    translated_query = translate_text(user_text, source_lang="ru", target_lang="en")
    print(f"🍱 Перевод запроса для API: {translated_query}")

    try:
        items, totals = get_nutrition_from_api(translated_query)
    except Exception as e:
        print("Nutrition API error:", e)
        await message.answer(
            "⚠️ Не получилось получить КБЖУ из сервиса.\n"
            "Попробуй ещё раз чуть позже или измени формулировку."
        )
        return

    if not items:
        await message.answer(
            "Я не нашёл продукты в этом описании 🤔\n"
            "Попробуй написать чуть по-другому: добавь количество или уточни продукт."
        )
        return

    lines = ["🍱 Оценка по КБЖУ для этого приёма пищи:\n"]

    api_details_lines: list[str] = []

    for item in items:
        name_en = (item.get("name") or "item").title()
        name = translate_text(name_en, source_lang="en", target_lang="ru")

        # Берём уже приведённые к float значения, которые проставили в get_nutrition_from_api
        cal = float(item.get("_calories", 0.0))
        p = float(item.get("_protein_g", 0.0))
        f = float(item.get("_fat_total_g", 0.0))
        c = float(item.get("_carbohydrates_total_g", 0.0))

        line = f"• {name} — {cal:.0f} ккал (Б {p:.1f} / Ж {f:.1f} / У {c:.1f})"
        lines.append(line)
        api_details_lines.append(line)

    # --- ИТОГО по этому приёму ---
    lines.append("\nИТОГО:")
    lines.append(
        f"🔥 Калории: {float(totals['calories']):.0f} ккал\n"
        f"💪 Белки: {float(totals['protein_g']):.1f} г\n"
        f"🥑 Жиры: {float(totals['fat_total_g']):.1f} г\n"
        f"🍩 Углеводы: {float(totals['carbohydrates_total_g']):.1f} г"
    )

    api_details = "\n".join(api_details_lines)

    save_meal_entry(
        user_id=user_id,
        raw_query=user_text,
        totals=totals,
        entry_date=entry_date,
        api_details=api_details,
    )


    # --- СУММА ЗА СЕГОДНЯ ---
    daily_totals = get_daily_meal_totals(user_id, entry_date)

    lines.append("\nСУММА ЗА СЕГОДНЯ:")
    lines.append(
        f"🔥 Калории: {daily_totals['calories']:.0f} ккал\n"
        f"💪 Белки: {daily_totals['protein_g']:.1f} г\n"
        f"🥑 Жиры: {daily_totals['fat_total_g']:.1f} г\n"
        f"🍩 Углеводы: {daily_totals['carbohydrates_total_g']:.1f} г"
    )

    # Закрываем режим ввода еды
    message.bot.expecting_food_input = False
    if hasattr(message.bot, "meal_entry_dates"):
        message.bot.meal_entry_dates.pop(user_id, None)

    text = "\n".join(lines)
    await answer_with_menu(
        message,
        text,
        reply_markup=kbju_after_meal_menu,
    )


@dp.message(F.text == "➕ Внести ещё приём")
async def kbju_add_more_meal(message: Message):
    await start_kbju_add_flow(message, date.today())


@dp.message(F.text == "✏️ Редактировать")
async def kbju_edit_meals(message: Message):
    user_id = str(message.from_user.id)
    # показываем результаты за сегодня с инлайн-кнопками редактирования
    await send_today_results(message, user_id)


@dp.callback_query(F.data.startswith("meal_del:"))
async def delete_meal(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    meal_id = int(parts[1])
    target_date = date.fromisoformat(parts[2]) if len(parts) > 2 else date.today()
    user_id = str(callback.from_user.id)

    result = delete_meal_entry(meal_id, user_id)
    if not result:
        await callback.message.answer("Не нашёл такой продукт для удаления.")
        return

    entry_date, description = result
    await callback.message.answer(
        f"🗑 Удалил запись за {entry_date.strftime('%d.%m.%Y')}: {description}"
    )
    await show_day_meals(callback.message, user_id, entry_date)


@dp.callback_query(F.data.startswith("meal_edit:"))
async def start_meal_edit(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    meal_id = int(parts[1])
    target_date = date.fromisoformat(parts[2]) if len(parts) > 2 else date.today()
    user_id = str(callback.from_user.id)

    session = SessionLocal()
    try:
        meal = session.query(Meal).filter_by(id=meal_id, user_id=user_id).first()
        if not meal:
            await callback.message.answer("Не нашёл запись для изменения.")
            return

        # Извлекаем продукты из products_json
        products = []
        raw_products = getattr(meal, "products_json", None)
        if raw_products:
            try:
                products = json.loads(raw_products)
            except Exception:
                pass

        # Если продуктов нет, пробуем извлечь из api_details
        if not products and meal.api_details:
            # Парсим api_details для извлечения продуктов
            # Формат: "• название (вес г) — ккал (Б ... / Ж ... / У ...)"
            import re
            lines = meal.api_details.split("\n")
            for line in lines:
                if line.strip().startswith("•"):
                    # Извлекаем название и вес
                    match = re.match(r"•\s*(.+?)\s*\((\d+(?:\.\d+)?)\s*г\)", line)
                    if match:
                        name = match.group(1).strip()
                        grams = float(match.group(2))
                        # Извлекаем КБЖУ
                        kbju_match = re.search(r"(\d+(?:\.\d+)?)\s*ккал.*?Б\s*(\d+(?:\.\d+)?).*?Ж\s*(\d+(?:\.\d+)?).*?У\s*(\d+(?:\.\d+)?)", line)
                        if kbju_match:
                            cal = float(kbju_match.group(1))
                            prot = float(kbju_match.group(2))
                            fat = float(kbju_match.group(3))
                            carbs = float(kbju_match.group(4))
                            # Вычисляем КБЖУ на 100г
                            if grams > 0:
                                products.append({
                                    "name": name,
                                    "grams": grams,
                                    "calories": cal,
                                    "protein_g": prot,
                                    "fat_total_g": fat,
                                    "carbohydrates_total_g": carbs,
                                    "calories_per_100g": (cal / grams) * 100,
                                    "protein_per_100g": (prot / grams) * 100,
                                    "fat_per_100g": (fat / grams) * 100,
                                    "carbs_per_100g": (carbs / grams) * 100,
                                })

        if not products:
            await callback.message.answer(
                "❌ Не удалось извлечь список продуктов из этой записи.\n"
                "Попробуй удалить и создать запись заново."
            )
            return

        # Сохраняем продукты в контекст для пересчета
        ctx = getattr(callback.bot, "meal_edit_context", {})
        ctx[user_id] = {
            "meal_id": meal_id,
            "date": target_date,
            "products": products  # Сохраняем продукты с КБЖУ на 100г
        }
        callback.bot.meal_edit_context = ctx

        # Формируем список продуктов для редактирования (только название и вес)
        edit_lines = ["✏️ Редактирование приёма пищи\n\nТекущий состав:"]
        for i, p in enumerate(products, 1):
            name = p.get("name") or "продукт"
            grams = p.get("grams", 0)
            edit_lines.append(f"{i}. {name}, {grams:.0f} г")
        
        edit_lines.append("\nВведи новый состав в формате:")
        edit_lines.append("название, вес г")
        edit_lines.append("название, вес г")
        edit_lines.append("\nПример:")
        edit_lines.append("курица, 200 г")
        edit_lines.append("рис, 150 г")
        edit_lines.append("\nМожно изменить название и/или вес. КБЖУ пересчитается автоматически.")

        await callback.message.answer("\n".join(edit_lines))
    finally:
        session.close()


@dp.message(lambda m: getattr(m.bot, "meal_edit_context", {}).get(str(m.from_user.id)))
async def handle_meal_edit_input(message: Message):
    user_id = str(message.from_user.id)
    context = message.bot.meal_edit_context.get(user_id) or {}
    meal_id = context.get("meal_id")
    target_date = context.get("date", date.today())
    saved_products = context.get("products", [])
    new_text = message.text.strip()

    if not meal_id:
        message.bot.meal_edit_context.pop(user_id, None)
        await message.answer("Не получилось определить запись для обновления.")
        return

    if not new_text:
        await message.answer("Напиши новый состав продуктов в формате: название, вес г")
        return

    if not saved_products:
        await message.answer(
            "❌ Не удалось найти сохраненные данные продуктов.\n"
            "Попробуй удалить и создать запись заново."
        )
        message.bot.meal_edit_context.pop(user_id, None)
        return

    # Парсим ввод пользователя: каждая строка = "название, вес г"
    import re
    lines = [line.strip() for line in new_text.split("\n") if line.strip()]
    edited_products = []
    
    for i, line in enumerate(lines):
        # Парсим формат "название, вес г" или "название, вес"
        match = re.match(r"(.+?),\s*(\d+(?:[.,]\d+)?)\s*г?", line, re.IGNORECASE)
        if not match:
            await message.answer(
                f"❌ Неверный формат в строке {i+1}: {line}\n"
                "Используй формат: название, вес г\n"
                "Пример: курица, 200 г"
            )
            return
        
        name = match.group(1).strip()
        grams_str = match.group(2).replace(",", ".")
        grams = float(grams_str)
        
        # Находим соответствующий продукт из сохраненных (по порядку или по названию)
        if i < len(saved_products):
            original_product = saved_products[i]
        else:
            # Если продуктов больше, чем было, используем последний продукт как шаблон
            original_product = saved_products[-1] if saved_products else None
        
        if not original_product:
            await message.answer("❌ Ошибка: не найдены исходные данные продукта.")
            return
        
        # Получаем КБЖУ на 100г из сохраненных данных
        # Если есть сохраненные значения на 100г, используем их
        calories_per_100g = original_product.get("calories_per_100g")
        protein_per_100g = original_product.get("protein_per_100g")
        fat_per_100g = original_product.get("fat_per_100g")
        carbs_per_100g = original_product.get("carbs_per_100g")
        
        # Если нет значений на 100г, вычисляем из сохраненных данных
        if not calories_per_100g and original_product.get("grams", 0) > 0:
            orig_grams = original_product.get("grams", 1)
            calories_per_100g = (original_product.get("calories", 0) / orig_grams) * 100
            protein_per_100g = (original_product.get("protein_g", 0) / orig_grams) * 100
            fat_per_100g = (original_product.get("fat_total_g", 0) / orig_grams) * 100
            carbs_per_100g = (original_product.get("carbohydrates_total_g", 0) / orig_grams) * 100
        
        # Пересчитываем КБЖУ для нового веса
        new_calories = (calories_per_100g * grams) / 100
        new_protein = (protein_per_100g * grams) / 100
        new_fat = (fat_per_100g * grams) / 100
        new_carbs = (carbs_per_100g * grams) / 100
        
        edited_products.append({
            "name": name,
            "grams": grams,
            "calories": new_calories,
            "protein_g": new_protein,
            "fat_total_g": new_fat,
            "carbohydrates_total_g": new_carbs,
        })

    # Суммируем КБЖУ всех продуктов
    totals = {
        "calories": sum(p["calories"] for p in edited_products),
        "protein_g": sum(p["protein_g"] for p in edited_products),
        "fat_total_g": sum(p["fat_total_g"] for p in edited_products),
        "carbohydrates_total_g": sum(p["carbohydrates_total_g"] for p in edited_products),
        "products": edited_products,
    }

    # Формируем api_details
    api_details_lines: list[str] = []
    for p in edited_products:
        api_details_lines.append(
            f"• {p['name']} ({p['grams']:.0f} г) — {p['calories']:.0f} ккал "
            f"(Б {p['protein_g']:.1f} / Ж {p['fat_total_g']:.1f} / У {p['carbohydrates_total_g']:.1f})"
        )
    api_details = "\n".join(api_details_lines) if api_details_lines else None

    # Обновляем запись
    success = update_meal_entry(meal_id, user_id, new_text, totals, api_details=api_details)
    if not success:
        message.bot.meal_edit_context.pop(user_id, None)
        await message.answer("Не нашёл запись для обновления.")
        return

    message.bot.meal_edit_context.pop(user_id, None)

    # Получаем общие дневные итоги после обновления
    daily_totals = get_daily_meal_totals(user_id, target_date)
    
    # Получаем настройки КБЖУ для отображения нормы и процентов
    settings = get_kbju_settings(user_id)
    
    lines = ["✅ Обновил запись по КБЖУ:\n"]
    
    if settings:
        # Получаем сожженные калории и скорректированные нормы (как в format_progress_block)
        burned_calories = get_daily_workout_calories(user_id, target_date)
        base_calories_target = settings.calories
        adjusted_calories_target = base_calories_target + burned_calories
        
        # Пропорционально увеличиваем норму БЖУ
        if base_calories_target > 0:
            ratio = adjusted_calories_target / base_calories_target
            adjusted_protein_target = settings.protein * ratio
            adjusted_fat_target = settings.fat * ratio
            adjusted_carbs_target = settings.carbs * ratio
        else:
            adjusted_protein_target = settings.protein
            adjusted_fat_target = settings.fat
            adjusted_carbs_target = settings.carbs
        
        def format_line(label: str, current: float, target: float, unit: str) -> str:
            percent = 0 if target <= 0 else round((current / target) * 100)
            return f"{label}: {current:.0f}/{target:.0f} {unit} ({percent}%)"
        
        lines.extend(
            [
                format_line("🔥 Калории", daily_totals['calories'], adjusted_calories_target, "ккал"),
                format_line("💪 Белки", daily_totals['protein_g'], adjusted_protein_target, "г"),
                format_line("🥑 Жиры", daily_totals['fat_total_g'], adjusted_fat_target, "г"),
                format_line("🍩 Углеводы", daily_totals['carbohydrates_total_g'], adjusted_carbs_target, "г"),
            ]
        )
    else:
        # Если настройки не заданы, показываем без нормы
        lines.extend(
            [
                f"🔥 Калории: {daily_totals['calories']:.0f} ккал",
                f"💪 Белки: {daily_totals['protein_g']:.1f} г",
                f"🥑 Жиры: {daily_totals['fat_total_g']:.1f} г",
                f"🍩 Углеводы: {daily_totals['carbohydrates_total_g']:.1f} г",
            ]
        )

    await message.answer("\n".join(lines))
    await show_day_meals(message, user_id, target_date)

@dp.message(F.text == "📆 Календарь")
async def calendar_view(message: Message):
    user_id = str(message.from_user.id)
    await show_calendar(message, user_id)


@dp.callback_query(F.data == "cal_close")
async def close_calendar(callback: CallbackQuery):
    await callback.answer("Календарь закрыт")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@dp.callback_query(F.data == "noop")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("cal_nav:"))
async def navigate_calendar(callback: CallbackQuery):
    await callback.answer()
    _, ym = callback.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    user_id = str(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=build_calendar_keyboard(user_id, year, month)
    )


@dp.callback_query(F.data.startswith("cal_back:"))
async def back_to_calendar(callback: CallbackQuery):
    await callback.answer()
    _, ym = callback.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    user_id = str(callback.from_user.id)
    await show_calendar(callback.message, user_id, year, month)


@dp.callback_query(F.data.startswith("cal_day:"))
async def select_calendar_day(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    callback.bot.edit_calendar_month = date(target_date.year, target_date.month, 1)
    await show_day_workouts(callback.message, str(callback.from_user.id), target_date)


@dp.callback_query(F.data.startswith("meal_cal_nav:"))
async def navigate_kbju_calendar(callback: CallbackQuery):
    await callback.answer()
    _, ym = callback.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    user_id = str(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=build_kbju_calendar_keyboard(user_id, year, month)
    )


@dp.callback_query(F.data.startswith("meal_cal_back:"))
async def back_to_kbju_calendar(callback: CallbackQuery):
    await callback.answer()
    _, ym = callback.data.split(":", 1)
    year, month = map(int, ym.split("-"))
    user_id = str(callback.from_user.id)
    await show_kbju_calendar(callback.message, user_id, year, month)


@dp.callback_query(F.data.startswith("meal_cal_day:"))
async def select_kbju_calendar_day(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    await show_day_meals(callback.message, str(callback.from_user.id), target_date)


@dp.callback_query(F.data.startswith("meal_cal_add:"))
async def add_kbju_from_calendar(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = date.fromisoformat(date_str)

    reset_user_state(callback.message, keep_supplements=True)
    await start_kbju_add_flow(callback.message, target_date)


@dp.callback_query(F.data.startswith("wrk_add:"))
async def add_workout_from_calendar(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    start_date_selection(callback.bot, "training")
    callback.bot.selected_date = target_date
    await proceed_after_date_selection(callback.message)


@dp.callback_query(F.data.startswith("wrk_del:"))
async def delete_workout(callback: CallbackQuery):
    await callback.answer()
    workout_id = int(callback.data.split(":", 1)[1])
    user_id = str(callback.from_user.id)

    session = SessionLocal()
    try:
        workout = session.query(Workout).filter_by(id=workout_id, user_id=user_id).first()
        if not workout:
            await callback.message.answer("Не нашёл такую запись для удаления.")
            return

        target_date = workout.date
        session.delete(workout)
        session.commit()
    finally:
        session.close()

    await callback.message.answer(
        f"🗑 Удалил: {target_date.strftime('%d.%m.%Y')} — {workout.exercise} ({workout.count})"
    )
    await show_day_workouts(callback.message, user_id, target_date)


@dp.callback_query(F.data.startswith("wrk_edit:"))
async def edit_workout(callback: CallbackQuery):
    await callback.answer()
    workout_id = int(callback.data.split(":", 1)[1])
    user_id = str(callback.from_user.id)

    session = SessionLocal()
    try:
        workout = session.query(Workout).filter_by(id=workout_id, user_id=user_id).first()
    finally:
        session.close()

    if not workout:
        await callback.message.answer("Не нашёл тренировку для изменения.")
        return

    callback.bot.expecting_edit_workout_id = workout_id
    callback.bot.edit_workout_date = workout.date
    await callback.message.answer(
        f"✏️ Введи новое количество для {workout.exercise} от {workout.date.strftime('%d.%m.%Y')}"
    )


@dp.message(F.text.in_(["🏋️ История тренировок", "📆 Календарь тренировок"]))
async def my_workouts(message: Message):
    user_id = str(message.from_user.id)
    await show_calendar(message, user_id)







@dp.message(F.text == "Сегодня")
async def workouts_today(message: Message):
    user_id = str(message.from_user.id)

    # создаём сессию
    db = SessionLocal()
    try:
        # получаем все тренировки пользователя за сегодня
        today = date.today()
        todays_workouts = (
            db.query(Workout)
            .filter(Workout.user_id == user_id, Workout.date == today)
            .all()
        )
    finally:
        db.close()

    # если ничего нет — показываем описание раздела тренировки
    if not todays_workouts:
        text = (
            "Сегодня ты ещё ничего не записывал 💤\n\n"
            "<b>🏋️ Раздел «Тренировка»</b>\n\n"
            "Здесь ты фиксируешь свои упражнения за день: подходы, время, шаги и т.п. "
            "Каждая запись сохраняется и попадает в календарь и историю, чтобы ты видел прогресс.\n\n"
            "<b>🔥 Как считается расход калорий</b>\n"
            "• Если ты выбираешь вариант <b>«Минуты»</b> — бот умножает длительность тренировки на "
            "интенсивность упражнения и твой вес, получая примерный расход ккал.\n"
            "• Для варианта <b>«Количество шагов»</b> бот грубо переводит шаги в минуты ходьбы и "
            "также оценивает, сколько калорий ты потратил.\n"
            "• Для силовых упражнений с повторами бот использует усреднённую калорийность одного повтора "
            "и масштабирует её под твой вес.\n\n"
            "Это не медицинские точные значения, а ориентир, чтобы понимать динамику нагрузки и баланс с КБЖУ. "
            "Нажми «➕ Добавить тренировку», запиши первый подход — и здесь появится твой список за сегодня 💪"
        )

        await answer_with_menu(message, text, reply_markup=my_workouts_menu)
        return

    # если тренировки есть — остаётся старое поведение
    message.bot.todays_workouts = todays_workouts
    message.bot.expecting_delete = False

    text = "💪 Результаты за сегодня:\n\n"
    for i, w in enumerate(todays_workouts, 1):
        variant_text = f" ({w.variant})" if w.variant else ""
        text += f"{i}. {w.exercise}{variant_text}: {w.count}\n"

    await answer_with_menu(message, text, reply_markup=today_menu)



@dp.message(F.text == "В другие дни")
async def workouts_history(message: Message):
    user_id = str(message.from_user.id)

    # создаём сессию
    db = SessionLocal()
    try:
        # получаем все тренировки, кроме сегодняшних
        history = (
            db.query(Workout)
            .filter(Workout.user_id == user_id, Workout.date != date.today())
            .order_by(Workout.date.desc())
            .all()
        )
    finally:
        db.close()

    # если записей нет
    if not history:
        await answer_with_menu(message, "У тебя пока нет истории тренировок 📭", reply_markup=my_workouts_menu)
        return

    # формируем текст
    text = "📅 История твоих тренировок:\n\n"
    for w in history:
        variant_text = f" ({w.variant})" if w.variant and w.variant != "Минуты" else ""
        formatted_count = format_count_with_unit(w.count, w.variant)
        entry_calories = w.calories or calculate_workout_calories(user_id, w.exercise, w.variant, w.count)
        text += (
            f"{w.date}: {w.exercise}{variant_text}: "
            f"{formatted_count} (~{entry_calories:.0f} ккал)\n"
        )

    await answer_with_menu(message, text, reply_markup=history_menu)



@dp.message(F.text == "Удалить запись из истории")
async def delete_from_history_start(message: Message):
    user_id = str(message.from_user.id)

    # создаём сессию
    db = SessionLocal()
    try:
        # получаем все тренировки пользователя
        history = (
            db.query(Workout)
            .filter(Workout.user_id == user_id)
            .order_by(Workout.date.desc())
            .all()
        )
    finally:
        db.close()

    if not history:
        await answer_with_menu(message, "История пуста 📭", reply_markup=my_workouts_menu)
        return

    # сохраняем в оперативную память (для следующего шага — удаления)
    message.bot.expecting_history_delete = True
    message.bot.history_workouts = history

    # формируем текст
    text = "Выбери номер записи для удаления:\n\n"
    for i, w in enumerate(history, 1):
        variant_text = f" ({w.variant})" if w.variant and w.variant != "Минуты" else ""
        formatted_count = format_count_with_unit(w.count, w.variant)
        text += f"{i}. {w.date} — {w.exercise}{variant_text}: {formatted_count}\n"

    await message.answer(text)




# -------------------- run --------------------
@dp.message(F.text == "💆 Процедуры")
async def procedures(message: Message):
    reset_user_state(message)
    user_id = str(message.from_user.id)
    message.bot.procedures_menu_open = True
    
    intro_text = (
        "💆 Раздел «Процедуры»\n\n"
        "Здесь ты можешь отслеживать любые процедуры для здоровья и красоты:\n"
        "• Контрастный душ\n"
        "• Баня и сауна\n"
        "• СПА-процедуры\n"
        "• Косметические процедуры\n"
        "• Массаж\n"
        "• И любые другие процедуры для ухода за собой\n\n"
        "Все записи сохраняются в календарь, чтобы ты видел свою активность."
    )
    
    await answer_with_menu(
        message,
        intro_text,
        reply_markup=procedures_menu,
    )


@dp.message(lambda m: m.text == "➕ Добавить процедуру" and getattr(m.bot, "procedures_menu_open", False))
async def add_procedure(message: Message):
    reset_user_state(message)
    message.bot.procedures_menu_open = True  # Восстанавливаем флаг после reset_user_state
    message.bot.expecting_procedure_name = True
    
    await answer_with_menu(
        message,
        "💆 Добавление процедуры\n\n"
        "Напиши название процедуры (например: контрастный душ, баня, массаж, маска для лица и т.д.)\n\n"
        "Можешь добавить заметки через запятую после названия.",
        reply_markup=procedures_menu,
    )


@dp.message(lambda m: getattr(m.bot, "expecting_procedure_name", False))
async def process_procedure_name(message: Message):
    user_id = str(message.from_user.id)
    text = message.text.strip()
    
    if not text:
        await message.answer("Напиши название процедуры, пожалуйста 🙏")
        return
    
    # Разделяем название и заметки (если есть запятая)
    parts = text.split(",", 1)
    name = parts[0].strip()
    notes = parts[1].strip() if len(parts) > 1 else None
    
    entry_date = date.today()
    save_procedure(user_id, name, entry_date, notes)
    
    message.bot.expecting_procedure_name = False
    message.bot.procedures_menu_open = True  # Восстанавливаем флаг после добавления процедуры
    
    result_text = f"✅ Добавил процедуру: {name}"
    if notes:
        result_text += f"\n📝 Заметки: {notes}"
    
    await answer_with_menu(
        message,
        result_text,
        reply_markup=procedures_menu,
    )


@dp.message(lambda m: m.text == "📊 Сегодня" and getattr(m.bot, "procedures_menu_open", False))
async def procedures_today(message: Message):
    reset_user_state(message)
    message.bot.procedures_menu_open = True  # Восстанавливаем флаг после reset_user_state
    user_id = str(message.from_user.id)
    today = date.today()
    procedures_list = get_procedures_for_day(user_id, today)
    
    if not procedures_list:
        await answer_with_menu(
            message,
            "💆 Сегодня процедур пока нет.\n\nДобавь первую процедуру через кнопку «➕ Добавить процедуру»",
            reply_markup=procedures_menu,
        )
        return
    
    lines = [f"💆 Процедуры за {today.strftime('%d.%m.%Y')}:\n"]
    for i, proc in enumerate(procedures_list, 1):
        notes_text = f" ({proc.notes})" if proc.notes else ""
        lines.append(f"{i}. {proc.name}{notes_text}")
    
    await answer_with_menu(
        message,
        "\n".join(lines),
        reply_markup=procedures_menu,
    )


@dp.message(lambda m: m.text == "📆 Календарь процедур" and getattr(m.bot, "procedures_menu_open", False))
async def procedures_calendar(message: Message):
    reset_user_state(message)
    message.bot.procedures_menu_open = True  # Восстанавливаем флаг после reset_user_state
    user_id = str(message.from_user.id)
    today = date.today()
    keyboard = build_procedures_calendar_keyboard(user_id, today.year, today.month)
    await message.answer(
        "📆 Выбери день, чтобы посмотреть процедуры:",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("proc_cal_nav:"))
async def navigate_procedures_calendar(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    year, month = map(int, date_str.split("-"))
    user_id = str(callback.from_user.id)
    keyboard = build_procedures_calendar_keyboard(user_id, year, month)
    await callback.message.edit_reply_markup(reply_markup=keyboard)


@dp.callback_query(F.data.startswith("proc_cal_day:"))
async def select_procedure_calendar_day(callback: CallbackQuery):
    await callback.answer()
    _, date_str = callback.data.split(":", 1)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    user_id = str(callback.from_user.id)
    procedures_list = get_procedures_for_day(user_id, target_date)
    
    if not procedures_list:
        await callback.message.answer(
            f"💆 {target_date.strftime('%d.%m.%Y')}\n\nПроцедур в этот день не было.",
            reply_markup=procedures_menu,
        )
        return
    
    lines = [f"💆 Процедуры за {target_date.strftime('%d.%m.%Y')}:\n"]
    for i, proc in enumerate(procedures_list, 1):
        notes_text = f" ({proc.notes})" if proc.notes else ""
        lines.append(f"{i}. {proc.name}{notes_text}")
    
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=procedures_menu,
    )


@dp.message(F.text == "💧 Контроль воды")
async def water(message: Message):
    reset_user_state(message)
    user_id = str(message.from_user.id)
    message.bot.water_menu_open = True
    today = date.today()
    daily_total = get_daily_water_total(user_id, today)
    recommended = get_water_recommended(user_id)
    
    # Получаем вес для уведомления
    weight = get_last_weight_kg(user_id)
    
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    bar = build_water_progress_bar(daily_total, recommended)
    
    # Формируем текст с информацией о расчете нормы
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
    
    await answer_with_menu(
        message,
        intro_text,
        reply_markup=water_menu,
    )


@dp.message(lambda m: m.text == "➕ Добавить воду" and getattr(m.bot, "water_menu_open", False))
async def add_water(message: Message):
    # Сбрасываем состояние, но сохраняем флаг water_menu_open
    reset_user_state(message)
    message.bot.water_menu_open = True
    message.bot.expecting_water_amount = True
    
    await answer_with_menu(
        message,
        "💧 Добавление воды\n\n"
        "Напиши количество воды в миллилитрах или выбери из предложенных.",
        reply_markup=water_amount_menu,
    )


@dp.message(lambda m: m.text == "📊 Статистика за сегодня" and getattr(m.bot, "water_menu_open", False))
async def water_today(message: Message):
    reset_user_state(message)
    message.bot.water_menu_open = True  # Восстанавливаем флаг после reset_user_state
    user_id = str(message.from_user.id)
    today = date.today()
    entries = get_water_entries_for_day(user_id, today)
    daily_total = get_daily_water_total(user_id, today)
    recommended = get_water_recommended(user_id)
    
    if not entries:
        await answer_with_menu(
            message,
            "💧 Сегодня воды ещё не добавлено.\n\n"
            "Используй кнопку «➕ Добавить воду» для записи.",
            reply_markup=water_menu,
        )
        return
    
    lines = [f"💧 Вода за {today.strftime('%d.%m.%Y')}:\n"]
    for i, entry in enumerate(entries, 1):
        time_str = entry.timestamp.strftime("%H:%M") if entry.timestamp else ""
        lines.append(f"{i}. {entry.amount:.0f} мл {time_str}")
    
    lines.append(f"\n📊 Итого: {daily_total:.0f} мл")
    lines.append(f"🎯 Норма: {recommended} мл")
    progress = round((daily_total / recommended) * 100) if recommended > 0 else 0
    lines.append(f"📈 Прогресс: {progress}%")
    
    # Визуальный прогресс-бар (используем build_water_progress_bar)
    bar = build_water_progress_bar(daily_total, recommended)
    lines.append(f"\n{bar}")
    
    await answer_with_menu(
        message,
        "\n".join(lines),
        reply_markup=water_menu,
    )


@dp.message(lambda m: m.text == "📆 История" and getattr(m.bot, "water_menu_open", False))
async def water_history(message: Message):
    reset_user_state(message)
    message.bot.water_menu_open = True  # Восстанавливаем флаг после reset_user_state
    user_id = str(message.from_user.id)
    
    session = SessionLocal()
    try:
        # Получаем последние 7 дней с записями
        entries = (
            session.query(WaterEntry)
            .filter(WaterEntry.user_id == user_id)
            .order_by(WaterEntry.date.desc())
            .limit(7)
            .all()
        )
    finally:
        session.close()
    
    if not entries:
        await answer_with_menu(
            message,
            "💧 История пуста.\n\nНачни отслеживать воду прямо сейчас!",
            reply_markup=water_menu,
        )
        return
    
    # Группируем по дням
    daily_totals = defaultdict(float)
    for entry in entries:
        daily_totals[entry.date] += entry.amount
    
    lines = ["💧 История (последние дни):\n"]
    for day, total in sorted(daily_totals.items(), reverse=True):
        day_str = day.strftime("%d.%m.%Y")
        lines.append(f"{day_str}: {total:.0f} мл")
    
    await answer_with_menu(
        message,
        "\n".join(lines),
        reply_markup=water_menu,
    )


@dp.message(F.text == "⚙️ Настройки")
async def settings(message: Message):
    reset_user_state(message)
    await answer_with_menu(
        message,
        "⚙️ Настройки\n\nВыбери действие:",
        reply_markup=settings_menu,
    )


@dp.message(F.text == "🗑 Удалить аккаунт")
async def delete_account_start(message: Message):
    reset_user_state(message)
    message.bot.expecting_account_deletion_confirm = True
    await answer_with_menu(
        message,
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        "Вы уверены, что хотите удалить аккаунт?\n\n"
        "При удалении аккаунта будут <b>безвозвратно удалены</b> все ваши данные:\n"
        "• Все тренировки\n"
        "• Все записи веса и замеров\n"
        "• Все записи КБЖУ\n"
        "• Все добавки и их история\n"
        "• Настройки КБЖУ\n\n"
        "Это действие нельзя отменить!",
        reply_markup=delete_account_confirm_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "✅ Да, удалить аккаунт")
async def delete_account_confirm(message: Message):
    if not getattr(message.bot, "expecting_account_deletion_confirm", False):
        await message.answer("Что-то пошло не так. Попробуй заново через меню Настройки.")
        return
    
    user_id = str(message.from_user.id)
    message.bot.expecting_account_deletion_confirm = False
    
    success = delete_user_account(user_id)
    
    if success:
        await message.answer(
            "✅ Аккаунт успешно удалён.\n\n"
            "Все ваши данные были удалены из базы данных.\n\n"
            "Если захотите вернуться, просто нажмите /start",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/start")]],
                resize_keyboard=True
            )
        )
    else:
        await message.answer(
            "❌ Произошла ошибка при удалении аккаунта.\n"
            "Попробуйте позже или обратитесь в поддержку.",
            reply_markup=settings_menu,
        )


@dp.message(F.text == "❌ Отмена")
async def delete_account_cancel(message: Message):
    if getattr(message.bot, "expecting_account_deletion_confirm", False):
        message.bot.expecting_account_deletion_confirm = False
        await answer_with_menu(
            message,
            "❌ Удаление аккаунта отменено.",
            reply_markup=settings_menu,
        )


@dp.message(F.text == "💬 Поддержка")
async def support(message: Message):
    reset_user_state(message)
    await answer_with_menu(
        message,
        "💬 Поддержка\n\n"
        "Эта функция пока в разработке. Скоро здесь можно будет связаться с поддержкой!",
        reply_markup=settings_menu,
    )


@dp.message(F.text == "🔒 Политика конфиденциальности")
async def privacy_policy(message: Message):
    reset_user_state(message)
    privacy_text = (
        "🔒 <b>Политика конфиденциальности</b>\n\n"
        "Добро пожаловать в Fitness Bot! Мы ценим вашу конфиденциальность и стремимся защищать ваши личные данные.\n\n"
        "<b>1. Сбор данных</b>\n"
        "Бот собирает и хранит следующие данные:\n"
        "• Идентификатор пользователя Telegram\n"
        "• Данные о тренировках (упражнения, количество, даты)\n"
        "• Записи веса и замеров тела (числовые значения)\n"
        "• Записи питания (КБЖУ)\n"
        "• Информация о добавках и их приёме\n"
        "• Настройки КБЖУ и цели\n"
        "• Фотографии еды, этикеток и штрих-кодов (используются только для анализа КБЖУ, не хранятся)\n\n"
        "<b>2. Использование данных</b>\n"
        "Ваши данные используются исключительно для:\n"
        "• Предоставления функционала бота\n"
        "• Отображения статистики и прогресса\n"
        "• Расчёта калорий и КБЖУ\n"
        "• Хранения истории тренировок и питания\n"
        "• Анализа фотографий еды для определения КБЖУ (через ИИ)\n\n"
        "<b>3. Хранение данных</b>\n"
        "Все данные хранятся в защищённой базе данных на сервере бота. "
        "Мы применяем стандартные меры безопасности для защиты вашей информации.\n\n"
        "<b>4. Передача данных третьим лицам</b>\n"
        "Мы не передаём ваши персональные данные третьим лицам. "
        "Данные используются только для работы бота и не продаются, не сдаются в аренду и не передаются другим компаниям.\n\n"
        "<b>5. Удаление данных</b>\n"
        "Вы можете в любой момент удалить свой аккаунт и все связанные данные через функцию "
        "\"🗑 Удалить аккаунт\" в настройках. После удаления все ваши данные будут безвозвратно удалены из базы данных.\n\n"
        "<b>6. Изменения в политике</b>\n"
        "Мы оставляем за собой право обновлять данную политику конфиденциальности. "
        "О существенных изменениях мы уведомим пользователей через бота.\n\n"
        "<b>7. Контакты</b>\n"
        "Если у вас есть вопросы о политике конфиденциальности, используйте функцию \"💬 Поддержка\" в настройках.\n\n"
        "Дата последнего обновления: 15.12.2025"
    )
    await answer_with_menu(
        message,
        privacy_text,
        reply_markup=settings_menu,
        parse_mode="HTML",
    )


nest_asyncio.apply()

async def main():
    print("🚀 Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
