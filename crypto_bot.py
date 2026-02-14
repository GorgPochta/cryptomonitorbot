import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import requests
import json
import time
import threading
from datetime import datetime
import os

# ===== НАСТРОЙКИ =====
BOT_TOKEN = "6566243038:AAE6iVBUqPyF5P3924dMrDp8cRcwwcUivZs"  # Твой токен
# =====================

# Состояния для разговора
SYMBOL1, SYMBOL2, THRESHOLD, INTERVAL, RECEIVER_TYPE, RECEIVER_ID = range(6)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Хранилище данных
user_data = {}
active_monitors = {}

# ===== ФУНКЦИЯ СБРОСА НАКОПЛЕННЫХ СООБЩЕНИЙ =====
async def clear_pending_updates(application):
    """Сбрасывает все накопленные сообщения при запуске"""
    try:
        # Получаем все ожидающие обновления и сразу их подтверждаем
        updates = await application.bot.get_updates()
        if updates:
            # Берем самый большой update_id и добавляем 1
            max_update_id = max(update.update_id for update in updates)
            await application.bot.get_updates(offset=max_update_id + 1)
            print(f"✅ Сброшено {len(updates)} накопленных сообщений")
        else:
            print("✅ Нет накопленных сообщений")
    except Exception as e:
        print(f"❌ Ошибка при сбросе сообщений: {e}")

