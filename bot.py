import asyncio
import logging
import uuid
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from supabase import create_client, Client

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# --- КОНФИГУРАЦИЯ ---
SUPABASE_URL = "https://xclfmpbippheygpwccpb.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhjbGZtcGJpcHBoZXlncHdjY3BiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM4MjAwNzAsImV4cCI6MjA3OTM5NjA3MH0.HhiUS4Ztls3byubqCaIg_xrmwuTmplXLS_K-vNMI-R8"
BOT_TOKEN = "8154688370:AAF4OWe9hvpvXyQA5_nryDHMFBpVG26MB1Y"
ADMIN_IDS = [844012884]
MINI_APP_URL = "t.me/OneNightTg_bot/onenightttttt"

# Инициализация
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
except Exception as e:
    logging.critical(f"Ошибка инициализации: {e}")
    exit()

# --- КОНСТАНТЫ ДЛЯ ONENIGHT ---
CITIES = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
    "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград", "Краснодар", "Сочи"
]

SERVICES_LIST = [
    "Классика",
    "Минет",
    "Анал",
    "Минет в машине",
    "Минет без резинки",
    "Окончание в рот",
    "Окончание на грудь",
    "Окончание на лицо",
    "Массаж",
    "Массаж эротический",
    "Массаж расслабляющий",
    "Куннилингус",
    "Римминг",
    "Золотой дождь",
    "Страпон",
    "БДСМ лайт",
    "БДСМ",
    "Доминация",
    "Фетиш",
    "Ролевые игры",
    "Стриптиз",
    "Лесби-шоу",
    "Групповой секс",
    "Эскорт на мероприятие",
    "Путешествия",
    "GFE (Girlfriend Experience)",
    "Апартаменты",
    "Выезд"
]

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def upload_photo_to_supabase(file_id: str, bot: Bot) -> str | None:
    """Загружает фото в Supabase Storage"""
    try:
        file = await bot.get_file(file_id)
        file_info = await bot.download_file(file.file_path)
        
        if file_info is None:
            return None
            
        file_extension = file.file_path.split('.')[-1] if '.' in file.file_path else 'jpg'
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        storage_path = f"profiles/{unique_filename}"
        
        file_info.seek(0)
        file_bytes = file_info.read()
        
        supabase.storage.from_("Files").upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": f"image/{file_extension}"}
        )
        
        public_url = supabase.storage.from_("Files").get_public_url(storage_path)
        return public_url
    except Exception as e:
        logging.error(f"Error uploading photo: {e}")
        return None

def generate_profile_preview(data):
    """Генерирует текст предпросмотра анкеты"""
    name = data.get('name', 'Имя')
    age = data.get('age', '?')
    city = data.get('city', 'Город')
    height = data.get('height', '?')
    weight = data.get('weight', '?')
    bust = data.get('bust', '?')
    price = data.get('price', '?')
    services = data.get('services', [])
    description = data.get('description', 'Описание не указано')
    is_top = "✨ TOP" if data.get('isTop', False) else ""
    is_verified = "✅ Верифицирована" if data.get('isVerified', False) else ""
    
    services_str = ", ".join(services) if services else "Не указаны"
    
    text = (
        f"👑 <b>{name}, {age} лет</b> {is_top} {is_verified}\n\n"
        f"📍 <b>Город:</b> {city}\n"
        f"📐 <b>Параметры:</b> Рост {height} см • Вес {weight} кг • Грудь {bust} размер\n"
        f"💰 <b>Цена:</b> {price} руб/час\n\n"
        f"🍓 <b>Услуги:</b> {services_str}\n\n"
        f"📝 <b>Описание:</b>\n{description}"
    )
    return text

# --- КЛАВИАТУРЫ ---

