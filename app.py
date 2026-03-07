import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Токен берется из переменных окружения на Render
import os
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
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
        WHERE user_id = ? ORDER BY created_at DESC LIMIT 10
    ''', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

# ---------- Машина состояний (опросник) ----------
class Form(StatesGroup):
    waiting_for_niche = State()
    waiting_for_product = State()
    waiting_for_audience = State()
    waiting_for_advantages = State()
    waiting_for_input_text = State()

# ---------- Команда /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "👋 Привет! Я помогу создать продающее объявление для Авито.\n\n"
        "📝 Я задам несколько вопросов, а потом сгенерирую текст.\n\n"
        "Какая у вас **ниша**? (например: стройматериалы, сантехника, услуги)"
    )
    await state.set_state(Form.waiting_for_niche)

# ---------- Шаг 1: Ниша ----------
@dp.message(Form.waiting_for_niche)
async def process_niche(message: types.Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer("Что именно вы **продаёте**? (например: бой бетона, смесители, вывоз мусора)")
    await state.set_state(Form.waiting_for_product)

# ---------- Шаг 2: Товар/услуга ----------
@dp.message(Form.waiting_for_product)
async def process_product(message: types.Message, state: FSMContext):
    await state.update_data(product=message.text)
    await message.answer("Кто ваша **целевая аудитория**? (частники, юрлица, перекупы)")
    await state.set_state(Form.waiting_for_audience)

# ---------- Шаг 3: Аудитория ----------
@dp.message(Form.waiting_for_audience)
async def process_audience(message: types.Message, state: FSMContext):
    await state.update_data(audience=message.text)
    await message.answer("Какие у вас **преимущества** перед конкурентами? (например: доставка, скидки, гарантия, работа с юрлицами)")
    await state.set_state(Form.waiting_for_advantages)

# ---------- Шаг 4: Преимущества ----------
@dp.message(Form.waiting_for_advantages)
async def process_advantages(message: types.Message, state: FSMContext):
    await state.update_data(advantages=message.text)
    await message.answer(
        "📝 А теперь **напишите своими словами**, как вы обычно продаёте.\n"
        "Можно просто 2-3 предложения, как вы бы описали товар клиенту."
    )
    await state.set_state(Form.waiting_for_input_text)

# ---------- Шаг 5: Своими словами ----------
@dp.message(Form.waiting_for_input_text)
async def process_input_text(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    user_text = message.text
    
    await message.answer("⏳ Генерирую объявление... (пока без нейросети, просто шаблон)")
    
    # Здесь будет генерация через нейросеть
    # Пока делаем простой шаблон для теста
    result = generate_template_text(user_data, user_text)
    
    # Сохраняем в историю
    category = user_data.get('niche', 'разное')
    save_generation(message.from_user.id, f"{user_data['niche']} | {user_data['product']}", result, category)
    
    await message.answer(result)
    await message.answer(
        "✅ Готово!\n\n"
        "Хотите **ещё вариант**? Просто напишите /start\n"
        "Посмотреть историю: /history"
    )
    await state.clear()

# ---------- Шаблонный генератор (для теста) ----------
def generate_template_text(data, user_text):
    niche = data.get('niche', 'товары')
    product = data.get('product', 'товар')
    audience = data.get('audience', 'клиенты')
    advantages = data.get('advantages', '')
    
    # Определяем аудиторию
    if 'частник' in audience.lower() or 'дач' in audience.lower():
        audience_block = "🏠 Для дома и дачи\n✅ Недорого\n✅ Можно немного"
    elif 'юрлиц' in audience.lower() or 'компани' in audience.lower():
        audience_block = "🏢 Для бизнеса\n✅ Работаем по договору\n✅ Безналичный расчёт\n✅ Закрывающие документы"
    elif 'перекуп' in audience.lower() or 'опт' in audience.lower():
        audience_block = "📦 Оптовым клиентам\n✅ Скидки от объема\n✅ Постоянное наличие"
    else:
        audience_block = "👥 Для всех клиентов\n✅ Индивидуальный подход"
    
    # Преимущества
    if advantages:
        adv_list = [a.strip() for a in advantages.split(',')]
        adv_block = "\n".join([f"✅ {adv}" for adv in adv_list if adv])
    else:
        adv_block = ""
    
    # Формируем заголовок
    title = f"{product} | {niche}"
    
    # Формируем оффер (первые строки)
    offer = f"{product} отличного качества. {audience_block.split(chr(10))[0]}"
    
    # Собираем всё вместе
    result = f"""📢 **{title}**

{offer}

**Что предлагаем:**
✅ {product}
✅ {niche}
{audience_block}
{adv_block}

**Почему выбирают нас:**
✅ Быстрая обратная связь
✅ Работаем честно и прозрачно
✅ Индивидуальный подход к каждому клиенту

📞 **Звоните или пишите!** Проконсультирую по любым вопросам.

---
*Сгенерировано ботом на основе вашего описания:*  
_{user_text[:100]}..._"""
    
    return result

# ---------- Команда /history ----------
@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    history = get_user_history(message.from_user.id)
    
    if not history:
        await message.answer("У вас пока нет сохранённых генераций.")
        return
    
    response = "📚 **Ваши последние генерации:**\n\n"
    for i, (user_input, gen_text, date) in enumerate(history, 1):
        date_formatted = date.split('T')[0]  # берём только дату
        preview = gen_text[:100] + "..." if len(gen_text) > 100 else gen_text
        response += f"{i}. _{date_formatted}_: {user_input}\n   `{preview}`\n\n"
    
    await message.answer(response)

# ---------- Запуск бота ----------
async def main():
    # Инициализируем базу данных
    init_db()
    
    # Запускаем бота
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
