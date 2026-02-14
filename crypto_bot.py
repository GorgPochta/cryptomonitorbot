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

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Состояния для разговора
(SYMBOL1, SYMBOL2, THRESHOLD, INTERVAL, RECEIVER_TYPE, RECEIVER_ID) = range(6)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "6566243038:AAE6iVBUqPyF5P3924dMrDp8cRcwwcUivZs")

# Файл для хранения данных пользователей
USER_DATA_FILE = 'user_data.json'

# Активные мониторы
active_monitors = {}

def load_user_data():
    """Загружает данные пользователей"""
    try:
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user_data(data):
    """Сохраняет данные пользователей"""
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# Глобальные данные
user_data = load_user_data()

# ===== КЛАСС МОНИТОРИНГА =====
class PriceMonitor:
    def __init__(self, owner_id, receiver_id, symbol1, symbol2, threshold, interval, bot_app):
        self.owner_id = owner_id  # кто создал
        self.receiver_id = receiver_id  # кому отправлять
        self.symbol1 = symbol1.lower()
        self.symbol2 = symbol2.lower()
        self.threshold = threshold
        self.interval = interval
        self.bot_app = bot_app
        self.active = True
        self.last_notification = 0
        
    def fetch_price(self, symbol):
        """Получает цену с Bybit"""
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
        except Exception as e:
            print(f"Ошибка получения цены {symbol}: {e}")
        return None
    
    async def send_message(self, text):
        """Отправляет сообщение получателю"""
        try:
            await self.bot_app.bot.send_message(
                chat_id=self.receiver_id,
                text=text,
                parse_mode='HTML'
            )
            # Также отправляем копию создателю (для информации)
            if self.receiver_id != self.owner_id:
                await self.bot_app.bot.send_message(
                    chat_id=self.owner_id,
                    text=f"📨 Уведомление отправлено получателю {self.receiver_id}\n\n{text}",
                    parse_mode='HTML'
                )
        except Exception as e:
            # Если не удалось отправить получателю - шлём создателю
            await self.bot_app.bot.send_message(
                chat_id=self.owner_id,
                text=f"❌ Не удалось отправить уведомление получателю {self.receiver_id}. Ошибка: {e}\n\nСигнал: {text}",
                parse_mode='HTML'
            )
    
    async def check_ratio(self):
        """Проверяет отношение"""
        if not self.active:
            return
            
        price1 = self.fetch_price(self.symbol1)
        price2 = self.fetch_price(self.symbol2)
        
        if price1 and price2:
            ratio = price1 / price2
            current_time = datetime.now().strftime('%H:%M:%S')
            
            # Проверяем сигнал
            if ratio >= self.threshold:
                signal_msg = (
                    f"🚨 <b>СИГНАЛ!</b>\n\n"
                    f"<b>Пара:</b> {self.symbol1.upper()}/{self.symbol2.upper()}\n"
                    f"<b>Отношение:</b> {ratio:.6f}\n"
                    f"<b>Порог:</b> {self.threshold}\n"
                    f"<b>Время:</b> {current_time}\n"
                    f"<b>Мониторинг создан:</b> @{self.owner_id}"
                )
                await self.send_message(signal_msg)
                self.last_notification = time.time()
        
        # Запускаем следующую проверку
        if self.active:
            threading.Timer(self.interval, lambda: asyncio.run_coroutine_threadsafe(
                self.check_ratio(), self.bot_app.loop
            )).start()
    
    def start(self):
        """Запускает мониторинг"""
        self.active = True
        threading.Timer(self.interval, lambda: asyncio.run_coroutine_threadsafe(
            self.check_ratio(), self.bot_app.loop
        )).start()
    
    def stop(self):
        """Останавливает мониторинг"""
        self.active = False

