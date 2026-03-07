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

# Токен Hugging Face из переменных окружения
HF_TOKEN = os.environ.get("HF_TOKEN")
if not HF_TOKEN:
    raise ValueError("HF_TOKEN не задан в переменных окружения")

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
    waiting_for_niche = State()
    waiting_for_product = State()
    waiting_for_audience = State()
    waiting_for_advantages = State()
    waiting_for_input_text = State()

# ---------- Генерация через YandexGPT (с заголовком X-Use-Tasks) ----------
async def generate_with_ai(user_data, user_text):
    niche = user_data.get('niche', 'товары')
    product = user_data.get('product', 'товар')
    audience = user_data.get('audience', 'клиенты')
    advantages = user_data.get('advantages', '')
    
    logger.info(f"=== НАЧАЛО ГЕНЕРАЦИИ ===")
    logger.info(f"Товар: {product}, Ниша: {niche}, Аудитория: {audience}")
    
    # Формируем промпт в формате, который понимает YandexGPT
    prompt = f"""Ты профессиональный копирайтер для Авито. Создай продающее объявление.

НИША: {niche}
ТОВАР/УСЛУГА: {product}
ЦЕЛЕВАЯ АУДИТОРИЯ: {audience}
ПРЕИМУЩЕСТВА: {advantages}
ОПИСАНИЕ ПРОДАВЦА: {user_text}

ТРЕБОВАНИЯ К ОБЪЯВЛЕНИЮ:
1. Заголовок должен отражать главную потребность клиента
2. В описании используй живые формулировки
3. Добавь эмодзи для структуры (✅, ⭐️, ☑️)
4. В конце добавь призыв к действию
5. Фраза "Добавьте в избранное" в конце

Используй живые формулировки, как в разговоре с клиентом.

Ассистент:[SEP]"""
    
    try:
        API_URL = "https://api-inference.huggingface.co/models/yandex/YandexGPT-5-Lite-8B-instruct"
        headers = {
            "Authorization": f"Bearer {HF_TOKEN}",
            "Content-Type": "application/json",
            "X-Use-Tasks": "text-generation"  # Критически важный заголовок!
        }
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 2500,
                "temperature": 0.5,
                "top_p": 0.9,
                "do_sample": True,
                "return_full_text": False
            }
        }
        
        logger.info("Отправляю запрос к Hugging Face Inference API...")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: requests.post(API_URL, headers=headers, json=payload, timeout=60)
        )
        
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                final_text = result[0].get('generated_text', '')
                final_text = final_text.replace('</s>', '').strip()
                logger.info(f"✅ Финальный текст получен: {len(final_text)} символов")
                return final_text
            else:
                logger.error(f"Странный ответ API: {result}")
                return generate_template_text(user_data, user_text)
        elif response.status_code == 401:
            logger.error("❌ Ошибка авторизации. Токен недействителен.")
            return "❌ Ошибка авторизации нейросети. Проверьте токен Hugging Face."
        else:
            logger.error(f"❌ Ошибка API: {response.status_code} - {response.text}")
            return generate_template_text(user_data, user_text)
        
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе к API")
        return generate_template_text(user_data, user_text)
    except Exception as e:
        logger.error(f"❌ ОШИБКА ПРИ ГЕНЕРАЦИИ: {e}")
        return generate_template_text(user_data, user_text)

# ---------- Шаблонный генератор (запасной) ----------
def generate_template_text(data, user_text):
    niche = data.get('niche', 'товары')
    product = data.get('product', 'товар')
    audience = data.get('audience', 'клиенты')
    advantages = data.get('advantages', '')
    
    if niche.lower() == product.lower():
        title = f"{product}"
    else:
        title = f"{product} | {niche}"
    
    if 'частник' in audience.lower() or 'дач' in audience.lower():
        audience_block = "🏠 Для дома и дачи\n✅ Недорого\n✅ Можно немного"
    elif 'юрлиц' in audience.lower() or 'компани' in audience.lower():
        audience_block = "🏢 Для бизнеса\n✅ Работаем по договору\n✅ Безналичный расчёт\n✅ Закрывающие документы"
    elif 'перекуп' in audience.lower() or 'опт' in audience.lower():
        audience_block = "📦 Оптовым клиентам\n✅ Скидки от объема\n✅ Постоянное наличие"
    else:
        audience_block = "👥 Для всех клиентов\n✅ Индивидуальный подход"
    
    if advantages:
        adv_list = [a.strip() for a in advantages.split(',')]
        adv_block = "\n".join([f"✅ {adv}" for adv in adv_list if adv])
    else:
        adv_block = ""
    
    result = f"""📢 {title}

{product} отличного качества. {audience_block.split(chr(10))[0]}

Что предлагаем:
✅ {product}
{audience_block}
{adv_block}

Почему выбирают нас:
✅ Быстрая обратная связь
✅ Работаем честно и прозрачно
✅ Индивидуальный подход

📞 Звоните или пишите! Проконсультирую по любым вопросам.

---
На основе вашего описания:
{user_text}"""
    
    return result

# ---------- Команда /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "👋 Привет! Я помогу создать продающее объявление для Авито.\n\n"
        "📝 Я задам несколько вопросов, а потом сгенерирую текст с помощью нейросети YandexGPT.\n\n"
        "Какая у вас ниша? (например: стройматериалы, сантехника, услуги)"
    )
    await state.set_state(Form.waiting_for_niche)

# ---------- Шаг 1: Ниша ----------
@dp.message(Form.waiting_for_niche)
async def process_niche(message: types.Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer("Что именно вы продаёте? (например: бой бетона, смесители, вывоз мусора)")
    await state.set_state(Form.waiting_for_product)

# ---------- Шаг 2: Товар/услуга ----------
@dp.message(Form.waiting_for_product)
async def process_product(message: types.Message, state: FSMContext):
    await state.update_data(product=message.text)
    await message.answer("Кто ваша целевая аудитория? (частники, юрлица, перекупы)")
    await state.set_state(Form.waiting_for_audience)

# ---------- Шаг 3: Аудитория ----------
@dp.message(Form.waiting_for_audience)
async def process_audience(message: types.Message, state: FSMContext):
    await state.update_data(audience=message.text)
    await message.answer("Какие у вас преимущества перед конкурентами? (например: доставка, скидки, гарантия, работа с юрлицами)")
    await state.set_state(Form.waiting_for_advantages)

# ---------- Шаг 4: Преимущества ----------
@dp.message(Form.waiting_for_advantages)
async def process_advantages(message: types.Message, state: FSMContext):
    await state.update_data(advantages=message.text)
    await message.answer(
        "📝 А теперь напишите своими словами, как вы обычно продаёте.\n"
        "Можно просто 2-3 предложения, как вы бы описали товар клиенту."
    )
    await state.set_state(Form.waiting_for_input_text)

# ---------- Шаг 5: Своими словами ----------
@dp.message(Form.waiting_for_input_text)
async def process_input_text(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    user_text = message.text
    
    await message.answer("⏳ Генерирую объявление с помощью YandexGPT... (может занять до 1 минуты)")
    
    # Используем нейросеть с правильным эндпоинтом и заголовком
    result = await generate_with_ai(user_data, user_text)
    
    category = user_data.get('niche', 'разное')
    save_generation(message.from_user.id, f"{user_data['niche']} | {user_data['product']}", result, category)
    
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
    # Принудительно сбрасываем все вебхуки
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Вебхук удалён")
    
    init_db()
    asyncio.create_task(run_web_server())
    
    logger.info("Бот запущен и готов к работе с YandexGPT!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