def worker_kb(is_admin=False):
    """Клавиатура воркера"""
    buttons = [
        [KeyboardButton(text="📂 Мои анкеты"), KeyboardButton(text="➕ Создать анкету")],
        [KeyboardButton(text="👥 Мамонты"), KeyboardButton(text="🔗 Реферальная ссылка")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def cancel_kb():
    """Кнопка отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def cities_kb():
    """Клавиатура выбора города"""
    buttons = []
    row = []
    for city in CITIES:
        row.append(InlineKeyboardButton(text=city, callback_data=f"city_{city}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def bust_size_kb():
    """Клавиатура выбора размера груди"""
    buttons = [
        [InlineKeyboardButton(text="1", callback_data="bust_1"),
         InlineKeyboardButton(text="2", callback_data="bust_2"),
         InlineKeyboardButton(text="3", callback_data="bust_3")],
        [InlineKeyboardButton(text="4", callback_data="bust_4"),
         InlineKeyboardButton(text="5", callback_data="bust_5"),
         InlineKeyboardButton(text="6", callback_data="bust_6")],
        [InlineKeyboardButton(text="Не указывать", callback_data="bust_0")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def services_kb(selected_services=None):
    """Клавиатура выбора услуг"""
    if selected_services is None:
        selected_services = []
    
    buttons = []
    for service in SERVICES_LIST:
        is_selected = service in selected_services
        text = f"✅ {service}" if is_selected else service
        callback_data = f"srv_{SERVICES_LIST.index(service)}"
        # Каждая услуга на отдельной строке для удобства
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])
    
    # Кнопка "Готово" в конце
    buttons.append([InlineKeyboardButton(text="✅ Готово", callback_data="srv_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def yes_no_kb(callback_prefix):
    """Универсальная клавиатура Да/Нет"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"{callback_prefix}_yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data=f"{callback_prefix}_no")]
    ])

def preview_kb():
    """Клавиатура предпросмотра"""
    buttons = [
        [InlineKeyboardButton(text="📝 Имя", callback_data="edit_name"),
         InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
        [InlineKeyboardButton(text="📍 Город", callback_data="edit_city"),
         InlineKeyboardButton(text="💰 Цена", callback_data="edit_price")],
        [InlineKeyboardButton(text="📐 Параметры", callback_data="edit_params"),
         InlineKeyboardButton(text="🍓 Услуги", callback_data="edit_services")],
        [InlineKeyboardButton(text="📸 Фото", callback_data="edit_photos"),
         InlineKeyboardButton(text="📄 Описание", callback_data="edit_description")],
        [InlineKeyboardButton(text="✨ TOP статус", callback_data="edit_top"),
         InlineKeyboardButton(text="✅ Верификация", callback_data="edit_verified")],
        [InlineKeyboardButton(text="✅ ОПУБЛИКОВАТЬ", callback_data="publish_confirm")],
        [InlineKeyboardButton(text="❌ Удалить черновик", callback_data="publish_cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_kb():
    """Клавиатура админа"""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Все анкеты"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="💳 Номер карты"), KeyboardButton(text="👤 Ник поддержки")],
        [KeyboardButton(text="🔙 Назад в меню")]
    ], resize_keyboard=True)

# --- МАШИНА СОСТОЯНИЙ ---

class ProfileForm(StatesGroup):
    """Состояния для создания/редактирования анкеты"""
    name = State()
    age = State()
    city = State()
    height = State()
    weight = State()
    bust = State()
    price = State()
    services = State()
    description = State()
    photos = State()
    isTop = State()
    isVerified = State()
    preview = State()

class AdminState(StatesGroup):
    """Состояния для админки"""
    waiting_payment_card = State()
    waiting_support_username = State()

# --- ОБРАБОТЧИКИ КОМАНД ---

async def register_user(telegram_id: int, first_name: str, username: str = None, referrer_id: int = None):
    """Регистрирует пользователя в базе данных"""
    try:
        user_data = {
            "telegram_id": telegram_id,
            "first_name": first_name,
            "username": username
        }
        
        # Проверяем, есть ли пользователь
        existing = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        
        if not existing.data:
            # Если новый юзер и есть реферер
            if referrer_id and referrer_id != telegram_id:
                user_data["referred_by"] = referrer_id
            
            supabase.table("users").insert(user_data).execute()
        else:
            # Обновляем инфу о юзере
            supabase.table("users").update({
                "first_name": first_name,
                "username": username
            }).eq("telegram_id", telegram_id).execute()
            
    except Exception as e:
        logging.error(f"Error registering user: {e}")

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    """Стартовая команда - показывает приветствие и кнопку Mini App с фото"""
    await state.clear()
    
    # Получаем реферальный ID из параметров
    args = command.args if hasattr(command, 'args') else None
    referrer_id = None
    
    if args and args.isdigit():
        referrer_id = int(args)
    
    # Регистрируем пользователя
    await register_user(
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.username,
        referrer_id
    )
    
    # Путь к фото
    photo_path = "1.png"
    photo = FSInputFile(photo_path)

    # Создаем клавиатуру
    welcome_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Открыть OneNight", url=MINI_APP_URL)]
    ])
    
    # Отправляем фото с подписью и кнопкой
    try:
        await message.answer_photo(
            photo=photo,
            caption=(
                "🔥 <b>Добро пожаловать в OneNight!</b>\n\n"
                "Найди идеальную девушку для незабываемого вечера. "
                "Тысячи анкет, реальные фото и безопасные встречи.\n\n"
                "Нажми кнопку ниже, чтобы открыть приложение:"
            ),
            parse_mode="HTML",
            reply_markup=welcome_kb
        )
    except Exception as e:
        logging.error(f"Error sending photo: {e}")
        # Если ошибка с фото, отправляем обычное сообщение
        await message.answer(
            "🔥 <b>Добро пожаловать в OneNight!</b>\n\n"
            "Найди идеальную девушку для незабываемого вечера. "
            "Тысячи анкет, реальные фото и безопасные встречи.\n\n"
            "Нажми кнопку ниже, чтобы открыть приложение:",
            parse_mode="HTML",
            reply_markup=welcome_kb
        )
