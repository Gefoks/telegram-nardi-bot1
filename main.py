import telebot
import random

# Токен от @BotFather
TOKEN = "8262738665:AAEyqjuQQnTxr4cyKff1SxgRaDUlCqjKbPI"

# Создаём объект бота
bot = telebot.TeleBot(TOKEN)

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "🎲 Добро пожаловать в Нарды!\nКоманда для броска костей: /roll")

# Обработчик команды /roll
@bot.message_handler(commands=['roll'])
def roll(message):
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    bot.send_message(message.chat.id, f"🎯 Кубики: [{dice1}] и [{dice2}]")
    if dice1 == dice2:
        bot.send_message(message.chat.id, "Дубль! Ходишь снова 🔁")

# Запускаем бота
bot.polling()
