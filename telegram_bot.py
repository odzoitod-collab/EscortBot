import logging
import sys
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from supabase import create_client, Client
from config import Config
from datetime import datetime

# Настройка логирования (уменьшаем уровень для httpx)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, Config.LOG_LEVEL.upper())
)
logger = logging.getLogger(__name__)

# Отключаем подробные логи httpx для ускорения
logging.getLogger("httpx").setLevel(logging.WARNING)

# Supabase клиент с оптимизацией
supabase: Client = create_client(
    Config.SUPABASE_URL, 
    Config.SUPABASE_KEY,
    options={
        "auto_refresh_token": False,
        "persist_session": False,
    }
)

# Состояния для ConversationHandler
(CREATE_NAME, CREATE_AGE, CREATE_CITY, CREATE_HEIGHT, CREATE_WEIGHT,
 CREATE_BUST, CREATE_PRICE, CREATE_DESCRIPTION, CREATE_SERVICES, 
 CREATE_IMAGES, CREATE_CONFIRM) = range(11)

# Состояния для админ панели
(ADMIN_EDIT_CARD, ADMIN_EDIT_SUPPORT) = range(100, 102)

# ============================================
# ПРОВЕРКА АДМИНА
# ============================================

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in Config.ADMIN_IDS

# ============================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С НАСТРОЙКАМИ
# ============================================

# Кэш для часто используемых данных
_settings_cache = None
_settings_cache_time = None
CACHE_DURATION = 300  # 5 минут

def get_site_settings() -> dict:
    """Получить настройки сайта с кэшированием"""
    global _settings_cache, _settings_cache_time
    
    now = datetime.now()
    if (_settings_cache is not None and 
        _settings_cache_time is not None and 
        (now - _settings_cache_time).seconds < CACHE_DURATION):
        return _settings_cache
    
    try:
        result = supabase.table('site_settings').select('*').eq('id', 1).execute()
        if result.data:
            _settings_cache = result.data[0]
            _settings_cache_time = now
            return _settings_cache
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
    
    # Возвращаем дефолтные настройки если не удалось загрузить
    default_settings = {'support_username': '@OneNightSupport', 'payment_card': '2202 2026 8321 4532'}
    _settings_cache = default_settings
    _settings_cache_time = now
    return default_settings

def update_site_settings(field: str, value: str) -> bool:
    """Обновить настройки сайта"""
    global _settings_cache, _settings_cache_time
    try:
        supabase.table('site_settings').update({field: value}).eq('id', 1).execute()
        # Сбрасываем кэш
        _settings_cache = None
        _settings_cache_time = None
        return True
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return False

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

# Кэш для воркеров
_workers_cache = {}

async def get_or_create_worker(user) -> dict:
    """Получить или создать воркера с кэшированием"""
    user_id = user.id
    
    # Проверяем кэш
    if user_id in _workers_cache:
        worker = _workers_cache[user_id]
        # Обновляем last_activity в фоне
        asyncio.create_task(update_worker_activity(user_id, user))
        return worker
    
    try:
        result = supabase.table('workers').select('*').eq('telegram_id', user_id).execute()
        
        if result.data:
            worker = result.data[0]
            # Кэшируем
            _workers_cache[user_id] = worker
            # Обновляем last_activity в фоне
            asyncio.create_task(update_worker_activity(user_id, user))
            return worker
        
        # Создаем нового воркера
        new_worker = supabase.table('workers').insert({
            'telegram_id': user_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }).execute()
        
        if new_worker.data:
            worker = new_worker.data[0]
            _workers_cache[user_id] = worker
            return worker
            
    except Exception as e:
        logger.error(f"Error with worker {user_id}: {e}")
    
    return None

async def update_worker_activity(user_id: int, user):
    """Обновляет активность воркера в фоне"""
    try:
        supabase.table('workers').update({
            'last_activity': datetime.now().isoformat(),
            'username': user.username,
            'first_name': user.first_name
        }).eq('telegram_id', user_id).execute()
    except Exception as e:
        logger.error(f"Error updating worker activity: {e}")


