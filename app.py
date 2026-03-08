import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
import os

# Токен
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_IDS = [867292164]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- Веб-сервер для Render ---
async def handle(request):
    return web.Response(text="OK")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    app.router.add_get('/health', handle)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌐 Веб-сервер для хелсчеков на {port}")

# ---------- База данных (твоя без изменений) ----------
def init_db():
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            promo_analyses INTEGER DEFAULT 0,
            bought_analyses INTEGER DEFAULT 0,
            subscription_end DATE,
            created_at TEXT
        )
    ''')
    
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
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS promo_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            user_id INTEGER,
            used_at TEXT
        )
    ''')
    
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

# ---------- Функции пользователей (твои без изменений) ----------
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
    
    cur.execute('SELECT promo_analyses FROM users WHERE user_id = ?', (user_id,))
    promo = cur.fetchone()
    if promo and promo[0] > 0:
        cur.execute('UPDATE users SET promo_analyses = promo_analyses - 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return True, "promo"
    
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

# ---------- Функции промокодов (твои без изменений) ----------
def check_promo_code(code, user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    cur.execute('''
        SELECT analyses_count, max_uses, used_count, expires_at 
        FROM promo_codes WHERE code = ?
    ''', (code,))
    promo = cur.fetchone()
    
    if not promo:
        conn.close()
        return False, "Код не найден"
    
    analyses_count, max_uses, used_count, expires_at = promo
    
    if expires_at and datetime.now().date() > datetime.fromisoformat(expires_at).date():
        conn.close()
        return False, "Срок действия кода истёк"
    
    if used_count >= max_uses:
        conn.close()
        return False, "Код уже использован максимальное количество раз"
    
    cur.execute('SELECT * FROM promo_uses WHERE code = ? AND user_id = ?', (code, user_id))
    if cur.fetchone():
        conn.close()
        return False, "Вы уже использовали этот код"
    
    conn.close()
    return True, analyses_count

def activate_promo_code(code, user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    
    cur.execute('SELECT analyses_count FROM promo_codes WHERE code = ?', (code,))
    analyses_count = cur.fetchone()[0]
    
    cur.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?', (code,))
    cur.execute('''
        INSERT INTO promo_uses (code, user_id, used_at)
        VALUES (?, ?, ?)
    ''', (code, user_id, datetime.now().isoformat()))
    add_promo_analyses(user_id, analyses_count)
    
    conn.commit()
    conn.close()

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

# ---------- Кнопки ----------
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

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Анализ объявления")],
        [KeyboardButton(text="📊 Мои отчёты"), KeyboardButton(text="💎 Купить анализы")],
        [KeyboardButton(text="🎫 Ввести промокод"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

admin_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список промокодов")],
        [KeyboardButton(text="➕ Создать промокод")],
        [KeyboardButton(text="❌ Удалить промокод")],
        [KeyboardButton(text="🏠 Главное меню")]
    ],
    resize_keyboard=True
)

# ---------- Состояния для FSM ----------
class PromoForm(StatesGroup):
    code = State()
    analyses = State()
    max_uses = State()
    days = State()

# ---------- Команды и кнопки (твои, без изменений) ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    create_user(user_id)
    await message.answer(
        "👋 Привет! Я помогу проанализировать твоё объявление на Авито и сделать его лучше.\n\n"
        "Выбери действие:",
        reply_markup=main_menu
    )

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    await message.answer("👨‍💻 Админ-панель\nУправление промокодами:", reply_markup=admin_menu)

@dp.message(lambda message: message.text == "🔍 Анализ объявления")
async def analyze_start(message: types.Message):
    user_id = message.from_user.id
    create_user(user_id)
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
    await message.answer("📊 История анализов пока пуста. Скоро здесь появятся твои отчёты.", reply_markup=main_menu)

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

# ---------- Создание промокода (пошаговое) ----------
@dp.message(lambda message: message.text == "➕ Создать промокод")
async def admin_create_promo_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("🔤 Введи **название промокода** (например: PROMO10):")
    await state.set_state(PromoForm.code)

@dp.message(PromoForm.code)
async def admin_create_promo_code(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    if not code.isalnum():
        await message.answer("❌ Код должен содержать только буквы и цифры. Попробуй ещё раз:")
        return
    await state.update_data(code=code)
    await message.answer("🔢 Введи **количество анализов**, которые даёт промокод (например: 3):")
    await state.set_state(PromoForm.analyses)

@dp.message(PromoForm.analyses)
async def admin_create_promo_analyses(message: types.Message, state: FSMContext):
    try:
        analyses = int(message.text.strip())
        if analyses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи **положительное число**. Попробуй ещё раз:")
        return
    await state.update_data(analyses=analyses)
    await message.answer("🔢 Введи **максимальное количество использований** (например: 5):")
    await state.set_state(PromoForm.max_uses)

@dp.message(PromoForm.max_uses)
async def admin_create_promo_max_uses(message: types.Message, state: FSMContext):
    try:
        max_uses = int(message.text.strip())
        if max_uses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи **положительное число**. Попробуй ещё раз:")
        return
    await state.update_data(max_uses=max_uses)
    await message.answer("📅 Введи **срок действия в днях** (0 — бессрочно, например: 30):")
    await state.set_state(PromoForm.days)

@dp.message(PromoForm.days)
async def admin_create_promo_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи **неотрицательное число** (0 или больше). Попробуй ещё раз:")
        return
    data = await state.get_data()
    create_promo_code(
        code=data['code'],
        analyses_count=data['analyses'],
        max_uses=data['max_uses'],
        expires_at_days=days if days > 0 else None,
        admin_id=message.from_user.id
    )
    await message.answer(
        f"✅ Промокод **{data['code']}** создан!\n"
        f"• {data['analyses']} анализов\n"
        f"• максимум {data['max_uses']} использований\n"
        f"• {'бессрочно' if days == 0 else f'{days} дней'}",
        reply_markup=admin_menu
    )
    await state.clear()

@dp.message(lambda message: message.text == "❌ Удалить промокод")
async def admin_delete_promo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Введи код для удаления:")

@dp.message(lambda message: message.from_user.id in ADMIN_IDS and len(message.text) < 20 and message.text not in BUTTON_TEXTS and not message.text.startswith('/'))
async def admin_delete_promo_execute(message: types.Message):
    code = message.text.strip().upper()
    deactivate_promo_code(code)
    await message.answer(f"✅ Промокод {code} удалён", reply_markup=admin_menu)

@dp.message(lambda message: message.from_user.id not in ADMIN_IDS and len(message.text) < 20 and message.text not in BUTTON_TEXTS and not message.text.startswith('/'))
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

@dp.message(lambda message: 'avito.ru' in message.text)
async def handle_url(message: types.Message):
    user_id = message.from_user.id
    url = message.text.strip()
    
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
    await asyncio.sleep(2)
    await message.answer(
        "📊 Анализ завершён (тестовая версия)\n\n"
        "Полноценный анализ будет добавлен в следующем обновлении.",
        reply_markup=main_menu
    )

@dp.message()
async def unknown_message(message: types.Message):
    await message.answer(
        "Я не понимаю эту команду. Используй кнопки меню или /start",
        reply_markup=main_menu
    )

# ---------- ЗАПУСК ----------
async def main():
    logger.info("Запускаю сервер...")
    
    # Сначала удаляем вебхук (на всякий случай)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Вебхук удалён")
    
    # Инициализируем базу
    init_db()
    logger.info("База данных инициализирована")
    
    # Запускаем веб-сервер для Render в фоне
    asyncio.create_task(run_web_server())
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    logger.info(f"✅ Бот @{bot_info.username} готов")
    
    # Запускаем бота (polling)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
