import logging
import sys
import asyncio
import html  # ВАЖНО: Для защиты HTML разметки
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from supabase import create_client, Client
from config import Config

# ============================================
# 1. НАСТРОЙКИ
# ============================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

try:
    supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
except Exception as e:
    logger.critical(f"FATAL: Ошибка Supabase: {e}")
    sys.exit(1)

# Состояния
(CREATE_NAME, CREATE_AGE, CREATE_CITY, CREATE_HEIGHT, CREATE_WEIGHT,
 CREATE_BUST, CREATE_PRICE, CREATE_DESCRIPTION, CREATE_SERVICES, CREATE_IMAGES) = range(10)

# ============================================
# 2. БАЗА ДАННЫХ (DB Layer)
# ============================================

class Cache:
    def __init__(self):
        self._data = {}
        self._expiry = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self._data:
            if datetime.now() < self._expiry[key]:
                return self._data[key]
            del self._data[key]
        return None

    def set(self, key: str, value: Any, ttl_seconds: int = 300):
        self._data[key] = value
        self._expiry[key] = datetime.now() + timedelta(seconds=ttl_seconds)

    def clear(self, prefix: str = None):
        if prefix:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys: del self._data[k]
        else:
            self._data.clear()

db_cache = Cache()

class DB:
    @staticmethod
    async def _run(func):
        return await asyncio.to_thread(func)

    @staticmethod
    async def get_worker(user) -> dict:
        """Получает или создает воркера. Кэширует результат."""
        cache_key = f"worker_{user.id}"
        cached = db_cache.get(cache_key)
        if cached: return cached

        def query():
            res = supabase.table('workers').select('*').eq('telegram_id', user.id).execute()
            if res.data:
                # Обновляем активность в фоне
                try:
                    supabase.table('workers').update({
                        'username': user.username,
                        'first_name': user.first_name,
                        'last_activity': datetime.now().isoformat()
                    }).eq('telegram_id', user.id).execute()
                except: pass
                return res.data[0]
            
            # Создаем нового
            try:
                new_w = supabase.table('workers').insert({
                    'telegram_id': user.id,
                    'username': user.username,
                    'first_name': user.first_name
                }).execute()
                return new_w.data[0] if new_w.data else None
            except: return None

        worker = await DB._run(query)
        if worker: db_cache.set(cache_key, worker, ttl_seconds=120)
        return worker

    @staticmethod
    async def register_referral(user, referral_code: str) -> Optional[int]:
        """
        Регистрирует реферала.
        Возвращает telegram_id воркера, если регистрация успешна (для уведомления).
        Возвращает None, если пользователь уже есть или код неверный.
        """
        def query():
            try:
                # 1. Ищем воркера по коду
                referrer = supabase.table('workers').select('id, telegram_id').eq('referral_code', referral_code).execute()
                if not referrer.data:
                    return None
                
                worker_data = referrer.data[0]
                
                # 2. Проверяем, не зарегистрирован ли уже этот клиент
                existing = supabase.table('worker_clients').select('id').eq('telegram_id', user.id).execute()
                if existing.data:
                    return None # Уже был
                
                # 3. Регистрируем
                supabase.table('worker_clients').insert({
                    'worker_id': worker_data['id'],
                    'telegram_id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name
                }).execute()
                
                # Сбрасываем кэш статистики воркера
                return worker_data['telegram_id']
            except Exception as e:
                logger.error(f"Ref error: {e}")
                return None
        
        referrer_tg_id = await DB._run(query)
        if referrer_tg_id:
             db_cache.clear(f"stats_{referrer_tg_id}") # Чистим кэш статистики этого воркера
        return referrer_tg_id

    @staticmethod
    async def get_worker_stats(worker_id: int) -> dict:
        """Получает статистику (кэшируется)"""
        cache_key = f"stats_id_{worker_id}"
        cached = db_cache.get(cache_key)
        if cached: return cached

        def query():
            c = supabase.table('worker_clients').select('id', count='exact').eq('worker_id', worker_id).execute()
            m = supabase.table('profiles').select('id', count='exact').eq('worker_id', worker_id).eq('is_active', True).execute()
            return {'clients': c.count, 'models': m.count}
        
        stats = await DB._run(query)
        db_cache.set(cache_key, stats, ttl_seconds=60)
        return stats

    @staticmethod
    async def get_worker_clients_list(worker_id: int, limit=20):
        """Получает список последних клиентов"""
        def query():
            return supabase.table('worker_clients')\
                .select('first_name, username, created_at')\
                .eq('worker_id', worker_id)\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute().data
        return await DB._run(query)

    @staticmethod
    async def get_models_short(worker_id: int):
        def query():
            return supabase.table('profiles').select('id, name, age, price').eq('worker_id', worker_id).eq('is_active', True).execute().data
        return await DB._run(query)

    @staticmethod
    async def create_model(worker_id: int, data: dict):
        def query():
            model = {
                'worker_id': worker_id,
                'name': data['name'], 'age': data['age'], 'city': data['city'],
                'height': data['height'], 'weight': data['weight'], 'bust': data['bust'],
                'price': data['price'], 'description': data.get('description', ''),
                'services': data.get('services', []), 'images': data.get('images', []),
                'isVerified': True
            }
            return supabase.table('profiles').insert(model).execute().data[0]
        return await DB._run(query)
    
    @staticmethod
    async def delete_model(model_id: int):
        def query():
            return supabase.table('profiles').update({'is_active': False}).eq('id', model_id).execute()
        return await DB._run(query)