async def register_referral(user, referral_code: str) -> bool:
    """Регистрация реферала (оптимизированная)"""
    try:
        # Находим воркера по реферальному коду
        referrer = supabase.table('workers').select('id').eq('referral_code', referral_code).execute()
        
        if not referrer.data:
            return False
        
        referrer_id = referrer.data[0]['id']
        
        # Проверяем, не зарегистрирован ли уже этот клиент (быстрая проверка)
        existing = supabase.table('worker_clients').select('id').eq('telegram_id', user.id).execute()
        
        if existing.data:
            return False
        
        # Регистрируем клиента
        supabase.table('worker_clients').insert({
            'worker_id': referrer_id,
            'telegram_id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }).execute()
        
        return True
    except Exception as e:
        logger.error(f"Error registering referral: {e}")
        return False

def get_worker_clients(worker_id: int) -> list:
    """Получить клиентов воркера"""
    result = supabase.table('worker_clients').select('*').eq('worker_id', worker_id).order('created_at', desc=True).execute()
    return result.data or []

def get_worker_models(worker_id: int) -> list:
    """Получить модели воркера"""
    result = supabase.table('profiles').select('*').eq('worker_id', worker_id).eq('is_active', True).order('created_at', desc=True).execute()
    return result.data or []

def create_model(worker_id: int, data: dict) -> dict:
    """Создать модель"""
    model_data = {
        'worker_id': worker_id,
        'name': data['name'],
        'age': data['age'],
        'city': data['city'],
        'height': data['height'],
        'weight': data['weight'],
        'bust': data['bust'],
        'price': data['price'],
        'description': data.get('description', ''),
        'services': data.get('services', []),
        'images': data.get('images', []),
        'isVerified': True
    }
    result = supabase.table('profiles').insert(model_data).execute()
    return result.data[0] if result.data else None

def delete_model(model_id: int) -> bool:
    """Удалить модель (мягкое удаление)"""
    result = supabase.table('profiles').update({'is_active': False}).eq('id', model_id).execute()
    return bool(result.data)


# ============================================
# ОСНОВНЫЕ КОМАНДЫ
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    logger.info(f"Пользователь {user.full_name} (@{user.username}, ID: {user.id}) запустил бота")
    
    # Проверяем реферальный код в deep link (без уведомления)
    if context.args:
        referral_code = context.args[0]
        await register_referral(user, referral_code)
    
    user_name = user.first_name if user.first_name else "друг"
    welcome_text = (
        f"🔥 Привет, {user_name}! Добро пожаловать в OneNight!\n\n"
        "Найди идеальную девушку для незабываемого вечера. "
        "Тысячи анкет, реальные фото и безопасные встречи.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Открыть OneNight", web_app=WebAppInfo(url=Config.WEB_APP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def worker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Воркер панель - /worker"""
    user = update.effective_user
    worker = await get_or_create_worker(user)
    
    if not worker:
        await update.message.reply_text("❌ Ошибка при создании профиля воркера")
        return
    
    referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={worker['referral_code']}"
    clients_count = len(get_worker_clients(worker['id']))
    models_count = len(get_worker_models(worker['id']))
    
    text = (
        f"👷 <b>Воркер Панель</b>\n\n"
        f"👤 <b>Ваш профиль:</b>\n"
        f"├ ID: <code>{worker['telegram_id']}</code>\n"
        f"├ Username: @{worker['username'] or 'не указан'}\n"
        f"└ Имя: {worker['first_name'] or 'не указано'}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"├ 👥 Клиентов: {clients_count}\n"
        f"└ 💃 Моделей: {models_count}\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"<i>Нажмите на ссылку, чтобы скопировать</i>"
    )
    
    keyboard = [
        [InlineKeyboardButton("👥 Мои клиенты", callback_data="worker_clients")],
        [InlineKeyboardButton("💃 Мои модели", callback_data="worker_models")],
        [InlineKeyboardButton("➕ Создать модель", callback_data="create_model")],
        [InlineKeyboardButton("🔗 Скопировать ссылку", callback_data=f"copy_ref_{worker['referral_code']}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')


# ============================================
# АДМИН ПАНЕЛЬ
# ============================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ панель - /admin"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет доступа к админ панели")
        return
    
    settings = get_site_settings()
    
    # Статистика
    workers_count = len(supabase.table('workers').select('id').execute().data or [])
    clients_count = len(supabase.table('worker_clients').select('id').execute().data or [])
    models_count = len(supabase.table('profiles').select('id').eq('is_active', True).execute().data or [])
    
    text = (
        "👑 <b>Админ Панель</b>\n\n"
        "📊 <b>Статистика:</b>\n"
        f"├ 👷 Воркеров: {workers_count}\n"
        f"├ 👥 Клиентов: {clients_count}\n"
        f"└ 💃 Моделей: {models_count}\n\n"
        "⚙️ <b>Текущие настройки:</b>\n"
        f"├ 💳 Карта: <code>{settings.get('payment_card', 'не указана')}</code>\n"
        f"└ 📞 Поддержка: {settings.get('support_username', 'не указан')}\n\n"
        "<i>Выберите действие:</i>"
    )
    
    keyboard = [
        [InlineKeyboardButton("💳 Изменить реквизиты", callback_data="admin_edit_card")],
        [InlineKeyboardButton("📞 Изменить поддержку", callback_data="admin_edit_support")],
        [InlineKeyboardButton("📊 Все модели", callback_data="admin_all_models")],
        [InlineKeyboardButton("👷 Все воркеры", callback_data="admin_all_workers")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик кнопок админ панели"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if not is_admin(user.id):
        await query.edit_message_text("❌ Доступ запрещен")
        return ConversationHandler.END
    
    data = query.data
    
    if data == "admin_menu":
        settings = get_site_settings()
        workers_count = len(supabase.table('workers').select('id').execute().data or [])
        clients_count = len(supabase.table('worker_clients').select('id').execute().data or [])
        models_count = len(supabase.table('profiles').select('id').eq('is_active', True).execute().data or [])
        
        text = (
            "👑 <b>Админ Панель</b>\n\n"
            "📊 <b>Статистика:</b>\n"
            f"├ 👷 Воркеров: {workers_count}\n"
            f"├ 👥 Клиентов: {clients_count}\n"
            f"└ 💃 Моделей: {models_count}\n\n"
            "⚙️ <b>Текущие настройки:</b>\n"
            f"├ 💳 Карта: <code>{settings.get('payment_card', 'не указана')}</code>\n"
            f"└ 📞 Поддержка: {settings.get('support_username', 'не указан')}"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 Изменить реквизиты", callback_data="admin_edit_card")],
            [InlineKeyboardButton("📞 Изменить поддержку", callback_data="admin_edit_support")],
            [InlineKeyboardButton("📊 Все модели", callback_data="admin_all_models")],
            [InlineKeyboardButton("👷 Все воркеры", callback_data="admin_all_workers")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ConversationHandler.END
    
    elif data == "admin_edit_card":
        settings = get_site_settings()
        text = (
            "💳 <b>Изменение реквизитов</b>\n\n"
            f"Текущая карта:\n<code>{settings.get('payment_card', 'не указана')}</code>\n\n"
            "Отправьте новый номер карты:"
        )
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ADMIN_EDIT_CARD
    
    elif data == "admin_edit_support":
        settings = get_site_settings()
        text = (
            "📞 <b>Изменение поддержки</b>\n\n"
            f"Текущий username:\n{settings.get('support_username', 'не указан')}\n\n"
            "Отправьте новый username (с @):"
        )
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ADMIN_EDIT_SUPPORT
    
    elif data == "admin_all_models":
        models = supabase.table('profiles').select('*').eq('is_active', True).order('created_at', desc=True).limit(20).execute().data or []
        
        if not models:
            text = "📊 <b>Все модели</b>\n\n<i>Моделей пока нет</i>"
        else:
            text = f"📊 <b>Все модели ({len(models)})</b>\n\n"
            for m in models[:10]:
                text += f"• {m['name']}, {m['age']} - {m['city']} ({m['price']}₽)\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ConversationHandler.END
    
    elif data == "admin_all_workers":
        workers = supabase.table('workers').select('*').order('created_at', desc=True).limit(20).execute().data or []
        
        if not workers:
            text = "👷 <b>Все воркеры</b>\n\n<i>Воркеров пока нет</i>"
        else:
            text = f"👷 <b>Все воркеры ({len(workers)})</b>\n\n"
            for w in workers[:10]:
                name = w.get('first_name') or w.get('username') or f"ID: {w['telegram_id']}"
                text += f"• {name} - код: <code>{w['referral_code']}</code>\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ConversationHandler.END
    
    return ConversationHandler.END


async def admin_save_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение новой карты"""
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END
    
    new_card = update.message.text.strip()
    
    # Валидация (простая проверка на цифры и пробелы)
    card_digits = new_card.replace(' ', '')
    if not card_digits.isdigit() or len(card_digits) < 13:
        await update.message.reply_text(
            "❌ Неверный формат карты. Введите номер карты (13-19 цифр):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="admin_menu")]])
        )
        return ADMIN_EDIT_CARD
    
    if update_site_settings('payment_card', new_card):
        text = f"✅ <b>Реквизиты обновлены!</b>\n\nНовая карта:\n<code>{new_card}</code>"
    else:
        text = "❌ Ошибка при сохранении"
    
    keyboard = [[InlineKeyboardButton("◀️ В админ панель", callback_data="admin_menu")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ConversationHandler.END


async def admin_save_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение нового username поддержки"""
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END
    
    new_support = update.message.text.strip()
    
    # Добавляем @ если нет
    if not new_support.startswith('@'):
        new_support = '@' + new_support
    
    if update_site_settings('support_username', new_support):
        text = f"✅ <b>Поддержка обновлена!</b>\n\nНовый username: {new_support}"
    else:
        text = "❌ Ошибка при сохранении"
    
    keyboard = [[InlineKeyboardButton("◀️ В админ панель", callback_data="admin_menu")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ConversationHandler.END


# ============================================
# CALLBACK HANDLERS
# ============================================

async def worker_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок воркер панели"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    worker = await get_or_create_worker(user)
    
    if not worker:
        await query.edit_message_text("❌ Ошибка")
        return
    
    data = query.data
    
    if data == "worker_menu":
        # Возврат в главное меню воркера
        referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start={worker['referral_code']}"
        clients_count = len(get_worker_clients(worker['id']))
        models_count = len(get_worker_models(worker['id']))
        
        text = (
            f"👷 <b>Воркер Панель</b>\n\n"
            f"👤 <b>Ваш профиль:</b>\n"
            f"├ ID: <code>{worker['telegram_id']}</code>\n"
            f"├ Username: @{worker['username'] or 'не указан'}\n"
            f"└ Имя: {worker['first_name'] or 'не указано'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"├ 👥 Клиентов: {clients_count}\n"
            f"└ 💃 Моделей: {models_count}\n\n"
            f"🔗 <b>Ваша реферальная ссылка:</b>\n"
            f"<code>{referral_link}</code>"
        )
        
        keyboard = [
            [InlineKeyboardButton("👥 Мои клиенты", callback_data="worker_clients")],
            [InlineKeyboardButton("💃 Мои модели", callback_data="worker_models")],
            [InlineKeyboardButton("➕ Создать модель", callback_data="create_model")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data == "worker_clients":
        # Список клиентов
        clients = get_worker_clients(worker['id'])
        
        if not clients:
            text = "👥 <b>Мои клиенты</b>\n\n<i>У вас пока нет клиентов.\nПоделитесь реферальной ссылкой!</i>"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="worker_menu")]]
        else:
            text = f"👥 <b>Мои клиенты ({len(clients)})</b>\n\n"
            keyboard = []
            for client in clients[:10]:  # Показываем первых 10
                name = client['first_name'] or client['username'] or f"ID: {client['telegram_id']}"
                keyboard.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"client_{client['id']}")])
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="worker_menu")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data.startswith("client_"):
        # Информация о клиенте
        client_id = int(data.split("_")[1])
        result = supabase.table('worker_clients').select('*').eq('id', client_id).execute()
        
        if result.data:
            client = result.data[0]
            created = datetime.fromisoformat(client['created_at'].replace('Z', '+00:00'))
            
            text = (
                f"👤 <b>Информация о клиенте</b>\n\n"
                f"├ ID: <code>{client['telegram_id']}</code>\n"
                f"├ Username: @{client['username'] or 'не указан'}\n"
                f"├ Имя: {client['first_name'] or 'не указано'}\n"
                f"└ Дата регистрации: {created.strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            text = "❌ Клиент не найден"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="worker_clients")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    
    elif data == "worker_models":
        # Список моделей
        models = get_worker_models(worker['id'])
        
        if not models:
            text = "💃 <b>Мои модели</b>\n\n<i>У вас пока нет моделей.\nСоздайте первую!</i>"
            keyboard = [
                [InlineKeyboardButton("➕ Создать модель", callback_data="create_model")],
                [InlineKeyboardButton("◀️ Назад", callback_data="worker_menu")]
            ]
        else:
            text = f"💃 <b>Мои модели ({len(models)})</b>\n\n"
            keyboard = []
            for model in models:
                keyboard.append([InlineKeyboardButton(
                    f"💃 {model['name']}, {model['age']} - {model['city']}", 
                    callback_data=f"model_{model['id']}"
                )])
            keyboard.append([InlineKeyboardButton("➕ Создать модель", callback_data="create_model")])
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="worker_menu")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data.startswith("model_"):
        # Информация о модели
        model_id = int(data.split("_")[1])
        result = supabase.table('profiles').select('*').eq('id', model_id).execute()
        
        if result.data:
            model = result.data[0]
            services = ', '.join(model['services'][:5]) if model['services'] else 'не указаны'
            if len(model['services']) > 5:
                services += f' и ещё {len(model["services"]) - 5}'
            
            text = (
                f"💃 <b>{model['name']}, {model['age']}</b>\n\n"
                f"📍 Город: {model['city']}\n"
                f"📏 Рост: {model['height']} см\n"
                f"⚖️ Вес: {model['weight']} кг\n"
                f"👙 Грудь: {model['bust']}\n"
                f"💰 Цена: {model['price']} ₽/час\n\n"
                f"📝 Описание:\n{model['description'] or 'не указано'}\n\n"
                f"🔧 Услуги: {services}\n"
                f"🖼 Фото: {len(model['images'] or [])}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🗑 Удалить модель", callback_data=f"delete_model_{model_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="worker_models")]
            ]
        else:
            text = "❌ Модель не найдена"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="worker_models")]]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data.startswith("delete_model_"):
        # Подтверждение удаления
        model_id = int(data.split("_")[2])
        
        text = "⚠️ <b>Вы уверены, что хотите удалить эту модель?</b>\n\nЭто действие нельзя отменить!"
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{model_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"model_{model_id}")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif data.startswith("confirm_delete_"):
        # Удаление модели
        model_id = int(data.split("_")[2])
        
        if delete_model(model_id):
            text = "✅ Модель успешно удалена!"
        else:
            text = "❌ Ошибка при удалении модели"
        
        keyboard = [[InlineKeyboardButton("◀️ К моделям", callback_data="worker_models")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


# ============================================
# СОЗДАНИЕ МОДЕЛИ - ConversationHandler
# ============================================

async def create_model_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания модели"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['new_model'] = {}
    
    text = (
        "➕ <b>Создание новой модели</b>\n\n"
        "Шаг 1/10: Введите <b>имя</b> модели\n\n"
        "<i>Например: Анна, Виктория, Мария</i>"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_NAME

async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение имени"""
    name = update.message.text.strip()
    
    if len(name) < 2 or len(name) > 30:
        await update.message.reply_text("❌ Имя должно быть от 2 до 30 символов. Попробуйте снова:")
        return CREATE_NAME
    
    context.user_data['new_model']['name'] = name
    
    text = (
        f"✅ Имя: <b>{name}</b>\n\n"
        "Шаг 2/10: Введите <b>возраст</b> (18-60)"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_AGE

async def create_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение возраста"""
    try:
        age = int(update.message.text.strip())
        if age < 18 or age > 60:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Введите корректный возраст (18-60):")
        return CREATE_AGE
    
    context.user_data['new_model']['age'] = age
    
    text = (
        f"✅ Возраст: <b>{age}</b>\n\n"
        "Шаг 3/10: Введите <b>город</b>\n\n"
        "<i>Например: Москва, Санкт-Петербург, Казань</i>"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_CITY

async def create_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение города"""
    city = update.message.text.strip()
    
    if len(city) < 2:
        await update.message.reply_text("❌ Введите корректный город:")
        return CREATE_CITY
    
    context.user_data['new_model']['city'] = city
    
    text = (
        f"✅ Город: <b>{city}</b>\n\n"
        "Шаг 4/10: Введите <b>рост</b> в см (140-210)"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_HEIGHT

async def create_height(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение роста"""
    try:
        height = int(update.message.text.strip())
        if height < 140 or height > 210:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Введите корректный рост (140-210 см):")
        return CREATE_HEIGHT
    
    context.user_data['new_model']['height'] = height
    
    text = (
        f"✅ Рост: <b>{height} см</b>\n\n"
        "Шаг 5/10: Введите <b>вес</b> в кг (35-120)"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_WEIGHT


async def create_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение веса"""
    try:
        weight = int(update.message.text.strip())
        if weight < 35 or weight > 120:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Введите корректный вес (35-120 кг):")
        return CREATE_WEIGHT
    
    context.user_data['new_model']['weight'] = weight
    
    text = (
        f"✅ Вес: <b>{weight} кг</b>\n\n"
        "Шаг 6/10: Введите <b>размер груди</b> (1-10)"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_BUST

async def create_bust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение размера груди"""
    try:
        bust = int(update.message.text.strip())
        if bust < 1 or bust > 10:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Введите корректный размер груди (1-10):")
        return CREATE_BUST
    
    context.user_data['new_model']['bust'] = bust
    
    text = (
        f"✅ Грудь: <b>{bust}</b>\n\n"
        "Шаг 7/10: Введите <b>цену за час</b> в рублях (от 1000)"
    )
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_PRICE

async def create_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение цены"""
    try:
        price = int(update.message.text.strip().replace(' ', '').replace('₽', ''))
        if price < 1000:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Введите корректную цену (от 1000 ₽):")
        return CREATE_PRICE
    
    context.user_data['new_model']['price'] = price
    
    text = (
        f"✅ Цена: <b>{price} ₽/час</b>\n\n"
        "Шаг 8/10: Введите <b>описание</b> модели\n\n"
        "<i>Опишите внешность, характер, особенности</i>"
    )
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_description")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_DESCRIPTION

async def create_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение описания"""
    description = update.message.text.strip()
    context.user_data['new_model']['description'] = description
    
    return await ask_services(update, context)

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск описания"""
    query = update.callback_query
    await query.answer()
    context.user_data['new_model']['description'] = ''
    
    return await ask_services_callback(update, context)

async def ask_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос услуг"""
    text = (
        "Шаг 9/10: Введите <b>услуги</b> через запятую\n\n"
        "<i>Например: Классика, Минет, Массаж, Эскорт</i>\n\n"
        "Доступные услуги:\n"
        "Классика, Минет, Анал, Массаж, Массаж эротический, "
        "Куннилингус, БДСМ, Ролевые игры, Стриптиз, Эскорт, Выезд, Апартаменты"
    )
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_services")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CREATE_SERVICES

async def ask_services_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос услуг (callback)"""
    query = update.callback_query
    text = (
        "Шаг 9/10: Введите <b>услуги</b> через запятую\n\n"
        "<i>Например: Классика, Минет, Массаж, Эскорт</i>"
    )
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_services")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CREATE_SERVICES


async def create_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение услуг"""
    services_text = update.message.text.strip()
    services = [s.strip() for s in services_text.split(',') if s.strip()]
    context.user_data['new_model']['services'] = services
    
    return await ask_images(update, context)

async def skip_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск услуг"""
    query = update.callback_query
    await query.answer()
    context.user_data['new_model']['services'] = ['Классика', 'Массаж']
    
    return await ask_images_callback(update, context)

async def ask_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос фото"""
    # Инициализируем список фото если его нет
    if 'images' not in context.user_data['new_model']:
        context.user_data['new_model']['images'] = []
    
    current_count = len(context.user_data['new_model']['images'])
    
    text = (
        f"📸 <b>Шаг 10/10: Отправьте фото</b>\n\n"
        f"Загружено: <b>{current_count}</b> фото\n\n"
        "Отправляйте фото из галереи (jpg, png).\n"
        "Можно отправлять по одному или несколько сразу.\n\n"
        "<i>Когда закончите — нажмите «✅ Готово»</i>"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Готово", callback_data="done_images")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CREATE_IMAGES

async def ask_images_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос фото (callback)"""
    query = update.callback_query
    
    # Инициализируем список фото если его нет
    if 'images' not in context.user_data['new_model']:
        context.user_data['new_model']['images'] = []
    
    current_count = len(context.user_data['new_model']['images'])
    
    text = (
        f"📸 <b>Шаг 10/10: Отправьте фото</b>\n\n"
        f"Загружено: <b>{current_count}</b> фото\n\n"
        "Отправляйте фото из галереи (jpg, png).\n"
        "Можно отправлять по одному или несколько сразу.\n\n"
        "<i>Когда закончите — нажмите «✅ Готово»</i>"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Готово", callback_data="done_images")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CREATE_IMAGES

async def create_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение фото из галереи"""
    # Проверяем есть ли фото в сообщении
    if not update.message.photo:
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте фото из галереи, а не текст.\n"
            "Нажмите 📎 и выберите фото."
        )
        return CREATE_IMAGES
    
    # Получаем фото максимального размера
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # Сохраняем URL фото из Telegram
    photo_url = file.file_path
    
    # Добавляем в список
    if 'images' not in context.user_data['new_model']:
        context.user_data['new_model']['images'] = []
    
    context.user_data['new_model']['images'].append(photo_url)
    current_count = len(context.user_data['new_model']['images'])
    
    # Отправляем подтверждение
    text = (
        f"✅ Фото #{current_count} загружено!\n\n"
        f"Всего фото: <b>{current_count}</b>\n\n"
        "Отправьте ещё фото или нажмите «✅ Готово»"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Готово", callback_data="done_images")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return CREATE_IMAGES

async def done_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершение загрузки фото"""
    query = update.callback_query
    await query.answer()
    
    images = context.user_data['new_model'].get('images', [])
    
    if not images:
        # Если фото не загружены, ставим заглушку
        context.user_data['new_model']['images'] = [
            'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400'
        ]
        await query.edit_message_text("⚠️ Фото не загружены, будет использовано фото по умолчанию.")
    
    return await show_confirmation_callback(update, context)

async def skip_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск фото - теперь это done_images"""
    return await done_images(update, context)

async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показ подтверждения"""
    model = context.user_data['new_model']
    services = ', '.join(model.get('services', [])[:5])
    
    text = (
        "📋 <b>Проверьте данные модели:</b>\n\n"
        f"👤 Имя: <b>{model['name']}</b>\n"
        f"🎂 Возраст: <b>{model['age']}</b>\n"
        f"📍 Город: <b>{model['city']}</b>\n"
        f"📏 Рост: <b>{model['height']} см</b>\n"
        f"⚖️ Вес: <b>{model['weight']} кг</b>\n"
        f"👙 Грудь: <b>{model['bust']}</b>\n"
        f"💰 Цена: <b>{model['price']} ₽/час</b>\n"
        f"📝 Описание: {model.get('description', 'не указано')[:100]}...\n"
        f"🔧 Услуги: {services}\n"
        f"🖼 Фото: {len(model.get('images', []))}\n\n"
        "Всё верно?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Создать", callback_data="confirm_create")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CREATE_CONFIRM

async def show_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показ подтверждения (callback)"""
    query = update.callback_query
    model = context.user_data['new_model']
    services = ', '.join(model.get('services', [])[:5])
    
    text = (
        "📋 <b>Проверьте данные модели:</b>\n\n"
        f"👤 Имя: <b>{model['name']}</b>\n"
        f"🎂 Возраст: <b>{model['age']}</b>\n"
        f"📍 Город: <b>{model['city']}</b>\n"
        f"📏 Рост: <b>{model['height']} см</b>\n"
        f"⚖️ Вес: <b>{model['weight']} кг</b>\n"
        f"👙 Грудь: <b>{model['bust']}</b>\n"
        f"💰 Цена: <b>{model['price']} ₽/час</b>\n"
        f"🔧 Услуги: {services}\n"
        f"🖼 Фото: {len(model.get('images', []))}\n\n"
        "Всё верно?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Создать", callback_data="confirm_create")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CREATE_CONFIRM


async def confirm_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение создания"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    worker = await get_or_create_worker(user)
    
    if not worker:
        await query.edit_message_text("❌ Ошибка")
        return ConversationHandler.END
    
    model_data = context.user_data.get('new_model', {})
    result = create_model(worker['id'], model_data)
    
    if result:
        text = (
            "✅ <b>Модель успешно создана!</b>\n\n"
            f"👤 {result['name']}, {result['age']}\n"
            f"📍 {result['city']}\n"
            f"💰 {result['price']} ₽/час\n\n"
            "Модель уже отображается на сайте!"
        )
    else:
        text = "❌ Ошибка при создании модели. Попробуйте позже."
    
    keyboard = [[InlineKeyboardButton("◀️ К моделям", callback_data="worker_models")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    context.user_data.pop('new_model', None)
    return ConversationHandler.END

async def cancel_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена создания"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop('new_model', None)
    
    text = "❌ Создание модели отменено"
    keyboard = [[InlineKeyboardButton("◀️ В меню", callback_data="worker_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    return ConversationHandler.END

# ============================================
# ОБРАБОТЧИК СООБЩЕНИЙ
# ============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик всех текстовых сообщений"""
    user = update.effective_user
    user_name = user.first_name if user.first_name else "друг"
    
    response_text = f"👋 Привет, {user_name}! Для использования OneNight нажми на кнопку ниже:"
    
    keyboard = [
        [InlineKeyboardButton("🚀 Открыть OneNight", web_app=WebAppInfo(url=Config.WEB_APP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(response_text, reply_markup=reply_markup)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}")

# ============================================
# MAIN
# ============================================

def main() -> None:
    """Основная функция для запуска бота"""
    
    if not Config.validate():
        sys.exit(1)
    
    # Создаем приложение с оптимизациями
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Настройки для более быстрой работы
    application.bot_data['pool_timeout'] = 1.0
    application.bot_data['read_timeout'] = 5.0
    application.bot_data['write_timeout'] = 5.0
    application.bot_data['connect_timeout'] = 5.0
    
    # ConversationHandler для создания модели
    create_model_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_model_start, pattern="^create_model$")],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            CREATE_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_age)],
            CREATE_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_city)],
            CREATE_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_height)],
            CREATE_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_weight)],
            CREATE_BUST: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_bust)],
            CREATE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_price)],
            CREATE_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_description),
                CallbackQueryHandler(skip_description, pattern="^skip_description$")
            ],
            CREATE_SERVICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_services),
                CallbackQueryHandler(skip_services, pattern="^skip_services$")
            ],
            CREATE_IMAGES: [
                MessageHandler(filters.PHOTO, create_images),
                CallbackQueryHandler(done_images, pattern="^done_images$"),
                CallbackQueryHandler(skip_images, pattern="^skip_images$")
            ],
            CREATE_CONFIRM: [
                CallbackQueryHandler(confirm_create, pattern="^confirm_create$"),
                CallbackQueryHandler(cancel_create, pattern="^cancel_create$")
            ]
        },
        fallbacks=[CallbackQueryHandler(cancel_create, pattern="^cancel_create$")],
        per_message=True,  # Изменено для лучшей производительности
        conversation_timeout=300  # 5 минут таймаут
    )
    
    # ConversationHandler для админ панели
    admin_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_callback, pattern="^admin_edit_card$"),
            CallbackQueryHandler(admin_callback, pattern="^admin_edit_support$")
        ],
        states={
            ADMIN_EDIT_CARD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_card),
                CallbackQueryHandler(admin_callback, pattern="^admin_menu$")
            ],
            ADMIN_EDIT_SUPPORT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_support),
                CallbackQueryHandler(admin_callback, pattern="^admin_menu$")
            ]
        },
        fallbacks=[CallbackQueryHandler(admin_callback, pattern="^admin_menu$")],
        per_message=True,  # Изменено для лучшей производительности
        conversation_timeout=300  # 5 минут таймаут
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("worker", worker_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(create_model_handler)
    application.add_handler(admin_handler)
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(worker_panel_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    logger.info("🚀 Запуск OneNight Telegram Bot...")
    
    # Запускаем с оптимизированными настройками
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        poll_interval=0.1,  # Более частые проверки обновлений
        timeout=10,         # Таймаут для long polling
        bootstrap_retries=3,
        read_timeout=5,
        write_timeout=5,
        connect_timeout=5,
        pool_timeout=1
    )

if __name__ == '__main__':
    main()