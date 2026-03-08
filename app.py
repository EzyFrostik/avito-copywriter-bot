import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Токен из переменных окружения
import os
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Клавиатура главного меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Анализ объявления")],
        [KeyboardButton(text="📊 Мои отчёты"), KeyboardButton(text="💎 Купить анализы")],
        [KeyboardButton(text="🎫 Ввести промокод"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я помогу проанализировать твоё объявление на Авито и сделать его лучше.\n\n"
        "Выбери действие:",
        reply_markup=main_menu
    )

# Обработчик кнопки "🔍 Анализ объявления"
@dp.message(lambda message: message.text == "🔍 Анализ объявления")
async def analyze_start(message: types.Message):
    await message.answer("🔗 Отправь мне ссылку на твоё объявление на Авито")

# Заглушки для остальных кнопок
@dp.message(lambda message: message.text == "📊 Мои отчёты")
async def my_reports(message: types.Message):
    await message.answer("📊 Здесь будет история твоих анализов. Пока она пуста.")

@dp.message(lambda message: message.text == "💎 Купить анализы")
async def buy_analyses(message: types.Message):
    await message.answer(
        "💎 Тарифы:\n"
        "• 1 анализ — 299 ₽\n"
        "• 5 анализов — 990 ₽\n"
        "• Подписка на месяц (30 анализов) — 1490 ₽\n\n"
        "Оплата временно в тестовом режиме. Напиши @support"
    )

@dp.message(lambda message: message.text == "🎫 Ввести промокод")
async def promo(message: types.Message):
    await message.answer("🎫 Введи промокод:")

@dp.message(lambda message: message.text == "👤 Мой профиль")
async def profile(message: types.Message):
    await message.answer(
        "👤 Твой профиль:\n"
        "• Промо-анализы: 0/3\n"
        "• Купленные анализы: 0\n"
        "• Подписка: нет"
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_message(message: types.Message):
    await message.answer(
        "❓ Как пользоваться ботом:\n"
        "1. Нажми «Анализ объявления»\n"
        "2. Отправь ссылку на объявление с Avito.ru\n"
        "3. Получи полный разбор и улучшенный текст\n\n"
        "Есть вопросы? Пиши @support"
    )

# Запуск бота
async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