@dp.message(Command("worker"))
async def cmd_worker(message: types.Message, state: FSMContext):
    """Вход в панель воркера"""
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    
    # Генерируем реферальную ссылку
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    
    await message.answer(
        f"👨‍💻 <b>Панель управления OneNight</b>\n\n"
        f"🔗 <b>Твоя реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"Отправляй эту ссылку клиентам. Все, кто перейдет по ней, "
        f"попадут в раздел 'Мамонты'.",
        parse_mode="HTML",
        reply_markup=worker_kb(is_admin)
    )

# --- СОЗДАНИЕ АНКЕТЫ ---

@dp.message(F.text == "➕ Создать анкету")
async def start_create_profile(message: types.Message, state: FSMContext):
    """Начало создания анкеты"""
    await state.clear()
    await state.update_data(is_edit_mode=False, photos=[])
    await state.set_state(ProfileForm.name)
    await message.answer(
        "📝 <b>Создание новой анкеты</b>\n\n"
        "1️⃣ Введите имя девушки:",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )

@dp.message(ProfileForm.name)
async def process_name(message: types.Message, state: FSMContext):
    """Обработка имени"""
    await state.update_data(name=message.text)
    await state.set_state(ProfileForm.age)
    await message.answer("2️⃣ Введите возраст (число от 18 до 35):")

@dp.message(ProfileForm.age)
async def process_age(message: types.Message, state: FSMContext):
    """Обработка возраста"""
    if not message.text.isdigit():
        await message.answer("⚠️ Введите число!")
        return
    
    age = int(message.text)
    if age < 18 or age > 35:
        await message.answer("⚠️ Возраст должен быть от 18 до 35 лет!")
        return
    
    await state.update_data(age=age)
    await state.set_state(ProfileForm.city)
    await message.answer("3️⃣ Выберите город:", reply_markup=cities_kb())

