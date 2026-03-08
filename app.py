import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

# ---------- SQLAlchemy для PostgreSQL ----------
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, Mapped, mapped_column
from sqlalchemy import select, delete, Integer, String, BigInteger, Text

# Токен и URL для вебхука
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")  # строка подключения к PostgreSQL
ADMIN_IDS = [867292164]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---------- ОТЛАДКА: показываем все входящие сообщения ----------
@dp.message()
async def debug_all_messages(message: types.Message):
    logger.info(f"🔍 Получено сообщение: text='{message.text}', from={message.from_user.id}, chat={message.chat.id}")
    # Не отвечаем, просто логируем

# ---------- Настройка PostgreSQL ----------
# Преобразуем обычный URL в асинхронный (меняем postgresql:// на postgresql+asyncpg://)
ASYNC_DB_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1) if DATABASE_URL else None

# Создаём движок и фабрику сессий
engine = None
async_session_maker = None

if ASYNC_DB_URL:
    engine = create_async_engine(ASYNC_DB_URL, echo=False, pool_size=10, max_overflow=20)
    async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("✅ Настроен движок PostgreSQL")
else:
    logger.error("❌ DATABASE_URL не задан!")

# Базовый класс для моделей
Base = declarative_base()

# Модель пользователя
class User(Base):
    __tablename__ = 'users'
    
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    promo_analyses: Mapped[int] = mapped_column(Integer, default=0)
    bought_analyses: Mapped[int] = mapped_column(Integer, default=0)
    subscription_end: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)

# Модель промокода
class PromoCode(Base):
    __tablename__ = 'promo_codes'
    
    code: Mapped[str] = mapped_column(String, primary_key=True)
    analyses_count: Mapped[int] = mapped_column(Integer, default=3)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[str] = mapped_column(String, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[str] = mapped_column(String)

# Модель использований промокодов
class PromoUse(Base):
    __tablename__ = 'promo_uses'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String)
    user_id: Mapped[int] = mapped_column(BigInteger)
    used_at: Mapped[str] = mapped_column(String)

# Модель анализов
class Analysis(Base):
    __tablename__ = 'analyses'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    url: Mapped[str] = mapped_column(String)
    report: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String)

# ---------- Инициализация БД ----------
async def init_db():
    if not engine:
        logger.error("❌ Нет подключения к БД")
        return
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Таблицы PostgreSQL созданы/проверены")