# ============================================
# 3. ОСНОВНЫЕ КОМАНДЫ
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # === ЛОГИКА РЕФЕРАЛОВ И УВЕДОМЛЕНИЙ ===
    if context.args:
        ref_code = context.args[0]
        # Пытаемся зарегистрировать и получаем ID воркера
        referrer_id = await DB.register_referral(user, ref_code)
        
        if referrer_id:
            # Отправляем уведомление воркеру
            try:
                safe_name = html.escape(user.first_name)
                username_text = f"(@{user.username})" if user.username else ""
                msg = (
                    f"🔔 <b>Новый реферал!</b>\n\n"
                    f"👤 Клиент: <b>{safe_name}</b> {username_text}\n"
                    f"📅 Дата: {datetime.now().strftime('%d.%m %H:%M')}"
                )
                await context.bot.send_message(chat_id=referrer_id, text=msg, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление воркеру {referrer_id}: {e}")
    # ========================================

    # Экранируем имя, чтобы HTML не ломался
    safe_user_name = html.escape(user.first_name)
    
    text = (
        f"👋 <b>Привет, {safe_user_name}!</b>\n\n"
        "Добро пожаловать в OneNight.\n"
        "Здесь ты найдешь лучшие анкеты для отдыха.\n\n"
        "👇 <b>Нажми кнопку ниже, чтобы начать:</b>"
    )
    
    keyboard = [[InlineKeyboardButton("🚀 Открыть приложение", web_app=WebAppInfo(url=Config.WEB_APP_URL))]]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    
    # Тихо удаляем ReplyKeyboard (отправляем и сразу удаляем сообщение)
    async def remove_keyboard():
        try:
            msg = await context.bot.send_message(
                update.effective_chat.id, 
                "⠀",  # невидимый символ
                reply_markup=ReplyKeyboardRemove()
            )
            await msg.delete()
        except:
            pass
    asyncio.create_task(remove_keyboard())

async def worker_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    worker = await DB.get_worker(user)
    
    if not worker:
        await update.message.reply_text("❌ Ошибка профиля")
        return

    stats = await DB.get_worker_stats(worker['id'])
    
    ref_link = f"https://t.me/{(await context.bot.get_me()).username}?start={worker['referral_code']}"
    
    text = (
        f"👷 <b>Кабинет Воркера</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🆔 ID: <code>{worker['telegram_id']}</code>\n\n"
        f"📊 <b>Твоя статистика:</b>\n"
        f"├ 👥 Клиентов: <b>{stats['clients']}</b>\n"
        f"└ 💃 Моделей: <b>{stats['models']}</b>\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n"
        f"<code>{ref_link}</code>"
    )
    
    kb = [
        [InlineKeyboardButton("👥 Мои клиенты", callback_data="worker_clients")],
        [InlineKeyboardButton("💃 Мои модели", callback_data="worker_models")],
        [InlineKeyboardButton("➕ Создать модель", callback_data="create_model")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

# ============================================
# 4. ОБРАБОТЧИКИ МЕНЮ (CALLBACKS)
# ============================================

async def worker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = update.effective_user
    worker = await DB.get_worker(user)
    if not worker: return

    if data == "worker_menu":
        # Возврат в главное меню
        stats = await DB.get_worker_stats(worker['id'])
        ref_link = f"https://t.me/{(await context.bot.get_me()).username}?start={worker['referral_code']}"
        text = (
            f"👷 <b>Кабинет Воркера</b>\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"📊 Клиентов: <b>{stats['clients']}</b> | Моделей: <b>{stats['models']}</b>\n"
            f"🔗 Ссылка: <code>{ref_link}</code>"
        )
        kb = [
            [InlineKeyboardButton("👥 Мои клиенты", callback_data="worker_clients")],
            [InlineKeyboardButton("💃 Мои модели", callback_data="worker_models")],
            [InlineKeyboardButton("➕ Создать модель", callback_data="create_model")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data == "worker_clients":
        # === СПИСОК КЛИЕНТОВ ===
        clients = await DB.get_worker_clients_list(worker['id'])
        
        if not clients:
            text = "👥 <b>Мои клиенты</b>\n\n😔 У вас пока нет рефералов.\nРаспространяйте свою ссылку!"
        else:
            text = f"👥 <b>Последние клиенты ({len(clients)}):</b>\n\n"
            for c in clients:
                # Парсим дату
                try:
                    date_obj = datetime.fromisoformat(c['created_at'].replace('Z', ''))
                    date_str = date_obj.strftime('%d.%m')
                except:
                    date_str = "??"
                
                safe_name = html.escape(c['first_name'] or "Без имени")
                link = f"@{c['username']}" if c['username'] else "Нет юзернейма"
                
                text += f"👤 <b>{safe_name}</b> ({link}) — {date_str}\n"

        kb = [[InlineKeyboardButton("◀️ Назад", callback_data="worker_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data == "worker_models":
        # Список моделей
        models = await DB.get_models_short(worker['id'])
        if not models:
            text = "💃 <b>Мои модели</b>\n\nСписок пуст."
            kb = [[InlineKeyboardButton("➕ Создать", callback_data="create_model")],
                  [InlineKeyboardButton("◀️ Назад", callback_data="worker_menu")]]
        else:
            text = f"💃 <b>Мои модели ({len(models)}):</b>"
            kb = []
            for m in models:
                kb.append([InlineKeyboardButton(f"{m['name']}, {m['age']} — {m['price']}₽", callback_data=f"del_ask_{m['id']}")])
            kb.append([InlineKeyboardButton("➕ Добавить новую", callback_data="create_model")])
            kb.append([InlineKeyboardButton("◀️ В меню", callback_data="worker_menu")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("del_ask_"):
        mid = data.split("_")[2]
        text = "🗑 <b>Удалить эту анкету?</b>\nВосстановить будет невозможно."
        kb = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"del_confirm_{mid}")],
            [InlineKeyboardButton("❌ Нет, назад", callback_data="worker_models")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("del_confirm_"):
        mid = int(data.split("_")[2])
        await DB.delete_model(mid)
        # Чистим кэш
        db_cache.clear(f"stats_id_{worker['id']}")
        await query.answer("Анкета удалена!", show_alert=True)
        # Возвращаемся к списку (рекурсивный вызов, но безопасно тут)
        # Лучше просто вызвать отрисовку меню заново
        await worker_callback(update, context) # Хаки, лучше перерисовать, но для краткости

# ============================================
# 5. СОЗДАНИЕ АНКЕТЫ (WIZARD)
# ============================================

async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['new'] = {}
    
    text = "📝 <b>Создание анкеты (1/10)</b>\n\nВведите <b>Имя</b> девушки:"
    kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return CREATE_NAME

async def input_process(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                        key: str, next_step: int, 
                        prompt: str, validator=None, transform=None):
    """Универсальная функция для шагов"""
    text = update.message.text.strip()
    
    # Экранируем ввод пользователя для безопасности HTML
    safe_text = html.escape(text)

    if validator:
        try:
            if not validator(text): raise ValueError()
        except:
            await update.message.reply_text("❌ <b>Ошибка!</b> Некорректный формат.\nПопробуйте снова:", parse_mode=ParseMode.HTML)
            return None # Остаемся на шаге

    value = transform(text) if transform else safe_text
    context.user_data['new'][key] = value
    
    kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]]
    await update.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return next_step

# --- ШАГИ ---

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await input_process(update, context, 'name', CREATE_AGE, 
        "📝 <b>Шаг 2/10</b>\nВведите <b>возраст</b> (18-60):") or CREATE_NAME

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await input_process(update, context, 'age', CREATE_CITY, 
        "📝 <b>Шаг 3/10</b>\nВведите <b>Город</b>:", 
        validator=lambda x: 18 <= int(x) <= 60, transform=int) or CREATE_AGE

async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await input_process(update, context, 'city', CREATE_HEIGHT, 
        "📝 <b>Шаг 4/10</b>\nВведите <b>Рост</b> (см):") or CREATE_CITY

async def get_height(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await input_process(update, context, 'height', CREATE_WEIGHT, 
        "📝 <b>Шаг 5/10</b>\nВведите <b>Вес</b> (кг):", transform=int) or CREATE_HEIGHT

async def get_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await input_process(update, context, 'weight', CREATE_BUST, 
        "📝 <b>Шаг 6/10</b>\nВведите размер <b>груди</b> (1-10):", transform=int) or CREATE_WEIGHT

async def get_bust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await input_process(update, context, 'bust', CREATE_PRICE, 
        "📝 <b>Шаг 7/10</b>\nВведите <b>Цену</b> за час (только цифры):", transform=int) or CREATE_BUST

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    res = await input_process(update, context, 'price', CREATE_DESCRIPTION, 
        "📝 <b>Шаг 8/10</b>\nВведите <b>описание</b> анкеты:\n\n<i>Опишите внешность, характер, особенности.\nМожно пропустить — нажмите кнопку ниже.</i>", 
        validator=lambda x: int(x.replace(' ', '')) > 0, transform=lambda x: int(x.replace(' ', '')))
    
    if res:
        kb = [
            [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_description")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
        ]
        await update.message.reply_text("👇 Введите описание или пропустите:", reply_markup=InlineKeyboardMarkup(kb))
    return res or CREATE_PRICE

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение описания"""
    text = update.message.text.strip()
    safe_text = html.escape(text)
    context.user_data['new']['description'] = safe_text
    
    services_list = (
        "📝 <b>Шаг 9/10</b>\nВведите <b>услуги</b> через запятую:\n\n"
        "<i>Например: Классика, Минет, Массаж, Эскорт</i>\n\n"
        "Доступные услуги:\n"
        "Классика, Минет, Анал, Массаж, Массаж эротический, "
        "Куннилингус, БДСМ, Ролевые игры, Стриптиз, Эскорт, Выезд, Апартаменты"
    )
    kb = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_services")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(services_list, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return CREATE_SERVICES

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск описания"""
    query = update.callback_query
    await query.answer()
    context.user_data['new']['description'] = ''
    
    services_list = (
        "📝 <b>Шаг 9/10</b>\nВведите <b>услуги</b> через запятую:\n\n"
        "<i>Например: Классика, Минет, Массаж, Эскорт</i>\n\n"
        "Доступные услуги:\n"
        "Классика, Минет, Анал, Массаж, Массаж эротический, "
        "Куннилингус, БДСМ, Ролевые игры, Стриптиз, Эскорт, Выезд, Апартаменты"
    )
    kb = [
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_services")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await query.edit_message_text(services_list, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    return CREATE_SERVICES

async def get_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение услуг"""
    text = update.message.text.strip()
    services = [html.escape(s.strip()) for s in text.split(',') if s.strip()]
    context.user_data['new']['services'] = services
    
    kb = [
        [InlineKeyboardButton("✅ Готово", callback_data="done_images")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await update.message.reply_text(
        "📸 <b>Шаг 10/10</b>\nОтправьте <b>ФОТО</b> (можно несколько).\n\nКогда закончите — нажмите «✅ Готово»",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML
    )
    return CREATE_IMAGES

async def skip_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск услуг"""
    query = update.callback_query
    await query.answer()
    context.user_data['new']['services'] = ['Классика', 'Массаж']
    
    kb = [
        [InlineKeyboardButton("✅ Готово", callback_data="done_images")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    await query.edit_message_text(
        "📸 <b>Шаг 10/10</b>\nОтправьте <b>ФОТО</b> (можно несколько).\n\nКогда закончите — нажмите «✅ Готово»",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML
    )
    return CREATE_IMAGES

async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo: 
        await update.message.reply_text("❌ Это не фото.")
        return CREATE_IMAGES
    
    if 'images' not in context.user_data['new']: context.user_data['new']['images'] = []
    
    # Берем лучшее качество
    file_id = update.message.photo[-1].file_id
    file_path = (await context.bot.get_file(file_id)).file_path
    
    context.user_data['new']['images'].append(file_path)
    count = len(context.user_data['new']['images'])
    
    kb = [[InlineKeyboardButton("✅ Готово, создать", callback_data="done_images")]]
    await update.message.reply_text(f"✅ Фото #{count} сохранено.\nЕще фото или Готово?", reply_markup=InlineKeyboardMarkup(kb))
    return CREATE_IMAGES

async def finish_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = context.user_data.get('new')
    if not data or not data.get('images'):
        data['images'] = ['https://via.placeholder.com/400'] # Заглушка
    
    user = update.effective_user
    worker = await DB.get_worker(user)
    
    await query.edit_message_text("⏳ <b>Сохраняем анкету в базу...</b>", parse_mode=ParseMode.HTML)
    
    await DB.create_model(worker['id'], data)
    
    # Чистим кэш
    db_cache.clear(f"stats_id_{worker['id']}")
    
    await query.edit_message_text(
        f"✅ <b>Анкета {data['name']} успешно создана!</b>\nОна уже видна в поиске.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="worker_menu")]]),
        parse_mode=ParseMode.HTML
    )
    context.user_data.pop('new', None)
    return ConversationHandler.END

async def cancel_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.edit_message_text("❌ Создание отменено.", 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Меню", callback_data="worker_menu")]]))
    return ConversationHandler.END

# ============================================
# MAIN
# ============================================

def main():
    app = Application.builder().token(Config.BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_start, pattern="^create_model$")],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT, get_name)],
            CREATE_AGE: [MessageHandler(filters.TEXT, get_age)],
            CREATE_CITY: [MessageHandler(filters.TEXT, get_city)],
            CREATE_HEIGHT: [MessageHandler(filters.TEXT, get_height)],
            CREATE_WEIGHT: [MessageHandler(filters.TEXT, get_weight)],
            CREATE_BUST: [MessageHandler(filters.TEXT, get_bust)],
            CREATE_PRICE: [MessageHandler(filters.TEXT, get_price)],
            CREATE_DESCRIPTION: [
                MessageHandler(filters.TEXT, get_description),
                CallbackQueryHandler(skip_description, pattern="^skip_description$")
            ],
            CREATE_SERVICES: [
                MessageHandler(filters.TEXT, get_services),
                CallbackQueryHandler(skip_services, pattern="^skip_services$")
            ],
            CREATE_IMAGES: [
                MessageHandler(filters.PHOTO, get_photo),
                CallbackQueryHandler(finish_create, pattern="^done_images$")
            ]
        },
        fallbacks=[CallbackQueryHandler(cancel_create, pattern="^cancel_create$")]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("worker", worker_panel))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(worker_callback))

    print("🚀 Bot started (Optimized + Notifications)")
    app.run_polling()

if __name__ == '__main__':
    main()