@dp.callback_query(ProfileForm.city, F.data.startswith("city_"))
async def process_city(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора города"""
    city = callback.data.replace("city_", "")
    await state.update_data(city=city)
    await callback.message.delete()
    await state.set_state(ProfileForm.height)
    await callback.message.answer(f"✅ Город: {city}\n\n4️⃣ Введите рост в см (150-200):")

@dp.message(ProfileForm.height)
async def process_height(message: types.Message, state: FSMContext):
    """Обработка роста"""
    if not message.text.isdigit():
        await message.answer("⚠️ Введите число!")
        return
    
    height = int(message.text)
    if height < 150 or height > 200:
        await message.answer("⚠️ Рост должен быть от 150 до 200 см!")
        return
    
    await state.update_data(height=height)
    await state.set_state(ProfileForm.weight)
    await message.answer("5️⃣ Введите вес в кг (40-100):")

@dp.message(ProfileForm.weight)
async def process_weight(message: types.Message, state: FSMContext):
    """Обработка веса"""
    if not message.text.isdigit():
        await message.answer("⚠️ Введите число!")
        return
    
    weight = int(message.text)
    if weight < 40 or weight > 100:
        await message.answer("⚠️ Вес должен быть от 40 до 100 кг!")
        return
    
    await state.update_data(weight=weight)
    await state.set_state(ProfileForm.bust)
    await message.answer("6️⃣ Выберите размер груди:", reply_markup=bust_size_kb())

@dp.callback_query(ProfileForm.bust, F.data.startswith("bust_"))
async def process_bust(callback: CallbackQuery, state: FSMContext):
    """Обработка размера груди"""
    bust = int(callback.data.replace("bust_", ""))
    await state.update_data(bust=bust)
    await callback.message.delete()
    await state.set_state(ProfileForm.price)
    await callback.message.answer("7️⃣ Введите цену за час в рублях (1000-100000):")

@dp.message(ProfileForm.price)
async def process_price(message: types.Message, state: FSMContext):
    """Обработка цены"""
    if not message.text.isdigit():
        await message.answer("⚠️ Введите число!")
        return
    
    price = int(message.text)
    if price < 1000 or price > 100000:
        await message.answer("⚠️ Цена должна быть от 1000 до 100000 рублей!")
        return
    
    await state.update_data(price=price, services=[])
    await state.set_state(ProfileForm.services)
    await message.answer("8️⃣ Выберите услуги (можно несколько):", reply_markup=services_kb([]))

@dp.callback_query(ProfileForm.services, F.data.startswith("srv_"))
async def process_services(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора услуг"""
    action = callback.data.replace("srv_", "")
    
    if action == "done":
        data = await state.get_data()
        services = data.get('services', [])
        if not services:
            await callback.answer("⚠️ Выберите хотя бы одну услугу!", show_alert=True)
            return
        await callback.message.delete()
        await state.set_state(ProfileForm.description)
        await callback.message.answer(
            "9️⃣ Введите описание анкеты (2-4 предложения):\n\n"
            "Пример: Элегантная блондинка с высшим образованием. "
            "Составлю компанию на статусных мероприятиях или скрашу одинокий вечер. "
            "Люблю искусство и хорошее вино."
        )
        return
    
    # Переключаем выбор услуги
    service_index = int(action)
    service_name = SERVICES_LIST[service_index]
    
    data = await state.get_data()
    services = data.get('services', [])
    
    if service_name in services:
        services.remove(service_name)
    else:
        services.append(service_name)
    
    await state.update_data(services=services)
    await callback.message.edit_reply_markup(reply_markup=services_kb(services))
    await callback.answer()

@dp.message(ProfileForm.description)
async def process_description(message: types.Message, state: FSMContext):
    """Обработка описания"""
    await state.update_data(description=message.text)
    await state.set_state(ProfileForm.photos)
    await message.answer(
        "🔟 Отправьте фото анкеты (минимум 2, рекомендуется 3-4).\n\n"
        "Отправляйте по одному фото. Когда закончите, нажмите 'Готово'.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Готово")]],
            resize_keyboard=True
        )
    )