# ---------- Функции для работы с БД (исправленные) ----------
async def get_user(user_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()

async def create_user(user_id: int):
    async with async_session_maker() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                new_user = User(
                    user_id=user_id,
                    promo_analyses=0,
                    bought_analyses=0,
                    subscription_end=None,
                    created_at=datetime.now().isoformat()
                )
                session.add(new_user)
                await session.commit()
                logger.info(f"✅ Создан пользователь {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка создания пользователя {user_id}: {e}")
            await session.rollback()

async def use_analysis(user_id: int):
    async with async_session_maker() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                return False, None
            
            if user.promo_analyses > 0:
                user.promo_analyses -= 1
                await session.commit()
                return True, "promo"
            
            if user.bought_analyses > 0:
                user.bought_analyses -= 1
                await session.commit()
                return True, "bought"
            
            return False, None
        except Exception as e:
            logger.error(f"❌ Ошибка use_analysis для {user_id}: {e}")
            await session.rollback()
            return False, None

async def add_promo_analyses(user_id: int, count: int):
    async with async_session_maker() as session:
        try:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.promo_analyses += count
                await session.commit()
                logger.info(f"✅ Пользователю {user_id} начислено {count} промо-анализов")
        except Exception as e:
            logger.error(f"❌ Ошибка add_promo_analyses для {user_id}: {e}")
            await session.rollback()

async def check_promo_code(code: str, user_id: int):
    async with async_session_maker() as session:
        try:
            result = await session.execute(select(PromoCode).where(PromoCode.code == code))
            promo = result.scalar_one_or_none()
            
            if not promo:
                return False, "Код не найден"
            
            if promo.expires_at:
                try:
                    if datetime.now().date() > datetime.fromisoformat(promo.expires_at).date():
                        return False, "Срок действия кода истёк"
                except:
                    pass
            
            if promo.used_count >= promo.max_uses:
                return False, "Код уже использован максимальное количество раз"
            
            result = await session.execute(
                select(PromoUse).where(PromoUse.code == code, PromoUse.user_id == user_id)
            )
            if result.scalar_one_or_none():
                return False, "Вы уже использовали этот код"
            
            return True, promo.analyses_count
        except Exception as e:
            logger.error(f"❌ Ошибка проверки промокода {code}: {e}")
            return False, "Ошибка базы данных"

async def activate_promo_code(code: str, user_id: int):
    async with async_session_maker() as session:
        try:
            # Получаем промокод
            result = await session.execute(select(PromoCode).where(PromoCode.code == code))
            promo = result.scalar_one_or_none()
            
            if not promo:
                return False
            
            # Обновляем счётчик использований
            promo.used_count += 1
            
            # Записываем использование
            new_use = PromoUse(
                code=code,
                user_id=user_id,
                used_at=datetime.now().isoformat()
            )
            session.add(new_use)
            
            # Получаем пользователя
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            
            if user:
                user.promo_analyses += promo.analyses_count
            
            await session.commit()
            logger.info(f"✅ Промокод {code} активирован пользователем {user_id}, начислено {promo.analyses_count} анализов")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка активации промокода {code}: {e}")
            await session.rollback()
            return False

async def create_promo_code(code: str, analyses_count: int, max_uses: int, expires_at_days: int, admin_id: int):
    async with async_session_maker() as session:
        try:
            expires_at = (datetime.now() + timedelta(days=expires_at_days)).date().isoformat() if expires_at_days > 0 else None
            new_promo = PromoCode(
                code=code.upper(),
                analyses_count=analyses_count,
                max_uses=max_uses,
                used_count=0,
                expires_at=expires_at,
                created_by=admin_id,
                created_at=datetime.now().isoformat()
            )
            session.add(new_promo)
            await session.commit()
            logger.info(f"✅ Промокод {code} создан: {analyses_count} ан., {max_uses} исп., до {expires_at}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка создания промокода {code}: {e}")
            await session.rollback()
            return False

async def get_all_promo_codes():
    async with async_session_maker() as session:
        try:
            result = await session.execute(
                select(PromoCode).order_by(PromoCode.created_at.desc())
            )
            codes = result.scalars().all()
            logger.info(f"✅ Загружено {len(codes)} промокодов из БД")
            return [(c.code, c.analyses_count, c.max_uses, c.used_count, c.expires_at) for c in codes]
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки промокодов: {e}")
            return []

async def deactivate_promo_code(code: str):
    async with async_session_maker() as session:
        try:
            await session.execute(delete(PromoCode).where(PromoCode.code == code.upper()))
            await session.commit()
            logger.info(f"✅ Промокод {code} удалён")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления промокода {code}: {e}")
            await session.rollback()
            return False

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

class DeletePromoForm(StatesGroup):
    code = State()

# ---------- Команды и кнопки ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await create_user(user_id)
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
    await create_user(user_id)
    
    user = await get_user(user_id)
    promo = user.promo_analyses if user else 0
    bought = user.bought_analyses if user else 0
    subscription = user.subscription_end if user else None
    
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
    user = await get_user(user_id)
    if not user:
        await create_user(user_id)
        user = await get_user(user_id)
    
    promo = user.promo_analyses if user else 0
    bought = user.bought_analyses if user else 0
    subscription = user.subscription_end if user else None
    
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
    
    codes = await get_all_promo_codes()
    if not codes:
        await message.answer("📭 Промокодов пока нет", reply_markup=admin_menu)
        return
    
    text = "📋 Список промокодов:\n\n"
    for code, analyses, max_uses, used, expires in codes:
        expires_str = expires if expires else "бессрочно"
        text += f"• {code}: {analyses} ан., {used}/{max_uses} исп., до {expires_str}\n"
    
    await message.answer(text, reply_markup=admin_menu)

# ---------- Создание промокода ----------
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
    success = await create_promo_code(
        code=data['code'],
        analyses_count=data['analyses'],
        max_uses=data['max_uses'],
        expires_at_days=days if days > 0 else 0,
        admin_id=message.from_user.id
    )
    
    if success:
        await message.answer(
            f"✅ Промокод **{data['code']}** создан!\n"
            f"• {data['analyses']} анализов\n"
            f"• максимум {data['max_uses']} использований\n"
            f"• {'бессрочно' if days == 0 else f'{days} дней'}",
            reply_markup=admin_menu
        )
    else:
        await message.answer(
            f"❌ Ошибка при создании промокода. Возможно, такой код уже существует.",
            reply_markup=admin_menu
        )
    await state.clear()

# ---------- Удаление промокода ----------
@dp.message(lambda message: message.text == "❌ Удалить промокод")
async def admin_delete_promo_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Введи код для удаления:")
    await state.set_state(DeletePromoForm.code)

@dp.message(DeletePromoForm.code)
async def admin_delete_promo_execute(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    code = message.text.strip().upper()
    success = await deactivate_promo_code(code)
    if success:
        await message.answer(f"✅ Промокод {code} удалён", reply_markup=admin_menu)
    else:
        await message.answer(f"❌ Ошибка при удалении промокода {code}", reply_markup=admin_menu)
    await state.clear()

# ---------- Активация промокода ----------
@dp.message(lambda message: len(message.text) < 20 and 
            message.text not in BUTTON_TEXTS and 
            not message.text.startswith('/'))
async def handle_promo(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip().upper()
    
    valid, result = await check_promo_code(code, user_id)
    
    if valid:
        success = await activate_promo_code(code, user_id)
        if success:
            await message.answer(
                f"✅ Промокод активирован!\n"
                f"Тебе начислено {result} анализа(ов).\n\n"
                f"Можешь начинать анализ 🔍",
                reply_markup=main_menu
            )
        else:
            await message.answer(f"❌ Ошибка при активации промокода", reply_markup=main_menu)
    else:
        await message.answer(f"❌ {result}", reply_markup=main_menu)

# ---------- Обработчик ссылок ----------
@dp.message(lambda message: 'avito.ru' in message.text)
async def handle_url(message: types.Message):
    user_id = message.from_user.id
    url = message.text.strip()
    
    result, _ = await use_analysis(user_id)
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

@dp.message(lambda message: message.text == "🏠 Главное меню")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu)

# ---------- ЗАПУСК ----------
async def on_startup(app):
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"✅ Вебхук установлен на {webhook_url}")
    
    await init_db()
    
    bot_info = await bot.get_me()
    logger.info(f"✅ Бот @{bot_info.username} запущен на вебхуках с PostgreSQL")

async def on_shutdown(app):
    await bot.delete_webhook()
    logger.info("Вебхук удалён")

app = web.Application()
webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
webhook_requests_handler.register(app, path="/webhook")
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)
