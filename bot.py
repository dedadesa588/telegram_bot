import logging
import sqlite3
import random
import time
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен бота (замените на свой)
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7624971330:AAF5ubAHuOQ532clkZW8oBfjpF8e_Yq-IFc')

# Константы
FARM_COOLDOWN = 3600  # 1 час в секундах
MIN_STARS = 1
MAX_STARS = 2

# Функция для проверки является ли пользователь администратором
async def is_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except:
        return False

# Функция полного сброса статистики
def reset_all_stats(chat_id: int):
    conn = sqlite3.connect('stars_bot.db')
    cursor = conn.cursor()
    
    # Полностью очищаем таблицу для этого чата
    cursor.execute('DELETE FROM users WHERE chat_id = ?', (chat_id,))
    
    conn.commit()
    conn.close()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('stars_bot.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER,
        chat_id INTEGER,
        username TEXT,
        first_name TEXT,
        stars INTEGER DEFAULT 0,
        multiplier REAL DEFAULT 1.0,
        level INTEGER DEFAULT 1,
        last_farm_time INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, chat_id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Функция для получения пользователя
def get_user(user_id, chat_id, username, first_name):
    conn = sqlite3.connect('stars_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute('''
        INSERT INTO users (user_id, chat_id, username, first_name)
        VALUES (?, ?, ?, ?)
        ''', (user_id, chat_id, username, first_name))
        conn.commit()
        user = (user_id, chat_id, username, first_name, 0, 1.0, 1, 0)
    
    conn.close()
    return user

# Функция для обновления пользователя
def update_user(user_id, chat_id, **kwargs):
    conn = sqlite3.connect('stars_bot.db')
    cursor = conn.cursor()
    
    set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
    values = list(kwargs.values()) + [user_id, chat_id]
    
    cursor.execute(f'UPDATE users SET {set_clause} WHERE user_id = ? AND chat_id = ?', values)
    conn.commit()
    conn.close()

# Расчет стоимости улучшения
def get_upgrade_cost(level):
    return level * 5

# Проверка времени для фарма
def can_farm(last_farm_time):
    current_time = time.time()
    return current_time - last_farm_time >= FARM_COOLDOWN

# Получение оставшегося времени
def get_remaining_time(last_farm_time):
    current_time = time.time()
    elapsed = current_time - last_farm_time
    remaining = max(0, FARM_COOLDOWN - elapsed)
    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)
    seconds = int(remaining % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        await update.message.reply_text("Этот бот предназначен для работы в групповых чатах!")
        return
    
    get_user(user.id, chat.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("🌟 Профиль", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="toplist")],
        [InlineKeyboardButton("🌾 Фармить звёзды", callback_data=f"farm_{user.id}")]
    ]
    
    # Добавляем кнопку для админов
    if await is_admin(context, user.id, chat.id):
        keyboard.append([InlineKeyboardButton("🔄 Сбросить статистику (Admin)", callback_data="admin_reset")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Привет, {user.first_name}! Добро пожаловать в бот звезд!\n\n"
        "Каждый час ты можешь получать от 1 до 2 звезд с помощью команды /farm.\n"
        "Накопи звезды и улучшай свой множитель!",
        reply_markup=reply_markup
    )

# Обработчик команды сброса статистики (только для админов)
async def reset_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        await update.message.reply_text("Эта команда работает только в групповых чатах!")
        return
    
    # Проверяем права администратора
    if not await is_admin(context, user.id, chat.id):
        await update.message.reply_text("❌ Только администраторы могут сбрасывать статистику!")
        return
    
    # Создаем клавиатуру с подтверждением
    keyboard = [
        [InlineKeyboardButton("✅ Да, сбросить всё", callback_data=f"confirm_reset_{chat.id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_reset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚠️ ВНИМАНИЕ! Вы уверены что хотите сбросить ВСЮ статистику?\n\n"
        "Это действие:\n"
        "• Обнулит все звёзды у всех игроков\n"
        "• Сбросит все уровни и множители\n"
        "• Удалит всю историю в этом чате\n\n"
        "Действие необратимо!",
        reply_markup=reply_markup
    )

# Обработчик команды /farm
async def farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        await update.message.reply_text("Эта команда работает только в групповых чатах!")
        return
    
    user_data = get_user(user.id, chat.id, user.username, user.first_name)
    last_farm_time = user_data[7]
    
    if not can_farm(last_farm_time):
        remaining = get_remaining_time(last_farm_time)
        await update.message.reply_text(
            f"⏰ Вы уже фармили недавно! Попробуйте снова через {remaining}"
        )
        return
    
    # Генерируем звёзды (1-2)
    base_stars = random.randint(MIN_STARS, MAX_STARS)
    multiplier = user_data[5]
    actual_stars = int(base_stars * multiplier)
    new_stars = user_data[4] + actual_stars
    current_time = time.time()
    
    # Обновляем данные пользователя
    update_user(user.id, chat.id, stars=new_stars, last_farm_time=current_time)
    
    # Формируем сообщение
    message = (
        f"🌟 {user.first_name} получил {actual_stars} звёзд!\n"
        f"📊 База: {base_stars} | Множитель: x{multiplier}\n"
        f"💰 Теперь у вас: {new_stars} звёзд"
    )
    
    keyboard = [
        [InlineKeyboardButton("🌟 Профиль", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="toplist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup)

# Обработчик команды /profile
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        await update.message.reply_text("Эта команда работает только в групповых чатах!")
        return
    
    user_data = get_user(user.id, chat.id, user.username, user.first_name)
    stars = user_data[4]
    multiplier = user_data[5]
    level = user_data[6]
    last_farm_time = user_data[7]
    upgrade_cost = get_upgrade_cost(level)
    
    # Проверяем время до следующего фарма
    if can_farm(last_farm_time):
        farm_status = "✅ Готов к фарму!"
    else:
        remaining = get_remaining_time(last_farm_time)
        farm_status = f"⏰ До фарма: {remaining}"
    
    keyboard = [
        [InlineKeyboardButton("🌾 Фармить звёзды", callback_data=f"farm_{user.id}")],
        [InlineKeyboardButton("🔄 Обновить", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="toplist")]
    ]
    
    if stars >= upgrade_cost:
        keyboard.insert(1, [InlineKeyboardButton(f"⚡️ Улучшить множитель ({upgrade_cost} звёзд)", callback_data=f"upgrade_{user.id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🌟 Профиль {user.first_name}\n\n"
        f"✨ Звёзды: {stars}\n"
        f"⚡️ Множитель: x{multiplier}\n"
        f"📊 Уровень: {level}\n"
        f"💎 Следующее улучшение: {upgrade_cost} звёзд\n"
        f"⏰ {farm_status}",
        reply_markup=reply_markup
    )

# Обработчик команды /balance
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        await update.message.reply_text("Эта команда работает только в групповых чатах!")
        return
    
    user_data = get_user(user.id, chat.id, user.username, user.first_name)
    stars = user_data[4]
    
    await update.message.reply_text(f"💰 Ваш баланс: {stars} звёзд")

# Обработчик команды /toplist
async def toplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        await update.message.reply_text("Эта команда работает только в групповых чатах!")
        return
    
    conn = sqlite3.connect('stars_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT username, first_name, stars, level 
    FROM users 
    WHERE chat_id = ? 
    ORDER BY stars DESC 
    LIMIT 10
    ''', (chat.id,))
    
    top_users = cursor.fetchall()
    conn.close()
    
    if not top_users:
        await update.message.reply_text("В этом чате ещё нет игроков!")
        return
    
    top_text = "🏆 Топ игроков:\n\n"
    for i, (username, first_name, stars, level) in enumerate(top_users, 1):
        display_name = f"@{username}" if username else first_name
        top_text += f"{i}. {display_name} - {stars} звёзд (Ур. {level})\n"
    
    keyboard = [
        [InlineKeyboardButton("🌟 Мой профиль", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🌾 Фармить звёзды", callback_data=f"farm_{user.id}")],
        [InlineKeyboardButton("🔄 Обновить топ", callback_data="toplist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(top_text, reply_markup=reply_markup)

# Обработчик подтверждения сброса
async def handle_confirm_reset(query, user, chat, context):
    # Получаем ID чата из callback_data
    chat_id = int(query.data.split('_')[-1])
    
    # Проверяем права администратора
    if not await is_admin(context, user.id, chat_id):
        await query.answer("❌ Только администраторы могут сбрасывать статистику!", show_alert=True)
        return
    
    # Сбрасываем статистику
    reset_all_stats(chat_id)
    
    await query.edit_message_text(
        "♻️ Статистика полностью сброшена!\n\n"
        "Все данные обнулены. Игроки могут начинать с чистого листа!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 В главное меню", callback_data=f"profile_{user.id}")]
        ])
    )
    # Обработчик отмены сброса
async def handle_cancel_reset(query):
    await query.edit_message_text(
        "✅ Сброс статистики отменен.\n"
        "Все данные сохранены.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 В главное меню", callback_data=f"profile_{query.from_user.id}")]
        ])
    )

