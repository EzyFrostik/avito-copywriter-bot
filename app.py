import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import os

# Токен из переменных окружения (исправлено: TELEGRAM_TOKEN)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_IDS = [867292164]  # ТВОЙ Telegram ID

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота (сессия будет создана позже)
bot = None
dp = Dispatcher()

# ---------- База данных ----------
def init_db():
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    # Таблица пользователей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            promo_analyses INTEGER DEFAULT 0,
            bought_analyses INTEGER DEFAULT 0,
            subscription_end DATE,
            created_at TEXT
        )
    ''')
    
    # Таблица промокодов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            analyses_count INTEGER DEFAULT 3,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            expires_at DATE,
            created_by INTEGER,
            created_at TEXT
        )
    ''')
    
    # Таблица использований промокодов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS promo_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            user_id INTEGER,
            used_at TEXT
        )
    ''')
    
    # Таблица анализов (история)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            url TEXT,
            report TEXT,
            created_at TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# ---------- Функции для работы с пользователями ----------
def get_user(user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cur.fetchone()
    conn.close()
    return user

def create_user(user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('''
        INSERT OR IGNORE INTO users (user_id, promo_analyses, bought_analyses, created_at)
        VALUES (?, 0, 0, ?)
    ''', (user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def use_analysis(user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    # Сначала проверяем промо-анализы
    cur.execute('SELECT promo_analyses FROM users WHERE user_id = ?', (user_id,))
    promo = cur.fetchone()
    
    if promo and promo[0] > 0:
        cur.execute('UPDATE users SET promo_analyses = promo_analyses - 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return True, "promo"
    
    # Потом купленные
    cur.execute('SELECT bought_analyses FROM users WHERE user_id = ?', (user_id,))
    bought = cur.fetchone()
    
    if bought and bought[0] > 0:
        cur.execute('UPDATE users SET bought_analyses = bought_analyses - 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return True, "bought"
    
    conn.close()
    return False, None

def add_promo_analyses(user_id, count):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('UPDATE users SET promo_analyses = promo_analyses + ? WHERE user_id = ?', (count, user_id))
    conn.commit()
    conn.close()

# ---------- Функции для промокодов ----------
def check_promo_code(code, user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    # Проверяем, существует ли код
    cur.execute('''
        SELECT analyses_count, max_uses, used_count, expires_at 
        FROM promo_codes WHERE code = ?
    ''', (code,))
    promo = cur.fetchone()
    
    if not promo:
        conn.close()
        return False, "Код не найден"
    
    analyses_count, max_uses, used_count, expires_at = promo
    
    # Проверяем срок действия
    if expires_at and datetime.now().date() > datetime.fromisoformat(expires_at).date():
        conn.close()
        return False, "Срок действия кода истёк"
    
    # Проверяем лимит использований
    if used_count >= max_uses:
        conn.close()
        return False, "Код уже использован максимальное количество раз"
    
    # Проверяем, не использовал ли этот пользователь код
    cur.execute('SELECT * FROM promo_uses WHERE code = ? AND user_id = ?', (code, user_id))
    if cur.fetchone():
        conn.close()
        return False, "Вы уже использовали этот код"
    
    conn.close()
    return True, analyses_count

def activate_promo_code(code, user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    # Получаем количество анализов
    cur.execute('SELECT analyses_count FROM promo_codes WHERE code = ?', (code,))
    analyses_count = cur.fetchone()[0]
    
    # Обновляем счётчик использований
    cur.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?', (code,))
    
    # Записываем использование
    cur.execute('''
        INSERT INTO promo_uses (code, user_id, used_at)
        VALUES (?, ?, ?)
    ''', (code, user_id, datetime.now().isoformat()))
    
    # Начисляем анализы пользователю
    add_promo_analyses(user_id, analyses_count)
    
    conn.commit()
    conn.close()

# ---------- Админ-функции ----------
def create_promo_code(code, analyses_count, max_uses, expires_at_days, admin_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    expires_at = (datetime.now() + timedelta(days=expires_at_days)).date().isoformat() if expires_at_days else None
    
    cur.execute('''
        INSERT INTO promo_codes (code, analyses_count, max_uses, expires_at, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (code.upper(), analyses_count, max_uses, expires_at, admin_id, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def get_all_promo_codes():
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('SELECT code, analyses_count, max_uses, used_count, expires_at FROM promo_codes ORDER BY created_at DESC')
    codes = cur.fetchall()
    conn.close()
    return codes

def deactivate_promo_code(code):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('DELETE FROM promo_codes WHERE code = ?', (code.upper(),))
    conn.commit()
    conn.close()

# ---------- Список всех текстов кнопок для фильтрации ----------
BUTTON_TEXTS = [
    "🔍 Анализ объявления",
    "📊 Мои отчёты",
    "💎 Купить анализы",
    "🎫 Ввести промокод",
    "👤 Мой профиль",
    "❓ Помощь",
    "📋 Список промокодов",
    "➕ Создать промокод",
    "❌ Удалить промокод",
    "🏠 Главное меню"
]

# ---------- Клавиатуры ----------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Анализ объявления")],
        [KeyboardButton(text="📊 Мои отчёты"), KeyboardButton(text="💎 Купить анализы")],
        [KeyboardButton(text="🎫 Ввести промокод"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# Админ-клавиатура
admin_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список промокодов")],
        [KeyboardButton(text="➕ Создать промокод")],
        [KeyboardButton(text="❌ Удалить промокод")],
        [KeyboardButton(text="🏠 Главное меню")]
    ],
    resize_keyboard=True
)

# ---------- Команда /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    create_user(user_id)
    
    await message.answer(
        "👋 Привет! Я помогу проанализировать твоё объявление на Авито и сделать его лучше.\n\n"
        "Выбери действие:",
        reply_markup=main_menu
    )

# ---------- Админ-панель ----------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    await message.answer(
        "👨‍💻 Админ-панель\n"
        "Управление промокодами:",
        reply_markup=admin_menu
    )

# ---------- Обработчики кнопок главного меню ----------
@dp.message(lambda message: message.text == "🔍 Анализ объявления")
async def analyze_start(message: types.Message):
    user_id = message.from_user.id
    create_user(user_id)
    
    # Проверяем наличие анализов
    user = get_user(user_id)
    promo = user[1] if user else 0
    bought = user[2] if user else 0
    subscription = user[3] if user else None
    
    if promo > 0 or bought > 0 or (subscription and datetime.now().date() <= datetime.fromisoformat(subscription).date()):
        await message.answer("🔗 Отправь мне ссылку на твоё объявление на Авито")
    else:
        await message.answer(
            "❌ У тебя нет доступных анализов.\n\n"
            "• Введи промокод 🎫\n"
            "• Или купи анализы 💎",
            reply_markup=main_menu
        )

@dp.message(lambda message: message.text == "🎫 Ввести промокод")
async def promo_start(message: types.Message):
    await message.answer("🎫 Введи промокод:")

@dp.message(lambda message: message.text == "💎 Купить анализы")
async def buy_analyses(message: types.Message):
    await message.answer(
        "💎 Тарифы (оплата временно в тестовом режиме):\n\n"
        "• 1 анализ — 299 ₽\n"
        "• 5 анализов — 990 ₽\n"
        "• Подписка на месяц (30 анализов) — 1490 ₽\n\n"
        "Для покупки напиши @support",
        reply_markup=main_menu
    )

@dp.message(lambda message: message.text == "👤 Мой профиль")
async def profile(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if not user:
        create_user(user_id)
        user = get_user(user_id)
    
    promo = user[1] if user else 0
    bought = user[2] if user else 0
    subscription = user[3] if user else None
    
    sub_text = f"до {subscription}" if subscription else "нет"
    
    await message.answer(
        f"👤 Твой профиль:\n"
        f"• Промо-анализы: {promo}/3\n"
        f"• Купленные анализы: {bought}\n"
        f"• Подписка: {sub_text}",
        reply_markup=main_menu
    )

@dp.message(lambda message: message.text == "📊 Мои отчёты")
async def my_reports(message: types.Message):
    await message.answer(
        "📊 История анализов пока пуста. Скоро здесь появятся твои отчёты.",
        reply_markup=main_menu
    )

@dp.message(lambda message: message.text == "❓ Помощь")
async def help_message(message: types.Message):
    await message.answer(
        "❓ Как пользоваться ботом:\n"
        "1. Нажми «Анализ объявления»\n"
        "2. Отправь ссылку на объявление с Avito.ru\n"
        "3. Получи полный разбор и улучшенный текст\n\n"
        "Есть вопросы? Пиши https://t.me/EzyFrost",
        reply_markup=main_menu
    )

# ---------- Обработчики кнопок админ-меню ----------
@dp.message(lambda message: message.text == "📋 Список промокодов")
async def admin_list_promos(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    codes = get_all_promo_codes()
    if not codes:
        await message.answer("📭 Промокодов пока нет", reply_markup=admin_menu)
        return
    
    text = "📋 Список промокодов:\n\n"
    for code, analyses, max_uses, used, expires in codes:
        expires_str = expires if expires else "бессрочно"
        text += f"• {code}: {analyses} ан., {used}/{max_uses} исп., до {expires_str}\n"
    
    await message.answer(text, reply_markup=admin_menu)

@dp.message(lambda message: message.text == "➕ Создать промокод")
async def admin_create_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer(
        "Введи параметры промокода в формате:\n"
        "`КОД КОЛИЧЕСТВО_АНАЛИЗОВ МАКС_ИСПОЛЬЗОВАНИЙ ДНЕЙ_ДЕЙСТВИЯ`\n\n"
        "Пример: `PROMO10 3 5 30` — код PROMO10 на 3 анализа, 5 использований, 30 дней\n\n"
        "Если дней = 0 — бессрочный"
    )

@dp.message(lambda message: message.text == "❌ Удалить промокод")
async def admin_delete_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("Введи код для удаления:")

@dp.message(lambda message: message.text == "🏠 Главное меню")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu)

# ---------- Обработчик ссылок на Авито ----------
@dp.message(lambda message: 'avito.ru' in message.text)
async def handle_url(message: types.Message):
    user_id = message.from_user.id
    url = message.text.strip()
    
    # Проверяем наличие анализов
    result, _ = use_analysis(user_id)
    if not result:
        await message.answer(
            "❌ У тебя нет доступных анализов.\n\n"
            "• Введи промокод 🎫\n"
            "• Или купи анализы 💎",
            reply_markup=main_menu
        )
        return
    
    await message.answer(
        f"✅ Ссылка принята!\n"
        f"Начинаю анализ: {url}\n\n"
        f"⏳ Это займёт около минуты..."
    )
    
    # Здесь будет вызов нейросети
    # Пока просто заглушка
    await asyncio.sleep(2)
    
    await message.answer(
        "📊 Анализ завершён (тестовая версия)\n\n"
        "Полноценный анализ будет добавлен в следующем обновлении.",
        reply_markup=main_menu
    )

# ---------- Обработчик ввода промокода (только для админа при создании) ----------
@dp.message(lambda message: message.from_user.id in ADMIN_IDS and 
            len(message.text.split()) == 4 and 
            message.text.split()[0].isalnum() and 
            message.text.split()[1].isdigit() and 
            message.text.split()[2].isdigit() and 
            message.text.split()[3].isdigit())
async def admin_create_promo_execute(message: types.Message):
    try:
        code, analyses, max_uses, days = message.text.split()
        analyses = int(analyses)
        max_uses = int(max_uses)
        days = int(days) if days != '0' else None
        
        create_promo_code(code.upper(), analyses, max_uses, days, message.from_user.id)
        await message.answer(f"✅ Промокод {code.upper()} создан!", reply_markup=admin_menu)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=admin_menu)

# ---------- Обработчик ввода кода для удаления (только для админа) ----------
@dp.message(lambda message: message.from_user.id in ADMIN_IDS and 
            len(message.text) < 20 and 
            message.text not in BUTTON_TEXTS and 
            not message.text.startswith('/'))
async def admin_delete_promo_execute(message: types.Message):
    code = message.text.strip().upper()
    deactivate_promo_code(code)
    await message.answer(f"✅ Промокод {code} удалён", reply_markup=admin_menu)

# ---------- Обработчик ввода промокода для обычных пользователей ----------
@dp.message(lambda message: message.from_user.id not in ADMIN_IDS and 
            len(message.text) < 20 and 
            message.text not in BUTTON_TEXTS and 
            not message.text.startswith('/'))
async def handle_promo(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip().upper()
    
    valid, result = check_promo_code(code, user_id)
    
    if valid:
        activate_promo_code(code, user_id)
        await message.answer(
            f"✅ Промокод активирован!\n"
            f"Тебе начислено {result} анализа(ов).\n\n"
            f"Можешь начинать анализ 🔍",
            reply_markup=main_menu
        )
    else:
        await message.answer(f"❌ {result}", reply_markup=main_menu)

# ---------- Обработчик всего остального (если вдруг что-то не распозналось) ----------
@dp.message()
async def unknown_message(message: types.Message):
    await message.answer(
        "Я не понимаю эту команду. Используй кнопки меню или /start",
        reply_markup=main_menu
    )

# ---------- Запуск ----------
async def main():
    global bot
    
    # Проверяем наличие токена
    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN не задан!")
        return
    
    # Создаём бота
    bot = Bot(token=TOKEN)
    
    # Жёсткий сброс всех подключений
    logger.info("Сбрасываю вебхук...")
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(2)
    
    # Закрываем старую сессию и создаём новую
    logger.info("Пересоздаю сессию...")
    await bot.close()
    await asyncio.sleep(1)
    
    # Создаём бота заново с новой сессией
    bot = Bot(token=TOKEN)
    
    logger.info("Вебхук удалён, сессия пересоздана")
    
    # Инициализация БД
    init_db()
    logger.info("База данных инициализирована")
    
    logger.info(f"✅ Бот запущен для @{bot.username}")
    
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