# ===== ОБРАБОТЧИКИ КОМАНД =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # Инициализируем пользователя
    if str(chat_id) not in user_data:
        user_data[str(chat_id)] = {
            'username': user.username,
            'first_name': user.first_name,
            'monitors': []
        }
        save_user_data(user_data)
    
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
        f"Ты можешь настроить отслеживание отношения двух активов.\n"
        f"Уведомления можно отправлять себе или другому пользователю.\n\n"
        f"Твой Chat ID: <code>{chat_id}</code>",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок главного меню"""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    print(f"🔍 Нажата кнопка в меню: {query.data}")  # Для отладки
    
    if query.data == 'add_pair':
        # Начинаем добавление новой пары
        await query.edit_message_text(
            "📝 <b>Добавление новой пары - шаг 1/4</b>\n\n"
            "Введи <b>первый тикер</b> (числитель):\n"
            "Например: <code>paxgusdt</code>",
            parse_mode='HTML'
        )
        return SYMBOL1  # Возвращаем следующее состояние
    
    elif query.data == 'list_pairs':
        # Показываем список пар
        if str(chat_id) in user_data and user_data[str(chat_id)]['monitors']:
            text = "📋 <b>Твои пары:</b>\n\n"
            for i, mon in enumerate(user_data[str(chat_id)]['monitors'], 1):
                text += f"{i}. {mon['symbol1'].upper()}/{mon['symbol2'].upper()}\n"
                text += f"   Порог: {mon['threshold']}, интервал: {mon['interval']}с\n"
                if 'receiver_id' in mon:
                    text += f"   Получатель: <code>{mon['receiver_id']}</code>\n\n"
            
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(
                "📭 У тебя пока нет сохраненных пар.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')
                ]])
            )
    
    elif query.data == 'stop_all':
        # Останавливаем все мониторы
        if chat_id in active_monitors:
            active_monitors[chat_id].stop()
            del active_monitors[chat_id]
            await query.edit_message_text(
                "⏹ Все мониторы остановлены.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ В меню", callback_data='back_to_menu')
                ]])
            )
        else:
            await query.edit_message_text(
                "ℹ️ Нет активных мониторов.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ В меню", callback_data='back_to_menu')
                ]])
            )
    
    elif query.data == 'help':
        # Показываем помощь
        help_text = (
            "ℹ️ <b>Как пользоваться:</b>\n\n"
            "1. Нажми 'Добавить пару'\n"
            "2. Введи первый тикер (например paxgusdt)\n"
            "3. Введи второй тикер (например xautusdt)\n"
            "4. Введи пороговое отношение (например 1.0048)\n"
            "5. Введи интервал проверки в секундах\n"
            "6. Выбери, куда отправлять уведомления:\n"
            "   • Себе\n"
            "   • Другой пользователь (введи Chat ID)\n\n"
            "Бот будет проверять каждые N секунд и пришлет сигнал указанному получателю."
        )
        await query.edit_message_text(
            help_text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В меню", callback_data='back_to_menu')
            ]])
        )
    
    elif query.data == 'back_to_menu':
        # Возвращаемся в главное меню
        keyboard = [
            [InlineKeyboardButton("📊 Добавить пару", callback_data='add_pair')],
            [InlineKeyboardButton("📋 Мои пары", callback_data='list_pairs')],
            [InlineKeyboardButton("⏹ Остановить все", callback_data='stop_all')],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "👋 Главное меню:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

async def symbol1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем первый тикер"""
    context.user_data['symbol1'] = update.message.text.strip().lower()
    await update.message.reply_text(
        "✅ Шаг 1/5 - первый тикер принят!\n\n"
        "Теперь введи <b>второй тикер</b> (знаменатель):\n"
        "Например: <code>xautusdt</code>",
        parse_mode='HTML'
    )
    return SYMBOL2

async def symbol2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем второй тикер"""
    context.user_data['symbol2'] = update.message.text.strip().lower()
    await update.message.reply_text(
        "✅ Шаг 2/5 - второй тикер принят!\n\n"
        "Теперь введи <b>пороговое отношение</b>:\n"
        "Например: <code>1.0048</code>",
        parse_mode='HTML'
    )
    return THRESHOLD

async def threshold_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем порог"""
    try:
        threshold = float(update.message.text.strip())
        context.user_data['threshold'] = threshold
        await update.message.reply_text(
            "✅ Шаг 3/5 - порог принят!\n\n"
            "Теперь введи <b>интервал проверки</b> в секундах:\n"
            "Например: <code>60</code>",
            parse_mode='HTML'
        )
        return INTERVAL
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введи число (например 1.0048)"
        )
        return THRESHOLD

