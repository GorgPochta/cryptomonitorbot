import logging
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
import asyncio

# ===== НАСТРОЙКИ =====
BOT_TOKEN = "6566243038:AAE6iVBUqPyF5P3924dMrDp8cRcwwcUivZs"  # Твой токен
# =====================

# Состояния для разговора
SYMBOL1, SYMBOL2, THRESHOLD, INTERVAL = range(4)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Хранилище данных (простое, без лишнего)
active_monitors = {}

# ===== ФУНКЦИЯ СБРОСА НАКОПЛЕННЫХ СООБЩЕНИЙ =====
async def clear_pending_updates(application):
    """Сбрасывает все накопленные сообщения при запуске"""
    try:
        updates = await application.bot.get_updates()
        if updates:
            max_update_id = max(update.update_id for update in updates)
            await application.bot.get_updates(offset=max_update_id + 1)
            print(f"✅ Сброшено {len(updates)} накопленных сообщений")
        else:
            print("✅ Нет накопленных сообщений")
    except Exception as e:
        print(f"❌ Ошибка при сбросе сообщений: {e}")

# ===== КЛАСС МОНИТОРИНГА =====
class PriceMonitor:
    def __init__(self, owner_id, symbol1, symbol2, threshold, interval, bot_app):
        self.owner_id = owner_id  # Кому отправлять (всегда владельцу)
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
    
    async def send_signal(self, text):
        """Отправляет сигнал владельцу"""
        try:
            await self.bot_app.bot.send_message(
                chat_id=self.owner_id,
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
                await self.send_signal(signal_msg)
        
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
    
    # Простое меню
    keyboard = [
        [InlineKeyboardButton("📊 Добавить пару", callback_data='add_pair')],
        [InlineKeyboardButton("📋 Мои пары", callback_data='list_pairs')],
        [InlineKeyboardButton("⏹ Остановить все", callback_data='stop_all')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"🔐 Все уведомления будут приходить сюда, в этот чат.\n\n"
        f"Твой Chat ID: <code>{chat_id}</code>",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    print(f"🔘 Нажата кнопка: {query.data} от {chat_id}")
    
    if query.data == 'add_pair':
        await query.edit_message_text(
            "📝 <b>Добавление пары</b>\n\n"
            "Введи <b>первый тикер</b> (например: <code>paxgusdt</code>):",
            parse_mode='HTML'
        )
        return SYMBOL1
    
    elif query.data == 'list_pairs':
        await query.edit_message_text("📋 Список пар будет позже")
    
    elif query.data == 'stop_all':
        if chat_id in active_monitors:
            active_monitors[chat_id].stop()
            del active_monitors[chat_id]
            await query.edit_message_text("⏹ Все мониторы остановлены")
        else:
            await query.edit_message_text("ℹ️ Нет активных мониторов")
    
    elif query.data == 'help':
        help_text = (
            "ℹ️ <b>Как пользоваться:</b>\n\n"
            "1. Нажми 'Добавить пару'\n"
            "2. Введи первый тикер (например: paxgusdt)\n"
            "3. Введи второй тикер (например: xautusdt)\n"
            "4. Введи пороговое отношение (например: 1.0048)\n"
            "5. Введи интервал проверки (например: 60 секунд)\n\n"
            "Бот будет проверять каждые N секунд и пришлет сигнал сюда."
        )
        await query.edit_message_text(help_text, parse_mode='HTML')

async def symbol1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['symbol1'] = update.message.text.strip().lower()
    await update.message.reply_text(
        "✅ Теперь введи <b>второй тикер</b> (например: <code>xautusdt</code>):",
        parse_mode='HTML'
    )
    return SYMBOL2

async def symbol2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['symbol2'] = update.message.text.strip().lower()
    await update.message.reply_text(
        "✅ Теперь введи <b>пороговое отношение</b> (например: <code>1.0048</code>):",
        parse_mode='HTML'
    )
    return THRESHOLD

async def threshold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        threshold = float(update.message.text.strip())
        context.user_data['threshold'] = threshold
        await update.message.reply_text(
            "✅ Теперь введи <b>интервал проверки</b> в секундах (например: <code>60</code>):",
            parse_mode='HTML'
        )
        return INTERVAL
    except:
        await update.message.reply_text("❌ Введи число (например 1.0048)")
        return THRESHOLD

async def interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        interval = int(update.message.text.strip())
        chat_id = update.effective_chat.id
        symbol1 = context.user_data['symbol1']
        symbol2 = context.user_data['symbol2']
        threshold = context.user_data['threshold']
        
        # Запускаем монитор (всегда на этого же пользователя)
        monitor = PriceMonitor(chat_id, symbol1, symbol2, threshold, interval, context.application)
        active_monitors[chat_id] = monitor
        monitor.start()
        
        await update.message.reply_text(
            f"✅ <b>Мониторинг запущен!</b>\n\n"
            f"📊 {symbol1.upper()}/{symbol2.upper()}\n"
            f"🎯 Порог: {threshold}\n"
            f"⏱ Интервал: {interval}с\n\n"
            f"🔔 Уведомления будут приходить в этот чат.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
        
    except:
        await update.message.reply_text("❌ Введи целое число (например 60)")
        return INTERVAL

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
    
    # ConversationHandler для добавления пары (без выбора получателя!)
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^add_pair$')],
        states={
            SYMBOL1: [MessageHandler(filters.TEXT & ~filters.COMMAND, symbol1_handler)],
            SYMBOL2: [MessageHandler(filters.TEXT & ~filters.COMMAND, symbol2_handler)],
            THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, threshold_handler)],
            INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, interval_handler)],
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