# Обработчик админского сброса через кнопку
async def handle_admin_reset(query, context):
    user = query.from_user
    chat = query.message.chat
    
    # Проверяем права администратора
    if not await is_admin(context, user.id, chat.id):
        await query.answer("❌ Только администраторы могут сбрасывать статистику!", show_alert=True)
        return
    
    # Создаем клавиатуру с подтверждением
    keyboard = [
        [InlineKeyboardButton("✅ Да, сбросить всё", callback_data=f"confirm_reset_{chat.id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_reset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(
        "⚠️ ВНИМАНИЕ! Вы уверены что хотите сбросить ВСЮ статистику?\n\n"
        "Это действие:\n"
        "• Обнулит все звёзды у всех игроков\n"
        "• Сбросит все уровни и множители\n"
        "• Удалит всю историю в этом чате\n\n"
        "Действие необратимо!",
        reply_markup=reply_markup
    )

# Обработчик callback запросов
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    chat = query.message.chat
    
    # Проверяем, кому принадлежит callback_data
    callback_data = query.data
    
    # Обработка общих команд (доступны всем)
    if callback_data == "toplist":
        await handle_toplist(query, user, chat)
        return
    elif callback_data == "admin_reset":
        await handle_admin_reset(query, context)
        return
    elif callback_data.startswith("confirm_reset_"):
        await handle_confirm_reset(query, user, chat, context)
        return
    elif callback_data == "cancel_reset":
        await handle_cancel_reset(query)
        return
    
    # Проверяем ID пользователя в callback_data
    if not callback_data.endswith(f"_{user.id}"):
        await query.answer("❌ Это не ваше меню!", show_alert=True)
        return
    
    # Обработка персональных команд
    if callback_data.startswith("profile_"):
        await handle_profile(query, user, chat)
    elif callback_data.startswith("farm_"):
        await handle_farm(query, user, chat)
    elif callback_data.startswith("upgrade_"):
        await handle_upgrade(query, user, chat)

# Обработчик топа (доступен всем)
async def handle_toplist(query, user, chat):
    conn = sqlite3.connect('stars_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT username, first_name, stars, level 
    FROM users 
    WHERE chat_id = ? 
    ORDER BY stars DESC 
    LIMIT 10
    ''', (chat.id,))
    
    top_users = cursor.fetchall()
    conn.close()
    
    top_text = "🏆 Топ игроков:\n\n"
    for i, (username, first_name, stars, level) in enumerate(top_users, 1):
        display_name = f"@{username}" if username else first_name
        top_text += f"{i}. {display_name} - {stars} звёзд (Ур. {level})\n"
    
    keyboard = [
        [InlineKeyboardButton("🌟 Мой профиль", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🌾 Фармить звёзды", callback_data=f"farm_{user.id}")],
        [InlineKeyboardButton("🔄 Обновить топ", callback_data="toplist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(top_text, reply_markup=reply_markup)

# Обработчик профиля
async def handle_profile(query, user, chat):
    user_data = get_user(user.id, chat.id, user.username, user.first_name)
    stars = user_data[4]
    multiplier = user_data[5]
    level = user_data[6]
    last_farm_time = user_data[7]
    upgrade_cost = get_upgrade_cost(level)
    
    # Проверяем время до следующего фарма
    if can_farm(last_farm_time):
        farm_status = "✅ Готов к фарму!"
    else:
        remaining = get_remaining_time(last_farm_time)
        farm_status = f"⏰ До фарма: {remaining}"
    
    keyboard = [
        [InlineKeyboardButton("🌾 Фармить звёзды", callback_data=f"farm_{user.id}")],
        [InlineKeyboardButton("🔄 Обновить", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="toplist")]
    ]
    
    if stars >= upgrade_cost:
        keyboard.insert(1, [InlineKeyboardButton(f"⚡️ Улучшить множитель ({upgrade_cost} звёзд)", callback_data=f"upgrade_{user.id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🌟 Профиль {user.first_name}\n\n"
        f"✨ Звёзды: {stars}\n"
        f"⚡️ Множитель: x{multiplier}\n"
        f"📊 Уровень: {level}\n"
        f"💎 Следующее улучшение: {upgrade_cost} звёзд\n"
        f"⏰ {farm_status}",
        reply_markup=reply_markup
    )

# Обработчик фарма
async def handle_farm(query, user, chat):
    user_data = get_user(user.id, chat.id, user.username, user.first_name)
    last_farm_time = user_data[7]
    
    if not can_farm(last_farm_time):
        remaining = get_remaining_time(last_farm_time)
        await query.answer(f"Подождите ещё {remaining}!", show_alert=True)
        return
    
    # Генерируем звёзды (1-2)
    base_stars = random.randint(MIN_STARS, MAX_STARS)
    multiplier = user_data[5]
    actual_stars = int(base_stars * multiplier)
    new_stars = user_data[4] + actual_stars
    current_time = time.time()
    
    # Обновляем данные пользователя
    update_user(user.id, chat.id, stars=new_stars, last_farm_time=current_time)
    
    # Формируем сообщение
    message = (
        f"🌟 {user.first_name} получил {actual_stars} звёзд!\n"
        f"📊 База: {base_stars} | Множитель: x{multiplier}\n"
        f"💰 Теперь у вас: {new_stars} звёзд"
    )
    
    keyboard = [
        [InlineKeyboardButton("🌟 Профиль", callback_data=f"profile_{user.id}")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="toplist")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup)

# Обработчик улучшения
async def handle_upgrade(query, user, chat):
    user_data = get_user(user.id, chat.id, user.username, user.first_name)
    stars = user_data[4]
    level = user_data[6]
    upgrade_cost = get_upgrade_cost(level)
    
    if stars >= upgrade_cost:
        new_stars = stars - upgrade_cost
        new_level = level + 1
        new_multiplier = round(1.0 + (new_level - 1) * 0.1, 1)
        
        update_user(user.id, chat.id, stars=new_stars, level=new_level, multiplier=new_multiplier)
        
        await query.edit_message_text(
            f"🎉 Поздравляем! Вы улучшили множитель до x{new_multiplier}!\n"
            f"💎 Потрачено: {upgrade_cost} звёзд\n"
            f"✨ Осталось: {new_stars} звёзд\n\n"
            f"Нажмите на кнопку ниже, чтобы вернуться в профиль",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌟 Вернуться в профиль", callback_data=f"profile_{user.id}")]
            ])
        )
    else:
        await query.answer("Недостаточно звёзд для улучшения!", show_alert=True)

def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("farm", farm))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("toplist", toplist))
    application.add_handler(CommandHandler("reset_stats", reset_stats))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()