# ===== КЛАСС МОНИТОРИНГА =====
class PriceMonitor:
    def __init__(self, owner_id, receiver_id, symbol1, symbol2, threshold, interval, bot_app):
        self.owner_id = owner_id
        self.receiver_id = receiver_id
        self.symbol1 = symbol1.lower()
        self.symbol2 = symbol2.lower()
        self.threshold = threshold
        self.interval = interval
        self.bot_app = bot_app
        self.active = True
        
    def fetch_price(self, symbol):
        try:
            response = requests.get(
                f'https://api.bybit.com/v5/market/tickers',
                params={'category': 'linear', 'symbol': symbol.upper()},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if data['retCode'] == 0 and data['result']['list']:
                    return float(data['result']['list'][0]['lastPrice'])
        except:
            pass
        return None
    
    async def send_message(self, text):
        try:
            await self.bot_app.bot.send_message(
                chat_id=self.receiver_id,
                text=text,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Ошибка отправки: {e}")
    
    async def check_ratio(self):
        if not self.active:
            return
            
        price1 = self.fetch_price(self.symbol1)
        price2 = self.fetch_price(self.symbol2)
        
        if price1 and price2:
            ratio = price1 / price2
            current_time = datetime.now().strftime('%H:%M:%S')
            
            if ratio >= self.threshold:
                signal_msg = (
                    f"🚨 <b>СИГНАЛ!</b>\n\n"
                    f"<b>Пара:</b> {self.symbol1.upper()}/{self.symbol2.upper()}\n"
                    f"<b>Отношение:</b> {ratio:.6f}\n"
                    f"<b>Порог:</b> {self.threshold}\n"
                    f"<b>Время:</b> {current_time}"
                )
                await self.send_message(signal_msg)
        
        if self.active:
            threading.Timer(self.interval, lambda: asyncio.run_coroutine_threadsafe(
                self.check_ratio(), self.bot_app.loop
            )).start()
    
    def start(self):
        self.active = True
        threading.Timer(self.interval, lambda: asyncio.run_coroutine_threadsafe(
            self.check_ratio(), self.bot_app.loop
        )).start()
    
    def stop(self):
        self.active = False

# ===== ОБРАБОТЧИКИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    print(f"✅ Получена команда /start от {user.first_name} (ID: {chat_id})")
    
    # Клавиатура
    keyboard = [
        [InlineKeyboardButton("📊 Добавить пару", callback_data='add_pair')],
        [InlineKeyboardButton("📋 Мои пары", callback_data='list_pairs')],
        [InlineKeyboardButton("⏹ Остановить все", callback_data='stop_all')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я бот для мониторинга криптопар на Bybit.\n"
        f"Твой Chat ID: <code>{chat_id}</code>",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    print(f"🔘 Нажата кнопка: {query.data} от пользователя {chat_id}")
    
    if query.data == 'add_pair':
        await query.edit_message_text(
            "📝 <b>Шаг 1/4</b>\n\nВведи первый тикер (например: <code>paxgusdt</code>):",
            parse_mode='HTML'
        )
        return SYMBOL1
    
    elif query.data == 'list_pairs':
        await query.edit_message_text("📋 Список пар появится позже")
    
    elif query.data == 'stop_all':
        await query.edit_message_text("⏹ Все мониторы остановлены")
    
    elif query.data == 'help':
        help_text = (
            "ℹ️ <b>Как пользоваться:</b>\n\n"
            "1. Нажми 'Добавить пару'\n"
            "2. Введи первый тикер\n"
            "3. Введи второй тикер\n"
            "4. Введи порог\n"
            "5. Введи интервал\n"
            "6. Выбери получателя"
        )
        await query.edit_message_text(help_text, parse_mode='HTML')
    
    elif query.data == 'back_to_menu':
        keyboard = [
            [InlineKeyboardButton("📊 Добавить пару", callback_data='add_pair')],
            [InlineKeyboardButton("📋 Мои пары", callback_data='list_pairs')],
            [InlineKeyboardButton("⏹ Остановить все", callback_data='stop_all')],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("👋 Главное меню:", reply_markup=reply_markup)

async def symbol1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['symbol1'] = update.message.text.strip().lower()
    await update.message.reply_text(
        "✅ Шаг 2/4\n\nВведи второй тикер (например: <code>xautusdt</code>):",
        parse_mode='HTML'
    )
    return SYMBOL2

async def symbol2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['symbol2'] = update.message.text.strip().lower()
    await update.message.reply_text(
        "✅ Шаг 3/4\n\nВведи пороговое отношение (например: <code>1.0048</code>):",
        parse_mode='HTML'
    )
    return THRESHOLD

async def threshold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        threshold = float(update.message.text.strip())
        context.user_data['threshold'] = threshold
        await update.message.reply_text(
            "✅ Шаг 4/4\n\nВведи интервал в секундах (например: <code>60</code>):",
            parse_mode='HTML'
        )
        return INTERVAL
    except:
        await update.message.reply_text("❌ Введи число (например 1.0048)")
        return THRESHOLD

async def interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        interval = int(update.message.text.strip())
        context.user_data['interval'] = interval
        
        # Кнопки выбора получателя
        keyboard = [
            [InlineKeyboardButton("👤 Себе", callback_data='receiver_self')],
            [InlineKeyboardButton("📱 Другой", callback_data='receiver_other')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📨 Куда отправлять уведомления?",
            reply_markup=reply_markup
        )
        return RECEIVER_TYPE
    except:
        await update.message.reply_text("❌ Введи целое число")
        return INTERVAL

async def receiver_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    
    if query.data == 'receiver_self':
        context.user_data['receiver_id'] = chat_id
        await finalize_monitor(update, context)
        return ConversationHandler.END
    else:
        await query.edit_message_text(
            "📝 Введи Chat ID получателя (число):"
        )
        return RECEIVER_ID

async def receiver_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        receiver_id = int(update.message.text.strip())
        context.user_data['receiver_id'] = receiver_id
        await finalize_monitor(update, context)
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ Введи число (Chat ID)")
        return RECEIVER_ID

async def finalize_monitor(update, context):
    chat_id = update.effective_chat.id
    symbol1 = context.user_data['symbol1']
    symbol2 = context.user_data['symbol2']
    threshold = context.user_data['threshold']
    interval = context.user_data['interval']
    receiver_id = context.user_data['receiver_id']
    
    # Запускаем монитор
    monitor = PriceMonitor(chat_id, receiver_id, symbol1, symbol2, threshold, interval, context.application)
    active_monitors[chat_id] = monitor
    monitor.start()
    
    await update.message.reply_text(
        f"✅ <b>Мониторинг запущен!</b>\n\n"
        f"📊 {symbol1.upper()}/{symbol2.upper()}\n"
        f"🎯 Порог: {threshold}\n"
        f"⏱ Интервал: {interval}с\n"
        f"📨 Получатель: {receiver_id}",
        parse_mode='HTML'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END

async def post_init(application):
    """Выполняется после инициализации бота"""
    print("🔄 Сброс накопленных сообщений...")
    await clear_pending_updates(application)
    print("✅ Бот готов к работе!")

def main():
    """Запуск бота"""
    print("🚀 Запуск бота...")
    
    # Создаем приложение с post_init
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    
    # ConversationHandler для добавления пары
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^add_pair$')],
        states={
            SYMBOL1: [MessageHandler(filters.TEXT & ~filters.COMMAND, symbol1_handler)],
            SYMBOL2: [MessageHandler(filters.TEXT & ~filters.COMMAND, symbol2_handler)],
            THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, threshold_handler)],
            INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, interval_handler)],
            RECEIVER_TYPE: [CallbackQueryHandler(receiver_handler)],
            RECEIVER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receiver_id_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(conv_handler)
    
    # Обработчик остальных кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Бот запущен и ждет сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
