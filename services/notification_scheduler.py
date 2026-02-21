"""Сервис для отправки запланированных уведомлений."""
import asyncio
import logging
import json
from datetime import datetime, time
from aiogram import Bot
from database.session import get_db_session
from database.models import User, Supplement

logger = logging.getLogger(__name__)


class NotificationScheduler:
    """Планировщик уведомлений о приёмах пищи и добавках."""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.running = False
        self.sent_notifications_today = set()  # Для предотвращения дублирования уведомлений
        self._last_check_date = None  # Дата последней проверки для сброса кэша
        
    async def send_notification(self, user_id: str, message: str):
        """Отправляет уведомление пользователю."""
        try:
            await self.bot.send_message(chat_id=user_id, text=message)
            logger.info(f"Уведомление отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
    
    async def send_meal_notifications(self, meal_type: str, message_text: str):
        """Отправляет уведомления о приёме пищи всем пользователям."""
        try:
            with get_db_session() as session:
                users = session.query(User).all()
                user_ids = [user.user_id for user in users]
            
            logger.info(f"Отправка уведомлений о {meal_type} {len(user_ids)} пользователям")
            
            # Отправляем уведомления всем пользователям
            tasks = [self.send_notification(user_id, message_text) for user_id in user_ids]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            logger.info(f"Уведомления о {meal_type} отправлены")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомлений о {meal_type}: {e}")
    
    def _get_weekday_name(self, weekday: int) -> str:
        """Преобразует номер дня недели (0=Понедельник) в русское сокращение."""
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        return weekday_names[weekday]
    
    def calculate_next_time(self, target_time: time) -> float:
        """Вычисляет время до следующего указанного времени в секундах."""
        now = datetime.now()
        target_datetime = datetime.combine(now.date(), target_time)
        
        # Если время уже прошло сегодня, планируем на завтра
        if now.time() >= target_time:
            from datetime import timedelta
            target_datetime += timedelta(days=1)
        
        delta = (target_datetime - now).total_seconds()
        return delta
    
    async def schedule_daily_notification(self, target_time: time, meal_type: str, message_text: str):
        """Планирует ежедневное уведомление на указанное время."""
        while self.running:
            try:
                # Вычисляем время до следующего указанного времени
                wait_seconds = self.calculate_next_time(target_time)
                
                logger.info(
                    f"Следующее уведомление о {meal_type} будет отправлено через "
                    f"{wait_seconds / 3600:.2f} часов (в {target_time})"
                )
                
                # Ждём до указанного времени
                await asyncio.sleep(wait_seconds)
                
                # Отправляем уведомления
                await self.send_meal_notifications(meal_type, message_text)
                
                # Ждём 1 секунду перед следующей итерацией (чтобы не отправлять дважды)
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logger.info(f"Планировщик уведомлений о {meal_type} остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в планировщике уведомлений о {meal_type}: {e}")
                # В случае ошибки ждём минуту перед повтором
                await asyncio.sleep(60)
    
    async def start(self):
        """Запускает планировщик уведомлений."""
        self.running = True
        logger.info("Запуск планировщика уведомлений о приёмах пищи и добавках")
        
        # Создаём задачи для каждого времени приёма пищи
        tasks = [
            self.schedule_daily_notification(
                time(10, 0),
                "завтрак",
                "Добавьте завтрак и Вы на один шаг приблизитесь к цели!"
            ),
            self.schedule_daily_notification(
                time(14, 0),
                "обед",
                "Добавьте обед и Вы на один шаг приблизитесь к цели!"
            ),
            self.schedule_daily_notification(
                time(20, 0),
                "ужин",
                "Добавьте ужин и Вы на один шаг приблизитесь к цели!"
            ),
            # Запускаем цикл проверки уведомлений о добавках
            self.supplement_notification_loop(),
        ]
        
        # Запускаем все задачи параллельно
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def check_and_send_supplement_notifications(self):
        """Проверяет добавки и отправляет уведомления, если наступило время приёма."""
        try:
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            current_weekday = self._get_weekday_name(now.weekday())
            today_date = now.date()
            
            # Сбрасываем кэш отправленных уведомлений в начале нового дня
            if self._last_check_date is None or self._last_check_date != today_date:
                self.sent_notifications_today.clear()
                self._last_check_date = today_date
            
            with get_db_session() as session:
                # Получаем все добавки с включенными уведомлениями (проверяем явно на True, чтобы исключить None)
                supplements = session.query(Supplement).filter(
                    Supplement.notifications_enabled.is_(True)
                ).all()
                
                for supplement in supplements:
                    try:
                        # Парсим дни и время
                        days = json.loads(supplement.days_json or "[]")
                        times = json.loads(supplement.times_json or "[]")
                        
                        # Проверяем, нужно ли отправлять уведомление
                        if not days or not times:
                            continue
                        
                        # Проверяем день недели
                        if current_weekday not in days:
                            continue
                        
                        # Проверяем время (с точностью до минуты)
                        if current_time_str not in times:
                            continue
                        
                        # Создаём уникальный ключ для уведомления
                        notification_key = f"{supplement.user_id}_{supplement.id}_{current_time_str}_{today_date}"
                        
                        # Проверяем, не отправляли ли уже это уведомление сегодня
                        if notification_key in self.sent_notifications_today:
                            continue
                        
                        # Отправляем уведомление
                        message = f"💊 Напоминание: пора принять добавку {supplement.name}"
                        await self.send_notification(supplement.user_id, message)
                        
                        # Помечаем уведомление как отправленное
                        self.sent_notifications_today.add(notification_key)
                        logger.info(
                            f"Отправлено уведомление о добавке {supplement.name} "
                            f"пользователю {supplement.user_id} в {current_time_str}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Ошибка при проверке добавки {supplement.id} "
                            f"для пользователя {supplement.user_id}: {e}",
                            exc_info=True
                        )
        except Exception as e:
            logger.error(f"Ошибка при проверке уведомлений о добавках: {e}", exc_info=True)
    
    async def supplement_notification_loop(self):
        """Цикл проверки уведомлений о добавках каждую минуту."""
        while self.running:
            try:
                await self.check_and_send_supplement_notifications()
                # Проверяем каждую минуту
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info("Цикл проверки уведомлений о добавках остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле проверки уведомлений о добавках: {e}", exc_info=True)
                # В случае ошибки ждём минуту перед повтором
                await asyncio.sleep(60)
    
    def stop(self):
        """Останавливает планировщик уведомлений."""
        self.running = False
        logger.info("Планировщик уведомлений остановлен")