@dp.message(ProfileForm.photos, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    """Обработка фото"""
    url = await upload_photo_to_supabase(message.photo[-1].file_id, bot)
    if url:
        data = await state.get_data()
        photos = data.get('photos', [])
        photos.append(url)
        await state.update_data(photos=photos)
        await message.answer(f"✅ Фото {len(photos)} добавлено!")
    else:
        await message.answer("❌ Ошибка загрузки фото. Попробуйте еще раз.")

@dp.message(ProfileForm.photos, F.text == "✅ Готово")
async def finish_photos(message: types.Message, state: FSMContext):
    """Завершение загрузки фото"""
    data = await state.get_data()
    photos = data.get('photos', [])
    
    if len(photos) < 2:
        await message.answer("⚠️ Загрузите минимум 2 фото!")
        return
    
    await state.set_state(ProfileForm.isTop)
    await message.answer(
        "1️⃣1️⃣ Сделать анкету TOP (будет отображаться с меткой TOP)?",
        reply_markup=yes_no_kb("top")
    )

@dp.callback_query(ProfileForm.isTop, F.data.startswith("top_"))
async def process_is_top(callback: CallbackQuery, state: FSMContext):
    """Обработка TOP статуса"""
    is_top = callback.data == "top_yes"
    await state.update_data(isTop=is_top)
    await callback.message.delete()
    await state.set_state(ProfileForm.isVerified)
    await callback.message.answer(
        "1️⃣2️⃣ Верифицировать анкету (будет отображаться с галочкой)?",
        reply_markup=yes_no_kb("verified")
    )

@dp.callback_query(ProfileForm.isVerified, F.data.startswith("verified_"))
async def process_is_verified(callback: CallbackQuery, state: FSMContext):
    """Обработка верификации"""
    is_verified = callback.data == "verified_yes"
    await state.update_data(isVerified=is_verified)
    await callback.message.delete()
    await show_preview(callback.message, state)

async def show_preview(message: types.Message, state: FSMContext):
    """Показ предпросмотра анкеты"""
    await state.set_state(ProfileForm.preview)
    data = await state.get_data()
    
    text = generate_profile_preview(data)
    photos = data.get('photos', [])
    
    await message.answer("👀 <b>ПРЕДПРОСМОТР АНКЕТЫ</b>", parse_mode="HTML")
    
    if photos:
        await message.answer_photo(
            photos[0],
            caption=text,
            parse_mode="HTML",
            reply_markup=preview_kb()
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=preview_kb())

# --- РЕДАКТИРОВАНИЕ И ПУБЛИКАЦИЯ ---

@dp.callback_query(ProfileForm.preview, F.data.startswith("edit_"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    """Обработка редактирования полей"""
    field = callback.data.replace("edit_", "")
    await state.update_data(is_edit_mode=True)
    
    if field == "name":
        await state.set_state(ProfileForm.name)
        await callback.message.answer("📝 Введите новое имя:", reply_markup=cancel_kb())
    elif field == "age":
        await state.set_state(ProfileForm.age)
        await callback.message.answer("🎂 Введите новый возраст:")
    elif field == "city":
        await state.set_state(ProfileForm.city)
        await callback.message.answer("📍 Выберите новый город:", reply_markup=cities_kb())
    elif field == "price":
        await state.set_state(ProfileForm.price)
        await callback.message.answer("💰 Введите новую цену:")
    elif field == "params":
        await state.set_state(ProfileForm.height)
        await callback.message.answer("📐 Введите новый рост:")
    elif field == "services":
        data = await state.get_data()
        await state.set_state(ProfileForm.services)
        await callback.message.answer("🍓 Выберите услуги:", reply_markup=services_kb(data.get('services', [])))
    elif field == "photos":
        await state.update_data(photos=[])
        await state.set_state(ProfileForm.photos)
        await callback.message.answer(
            "📸 Загрузите новые фото:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="✅ Готово")]],
                resize_keyboard=True
            )
        )
    elif field == "description":
        await state.set_state(ProfileForm.description)
        await callback.message.answer("📄 Введите новое описание:")
    elif field == "top":
        await state.set_state(ProfileForm.isTop)
        await callback.message.answer("✨ TOP статус:", reply_markup=yes_no_kb("top"))
    elif field == "verified":
        await state.set_state(ProfileForm.isVerified)
        await callback.message.answer("✅ Верификация:", reply_markup=yes_no_kb("verified"))
    
    await callback.answer()

@dp.callback_query(ProfileForm.preview, F.data == "publish_confirm")
async def publish_profile(callback: CallbackQuery, state: FSMContext):
    """Публикация анкеты"""
    data = await state.get_data()
    user_id = callback.from_user.id
    
    try:
        profile_payload = {
            "name": data['name'],
            "age": data['age'],
            "city": data['city'],
            "height": data['height'],
            "weight": data['weight'],
            "bust": data['bust'],
            "price": data['price'],
            "services": data['services'],
            "description": data['description'],
            "images": data['photos'],
            "isTop": data.get('isTop', False),
            "isVerified": data.get('isVerified', False),
            "telegram_owner_id": user_id
        }
        
        profile_id = data.get('profile_id')
        if profile_id and data.get('is_edit_mode'):
            # Обновление существующей анкеты
            supabase.table("profiles").update(profile_payload).eq("id", profile_id).execute()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"✅ <b>Анкета #{profile_id} обновлена!</b>", parse_mode="HTML")
        else:
            # Создание новой анкеты
            result = supabase.table("profiles").insert(profile_payload).execute()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("✅ <b>Анкета успешно опубликована!</b>", parse_mode="HTML")
        
        await state.clear()
        is_admin = user_id in ADMIN_IDS
        await callback.message.answer("Главное меню:", reply_markup=worker_kb(is_admin))
        
    except Exception as e:
        logging.error(f"Publish error: {e}")
        await callback.answer("❌ Ошибка публикации!", show_alert=True)

@dp.callback_query(ProfileForm.preview, F.data == "publish_cancel")
async def cancel_publish(callback: CallbackQuery, state: FSMContext):
    """Отмена публикации"""
    await state.clear()
    await callback.message.delete()
    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.answer("❌ Черновик удален.", reply_markup=worker_kb(is_admin))

# --- УПРАВЛЕНИЕ АНКЕТАМИ ---

@dp.message(F.text == "📂 Мои анкеты")
async def my_profiles(message: types.Message):
    """Список анкет воркера"""
    user_id = message.from_user.id
    
    try:
        response = supabase.table("profiles").select("*").eq("telegram_owner_id", user_id).execute()
        profiles = response.data
        
        if not profiles:
            await message.answer(
                "😔 У тебя пока нет анкет.\n\n"
                "Нажми '➕ Создать анкету' чтобы добавить первую!"
            )
            return
        
        text = f"📂 <b>Твои анкеты ({len(profiles)}):</b>\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        for i, profile in enumerate(profiles, 1):
            name = profile.get('name', 'Без имени')
            age = profile.get('age', '?')
            city = profile.get('city', 'Город не указан')
            profile_id = profile.get('id')
            
            is_top = "✨" if profile.get('isTop', False) else ""
            is_verified = "✅" if profile.get('isVerified', False) else ""
            
            text += f"{i}. <b>{name}, {age}</b> — {city} {is_top} {is_verified}\n"
            
            row_buttons = [
                InlineKeyboardButton(
                    text=f"✏️ {name}",
                    callback_data=f"edit_profile_{profile_id}"
                ),
                InlineKeyboardButton(
                    text=f"🗑️",
                    callback_data=f"delete_profile_{profile_id}"
                )
            ]
            keyboard.inline_keyboard.append(row_buttons)
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Profiles error: {e}")
        await message.answer("❌ Ошибка получения списка анкет.")

@dp.callback_query(F.data.startswith("edit_profile_"))
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    """Редактирование анкеты"""
    profile_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    try:
        response = supabase.table("profiles").select("*").eq("id", profile_id).eq("telegram_owner_id", user_id).execute()
        
        if not response.data:
            await callback.message.answer("❌ Эта анкета тебе не принадлежит!")
            await callback.answer()
            return
        
        profile = response.data[0]
        
        await state.update_data(
            name=profile.get('name'),
            age=profile.get('age'),
            city=profile.get('city'),
            height=profile.get('height'),
            weight=profile.get('weight'),
            bust=profile.get('bust'),
            price=profile.get('price'),
            services=profile.get('services', []),
            description=profile.get('description'),
            photos=profile.get('images', []),
            isTop=profile.get('isTop', False),
            isVerified=profile.get('isVerified', False),
            profile_id=profile_id,
            is_edit_mode=True
        )
        
        await show_preview(callback.message, state)
        
    except Exception as e:
        logging.error(f"Edit profile error: {e}")
        await callback.message.answer("❌ Ошибка загрузки анкеты.")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_profile_"))
async def delete_profile_confirm(callback: CallbackQuery):
    """Подтверждение удаления анкеты"""
    profile_id = callback.data.split("_")[2]
    
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{profile_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")
        ]
    ])
    
    await callback.message.answer(
        f"⚠️ Ты уверен, что хочешь удалить анкету #{profile_id}?\n\n"
        "Это действие нельзя отменить!",
        reply_markup=confirm_kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def delete_profile(callback: CallbackQuery):
    """Удаление анкеты"""
    profile_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    try:
        response = supabase.table("profiles").select("id").eq("id", profile_id).eq("telegram_owner_id", user_id).execute()
        
        if not response.data:
            await callback.message.answer("❌ Эта анкета тебе не принадлежит!")
            await callback.answer()
            return
        
        supabase.table("profiles").delete().eq("id", profile_id).execute()
        await callback.message.answer(f"✅ Анкета #{profile_id} успешно удалена!")
        
    except Exception as e:
        logging.error(f"Delete profile error: {e}")
        await callback.message.answer("❌ Ошибка удаления анкеты.")
    
    await callback.answer()

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery):
    """Отмена удаления"""
    await callback.message.edit_text("❌ Удаление отменено")
    await callback.answer()