async def interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем интервал"""
    try:
        interval = int(update.message.text.strip())
        context.user_data['interval'] = interval
        
        # Спрашиваем, куда отправлять уведомления (ТОЛЬКО СЕБЕ ИЛИ ДРУГОЙ)
        keyboard = [
            [InlineKeyboardButton("👤 Себе", callback_data='receiver_self')],
            [InlineKeyboardButton("📱 Другой пользователь", callback_data='receiver_other')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "✅ Шаг 4/4 - интервал принят!\n\n"
            "📨 <b>Куда отправлять уведомления?</b>\n"
            "Выбери вариант:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return RECEIVER_TYPE
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введи целое число (например 60)"
        )
        return INTERVAL

async def receiver_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор получателя"""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    
    if query.data == 'receiver_self':
        # Отправляем себе
        context.user_data['receiver_id'] = chat_id
        await query.message.reply_text("✅ Получатель: себе\n\n⏳ Запускаю мониторинг...")
        await finalize_monitor(update, context)
        return ConversationHandler.END
    
    elif query.data == 'receiver_other':
        context.user_data['receiver_type'] = query.data
        await query.message.reply_text(
            "📝 Введи <b>Chat ID</b> получателя:\n\n"
            "• Найди Chat ID через @userinfobot\n"
            "• Пример: <code>123456789</code>",
            parse_mode='HTML'
        )
        return RECEIVER_ID

async def receiver_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем Chat ID получателя"""
    try:
        receiver_id = int(update.message.text.strip())
        context.user_data['receiver_id'] = receiver_id
        await finalize_monitor(update, context)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Chat ID должен быть числом.\n"
            "Пример: <code>123456789</code>",
            parse_mode='HTML'
        )
        return RECEIVER_ID

async def finalize_monitor(update, context):
    """Завершает настройку и запускает монитор"""
    chat_id = update.effective_chat.id
    symbol1 = context.user_data['symbol1']
    symbol2 = context.user_data['symbol2']
    threshold = context.user_data['threshold']
    interval = context.user_data['interval']
    receiver_id = context.user_data.get('receiver_id', chat_id)
    
    # Сохраняем в данные пользователя
    monitor_config = {
        'symbol1': symbol1,
        'symbol2': symbol2,
        'threshold': threshold,
        'interval': interval,
        'receiver_id': receiver_id,
        'created': datetime.now().isoformat()
    }
    
    if str(chat_id) not in user_data:
        user_data[str(chat_id)] = {'monitors': []}
    
    user_data[str(chat_id)]['monitors'].append(monitor_config)
    save_user_data(user_data)
    
    # Запускаем монитор
    if chat_id in active_monitors:
        active_monitors[chat_id].stop()
    
    monitor = PriceMonitor(chat_id, receiver_id, symbol1, symbol2, threshold, interval, context.application)
    active_monitors[chat_id] = monitor
    monitor.start()
    
    # Сообщение о запуске
    receiver_text = f"<code>{receiver_id}</code>" if receiver_id != chat_id else "👤 Себе"
    
    await update.message.reply_text(
        f"✅ <b>Мониторинг запущен!</b>\n\n"
        f"📊 {symbol1.upper()}/{symbol2.upper()}\n"
        f"🎯 Порог: {threshold}\n"
        f"⏱ Интервал: {interval}с\n"
        f"📨 Получатель: {receiver_text}\n\n"
        f"При достижении порога уведомление придет указанному получателю.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ В меню", callback_data='back_to_menu')
        ]])
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
    await update.message.reply_text(
        "❌ Добавление отменено.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ В меню", callback_data='back_to_menu')
        ]])
    )
    return ConversationHandler.END

def main():
    """Запуск бота"""
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    
    # Обработчик кнопок (кроме add_pair)
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^(?!add_pair$).*'))
    
    # ConversationHandler для добавления пары
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^add_pair$')],
        states={
            SYMBOL1: [MessageHandler(filters.TEXT & ~filters.COMMAND, symbol1_handler)],
            SYMBOL2: [MessageHandler(filters.TEXT & ~filters.COMMAND, symbol2_handler)],
            THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, threshold_handler)],
            INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, interval_handler)],
            RECEIVER_TYPE: [CallbackQueryHandler(receiver_type_handler)],
            RECEIVER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receiver_id_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(conv_handler)
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
