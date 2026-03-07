import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import os
import requests
from aiohttp import web

# Токен из переменных окружения
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения")

# Ключ OpenRouter из переменных окружения
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY не задан в переменных окружения")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---------- База данных ----------
def init_db():
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_input TEXT,
            generated_text TEXT,
            category TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_generation(user_id, user_input, generated_text, category):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO generations (user_id, user_input, generated_text, category, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, user_input, generated_text, category, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_history(user_id):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT user_input, generated_text, created_at FROM generations
        WHERE user_id = ? ORDER BY created_at DESC LIMIT 5
    ''', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

# ---------- Машина состояний ----------
class Form(StatesGroup):
    waiting_for_url = State()           # Шаг 1: ссылка на объявление
    waiting_for_niche = State()          # Шаг 2: ниша
    waiting_for_product = State()        # Шаг 3: товар
    waiting_for_audience = State()       # Шаг 4: аудитория
    waiting_for_advantages = State()     # Шаг 5: преимущества

# ---------- Генерация с анализом объявления ----------
async def analyze_and_generate(url, user_data):
    niche = user_data.get('niche', 'товары')
    product = user_data.get('product', 'товар')
    audience = user_data.get('audience', 'клиенты')
    advantages = user_data.get('advantages', '')
    
    logger.info(f"=== АНАЛИЗ ОБЪЯВЛЕНИЯ ===")
    logger.info(f"URL: {url}")
    
    # ШАГ 1: Анализ объявления
    analysis_prompt = f"""Ты профессиональный маркетолог и копирайтер. Проанализируй объявление по ссылке: {url}

Напиши краткий анализ по пунктам:
1. Сильные стороны объявления
2. Слабые стороны (что можно улучшить)
3. Что отсутствует (цена, доставка, гарантии и т.д.)
4. Насколько заголовок цепляет
5. Общая оценка от 1 до 10"""
    
    # ШАГ 2: Генерация нового объявления
    generation_prompt = f"""На основе анализа создай новое, улучшенное объявление для Авито.

ИСХОДНЫЕ ДАННЫЕ:
- Ниша: {niche}
- Товар/услуга: {product}
- Целевая аудитория: {audience}
- Преимущества: {advantages}

ТРЕБОВАНИЯ К НОВОМУ ОБЪЯВЛЕНИЮ:
1. Заголовок (цепляющий, с ключевыми словами)
2. Краткое вступление (1-2 предложения)
3. Список того, что предлагаете (с эмодзи ✅) — минимум 5 пунктов
4. Почему выбирают вас (с эмодзи ⭐️) — минимум 3 пункта
5. Цена и условия доставки (если есть)
6. Призыв к действию
7. Фраза "Добавьте в избранное" в конце

Используй лучшие практики из анализа, исправь слабые места."""
    
    try:
        API_URL = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/avito_copywriter_bot",
            "X-Title": "Avito Copywriter Bot"
        }
        loop = asyncio.get_event_loop()
        
        # Получаем анализ
        logger.info("Анализирую объявление...")
        payload1 = {
            "model": "gryphe/mythomax-l2-13b:free",
            "messages": [
                {"role": "system", "content": "Ты профессиональный маркетолог и копирайтер."},
                {"role": "user", "content": analysis_prompt}
            ],
            "max_tokens": 800,
            "temperature": 0.5
        }
        response1 = await loop.run_in_executor(
            None, 
            lambda: requests.post(API_URL, headers=headers, json=payload1, timeout=30)
        )
        
        if response1.status_code != 200:
            raise Exception(f"Анализ не удался: {response1.status_code}")
        
        analysis = response1.json()['choices'][0]['message']['content']
        logger.info(f"Анализ получен: {len(analysis)} символов")
        
        # Генерируем новое объявление
        logger.info("Генерирую улучшенное объявление...")
        payload2 = {
            "model": "gryphe/mythomax-l2-13b:free",
            "messages": [
                {"role": "system", "content": "Ты профессиональный копирайтер для Авито. Создавай продающие объявления."},
                {"role": "user", "content": f"Проанализированное объявление:\n{analysis}\n\n{generation_prompt}"}
            ],
            "max_tokens": 2000,
            "temperature": 0.7
        }
        
        response2 = await loop.run_in_executor(
            None, 
            lambda: requests.post(API_URL, headers=headers, json=payload2, timeout=60)
        )
        
        if response2.status_code == 200:
            result = response2.json()
            final_text = result['choices'][0]['message']['content']
            logger.info(f"✅ Финальный текст получен: {len(final_text)} символов")
            return final_text
        else:
            logger.error(f"❌ Ошибка OpenRouter: {response2.status_code} - {response2.text}")
            return "❌ Ошибка генерации. Попробуйте позже."
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА ПРИ ГЕНЕРАЦИИ: {e}")
        return "❌ Ошибка нейросети. Попробуйте позже."

# ---------- Команда /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "👋 Привет! Я помогу проанализировать твоё объявление и создать улучшенный вариант.\n\n"
        "📝 Отправь мне **ссылку на твоё объявление на Авито**"
    )
    await state.set_state(Form.waiting_for_url)

# ---------- Шаг 1: Ссылка на объявление ----------
@dp.message(Form.waiting_for_url)
async def process_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    
    # Простейшая проверка, что это ссылка на Авито
    if 'avito.ru' not in url:
        await message.answer("❌ Это не похоже на ссылку на Авито. Попробуй ещё раз.")
        return
    
    await state.update_data(url=url)
    await message.answer("Какая у вас **ниша**? (например: стройматериалы, сантехника, услуги)")
    await state.set_state(Form.waiting_for_niche)

# ---------- Шаг 2: Ниша ----------
@dp.message(Form.waiting_for_niche)
async def process_niche(message: types.Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer("Что именно вы **продаёте**? (например: бой бетона, смесители, вывоз мусора)")
    await state.set_state(Form.waiting_for_product)

# ---------- Шаг 3: Товар/услуга ----------
@dp.message(Form.waiting_for_product)
async def process_product(message: types.Message, state: FSMContext):
    await state.update_data(product=message.text)
    await message.answer("Кто ваша **целевая аудитория**? (частники, юрлица, перекупы)")
    await state.set_state(Form.waiting_for_audience)

# ---------- Шаг 4: Аудитория ----------
@dp.message(Form.waiting_for_audience)
async def process_audience(message: types.Message, state: FSMContext):
    await state.update_data(audience=message.text)
    await message.answer("Какие у вас **преимущества** перед конкурентами? (например: доставка, скидки, гарантия, работа с юрлицами)")
    await state.set_state(Form.waiting_for_advantages)

# ---------- Шаг 5: Преимущества (финальный) ----------
@dp.message(Form.waiting_for_advantages)
async def process_advantages(message: types.Message, state: FSMContext):
    await state.update_data(advantages=message.text)
    user_data = await state.get_data()
    
    await message.answer("⏳ Анализирую объявление и генерирую улучшенный вариант... (может занять до 1 минуты)")
    
    # Генерация с анализом
    result = await analyze_and_generate(user_data['url'], user_data)
    
    # Сохраняем в историю
    category = user_data.get('niche', 'разное')
    save_generation(
        message.from_user.id, 
        f"{user_data['niche']} | {user_data['product']}", 
        result, 
        category
    )
    
    await message.answer(result)
    await message.answer(
        "✅ Готово!\n\n"
        "Хотите ещё вариант? Просто напишите /start\n"
        "Посмотреть историю: /history"
    )
    await state.clear()

# ---------- Команда /history ----------
@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    history = get_user_history(message.from_user.id)
    
    if not history:
        await message.answer("У вас пока нет сохранённых генераций.")
        return
    
    await message.answer("📚 Ваши последние генерации:")
    
    for i, (user_input, gen_text, date) in enumerate(history, 1):
        date_formatted = date.split('T')[0]
        response = f"📄 Генерация #{i} от {date_formatted}\n\n{gen_text}"
        await message.answer(response)

# ---------- Веб-сервер для Render ----------
async def handle(request):
    return web.Response(text="Бот работает!")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    app.router.add_get('/health', handle)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {port}")

# ---------- Запуск ----------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Вебхук удалён")
    
    init_db()
    asyncio.create_task(run_web_server())
    
    logger.info("Бот запущен и готов к работе с анализом объявлений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