# --- МАМОНТЫ ---

@dp.message(F.text == "👥 Мамонты")
async def show_mamonty(message: types.Message):
    """Показывает список мамонтов (людей, перешедших по реферальной ссылке)"""
    user_id = message.from_user.id
    
    try:
        response = supabase.table("users").select("*").eq("referred_by", user_id).execute()
        mamonty = response.data
        
        if not mamonty:
            await message.answer(
                "😔 <b>У тебя пока нет мамонтов</b>\n\n"
                "Отправляй свою реферальную ссылку клиентам, "
                "и они появятся здесь.",
                parse_mode="HTML"
            )
            return
        
        text = f"👥 <b>Твои мамонты ({len(mamonty)}):</b>\n\n"
        
        for i, mamont in enumerate(mamonty, 1):
            name = mamont.get('first_name', 'Без имени')
            username = mamont.get('username', '')
            username_str = f"@{username}" if username else "нет username"
            created = mamont.get('created_at', '').split('T')[0] if mamont.get('created_at') else 'неизвестно'
            
            text += f"{i}. <b>{name}</b> ({username_str})\n"
            text += f"   📅 Перешел: {created}\n\n"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Mamonty error: {e}")
        await message.answer("❌ Ошибка получения списка мамонтов.")

@dp.message(F.text == "🔗 Реферальная ссылка")
async def show_ref_link(message: types.Message):
    """Показывает реферальную ссылку"""
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    
    await message.answer(
        f"🔗 <b>Твоя реферальная ссылка:</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"Отправляй эту ссылку клиентам. Все, кто перейдет по ней, "
        f"попадут в раздел 'Мамонты'.",
        parse_mode="HTML"
    )

# --- АДМИНКА ---

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    """Админ панель (доступна только админам)"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.clear()
    await message.answer(
        "⚙️ <b>Админ панель OneNight</b>\n\n"
        "Управление анкетами, реквизитами и настройками.",
        parse_mode="HTML",
        reply_markup=admin_kb()
    )

@dp.message(F.text == "📋 Все анкеты")
async def show_all_profiles(message: types.Message):
    """Показывает все анкеты с возможностью удаления"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        response = supabase.table("profiles").select("*").order("created_at", desc=True).limit(20).execute()
        profiles = response.data
        
        if not profiles:
            await message.answer("📋 <b>Анкет пока нет</b>", parse_mode="HTML")
            return
        
        text = f"📋 <b>Все анкеты (последние 20):</b>\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        for i, profile in enumerate(profiles, 1):
            name = profile.get('name', 'Без имени')
            age = profile.get('age', '?')
            city = profile.get('city', 'Город не указан')
            profile_id = profile.get('id')
            price = profile.get('price', 0)
            
            is_top = "✨" if profile.get('isTop', False) else ""
            is_verified = "✅" if profile.get('isVerified', False) else ""
            
            text += f"{i}. <b>{name}, {age}</b> — {city} — {price}₽ {is_top} {is_verified}\n"
            
            row_buttons = [
                InlineKeyboardButton(
                    text=f"🗑️ Удалить {name}",
                    callback_data=f"admin_delete_{profile_id}"
                )
            ]
            keyboard.inline_keyboard.append(row_buttons)
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Show all profiles error: {e}")
        await message.answer("❌ Ошибка получения анкет.")

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    """Показ статистики"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        profiles_response = supabase.table("profiles").select("*").execute()
        users_response = supabase.table("users").select("*").execute()
        
        total_profiles = len(profiles_response.data)
        total_users = len(users_response.data)
        
        top_profiles = len([p for p in profiles_response.data if p.get('isTop', False)])
        verified_profiles = len([p for p in profiles_response.data if p.get('isVerified', False)])
        
        # Считаем мамонтов (пользователей с реферером)
        mamonty = len([u for u in users_response.data if u.get('referred_by')])
        
        cities_count = {}
        for profile in profiles_response.data:
            city = profile.get('city', 'Не указан')
            cities_count[city] = cities_count.get(city, 0) + 1
        
        top_cities = sorted(cities_count.items(), key=lambda x: x[1], reverse=True)[:5]
        
        text = (
            f"📊 <b>Статистика OneNight</b>\n\n"
            f"📂 Всего анкет: {total_profiles}\n"
            f"✨ TOP анкет: {top_profiles}\n"
            f"✅ Верифицированных: {verified_profiles}\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🎯 Мамонтов: {mamonty}\n\n"
            f"🏙 <b>Топ-5 городов:</b>\n"
        )
        
        for i, (city, count) in enumerate(top_cities, 1):
            text += f"{i}. {city}: {count} анкет\n"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Stats error: {e}")
        await message.answer("❌ Ошибка получения статистики.")

@dp.message(F.text == "💳 Номер карты")
async def change_payment_card(message: types.Message, state: FSMContext):
    """Изменение номера карты"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        response = supabase.table("site_settings").select("*").eq("id", 1).execute()
        settings = response.data[0] if response.data else {}
        
        current_card = settings.get('payment_card', 'Не установлена')
        
        await state.set_state(AdminState.waiting_payment_card)
        await message.answer(
            f"💳 <b>Текущий номер карты:</b>\n<code>{current_card}</code>\n\n"
            f"Введите новый номер карты:\n\n"
            f"Пример: <code>2202 2026 8321 4532</code>",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
        
    except Exception as e:
        logging.error(f"Payment card error: {e}")
        await message.answer("❌ Ошибка получения номера карты.")

@dp.message(AdminState.waiting_payment_card)
async def change_card_finish(message: types.Message, state: FSMContext):
    """Сохранение новой карты"""
    card = message.text.strip()
    
    try:
        supabase.table("site_settings").update({
            "payment_card": card,
            "updated_at": "now()"
        }).eq("id", 1).execute()
        
        await message.answer(
            f"✅ Номер карты обновлен:\n<code>{card}</code>",
            parse_mode="HTML",
            reply_markup=admin_kb()
        )
        
    except Exception as e:
        logging.error(f"Update card error: {e}")
        await message.answer("❌ Ошибка сохранения карты.")
    
    await state.clear()

@dp.message(F.text == "👤 Ник поддержки")
async def change_support_username(message: types.Message, state: FSMContext):
    """Изменение ника поддержки"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        response = supabase.table("site_settings").select("*").eq("id", 1).execute()
        settings = response.data[0] if response.data else {}
        
        current_username = settings.get('support_username', 'Не установлен')
        
        await state.set_state(AdminState.waiting_support_username)
        await message.answer(
            f"👤 <b>Текущий ник поддержки:</b>\n<code>{current_username}</code>\n\n"
            f"Введите новый ник поддержки:\n\n"
            f"Пример: <code>@OneNightSupport</code>",
            parse_mode="HTML",
            reply_markup=cancel_kb()
        )
        
    except Exception as e:
        logging.error(f"Support username error: {e}")
        await message.answer("❌ Ошибка получения ника поддержки.")

@dp.message(AdminState.waiting_support_username)
async def change_support_username_finish(message: types.Message, state: FSMContext):
    """Сохранение нового ника поддержки"""
    username = message.text.strip()
    
    # Добавляем @ если его нет
    if not username.startswith('@'):
        username = '@' + username
    
    try:
        supabase.table("site_settings").update({
            "support_username": username,
            "updated_at": "now()"
        }).eq("id", 1).execute()
        
        await message.answer(
            f"✅ Ник поддержки обновлен:\n<code>{username}</code>",
            parse_mode="HTML",
            reply_markup=admin_kb()
        )
        
    except Exception as e:
        logging.error(f"Update support username error: {e}")
        await message.answer("❌ Ошибка сохранения ника поддержки.")
    
    await state.clear()

@dp.callback_query(F.data.startswith("admin_edit_"))
async def admin_edit_profile(callback: CallbackQuery, state: FSMContext):
    """Админ редактирование анкеты"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    profile_id = callback.data.split("_")[2]
    
    try:
        response = supabase.table("profiles").select("*").eq("id", profile_id).execute()
        
        if not response.data:
            await callback.message.answer("❌ Анкета не найдена!")
            await callback.answer()
            return
        
        profile = response.data[0]
        
        await state.update_data(
            name=profile.get('name'),
            age=profile.get('age'),
            city=profile.get('city'),
            height=profile.get('height'),
            weight=profile.get('weight'),
            bust=profile.get('bust'),
            price=profile.get('price'),
            services=profile.get('services', []),
            description=profile.get('description'),
            photos=profile.get('images', []),
            isTop=profile.get('isTop', False),
            isVerified=profile.get('isVerified', False),
            profile_id=profile_id,
            is_edit_mode=True
        )
        
        await show_preview(callback.message, state)
        
    except Exception as e:
        logging.error(f"Admin edit error: {e}")
        await callback.message.answer("❌ Ошибка загрузки анкеты.")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_profile_confirm(callback: CallbackQuery):
    """Админ подтверждение удаления"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    profile_id = callback.data.split("_")[2]
    
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_confirm_delete_{profile_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel_delete")
        ]
    ])
    
    await callback.message.answer(
        f"⚠️ Удалить анкету #{profile_id}?",
        reply_markup=confirm_kb
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_confirm_delete_"))
async def admin_delete_profile(callback: CallbackQuery):
    """Админ удаление анкеты"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен!", show_alert=True)
        return
    
    profile_id = callback.data.split("_")[3]
    
    try:
        supabase.table("profiles").delete().eq("id", profile_id).execute()
        await callback.message.answer(f"✅ Анкета #{profile_id} удалена!")
    except Exception as e:
        logging.error(f"Admin delete error: {e}")
        await callback.message.answer("❌ Ошибка удаления.")
    
    await callback.answer()

@dp.callback_query(F.data == "admin_cancel_delete")
async def admin_cancel_delete(callback: CallbackQuery):
    """Админ отмена удаления"""
    await callback.message.edit_text("❌ Удаление отменено")
    await callback.answer()

# --- ОБЩИЕ ОБРАБОТЧИКИ ---

@dp.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message, state: FSMContext):
    """Отмена действия"""
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("❌ Действие отменено.", reply_markup=worker_kb(is_admin))

@dp.message(F.text == "🔙 Назад в меню")
async def back_to_menu(message: types.Message, state: FSMContext):
    """Возврат в меню"""
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Главное меню:", reply_markup=worker_kb(is_admin))

# --- ЗАПУСК БОТА ---

async def main():
    """Главная функция запуска бота"""
    print("🚀 OneNight Bot запущен!")
    print("📝 Бот готов к созданию анкет")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Бот остановлен")

