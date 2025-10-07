import os
import telebot
import random
from flask import Flask

# Токен от @BotFather
TOKEN = "8262738665:AAEyqjuQQnTxr4cyKff1SxgRaDUlCqjKbPI"

# Создаём объект бота
bot = telebot.TeleBot(TOKEN)

# Создаём приложение Flask (необходимо для Render)
app = Flask(__name__)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "🎲 Добро пожаловать в Нарды!\nКоманда для броска костей: /roll")

@bot.message_handler(commands=['roll'])
def roll(message):
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    bot.send_message(message.chat.id, f"🎯 Кубики: [{dice1}] и [{dice2}]")
    if dice1 == dice2:
        bot.send_message(message.chat.id, "Дубль! Ходишь снова 🔁")

# Роутинг для Flask (необязательный для бота, но нужен для Render)
@app.route('/')
def index():
    return 'Bot is running!'

# Привязка бота и Flask к порту
if __name__ == '__main__':
    # Render будет передавать порт через переменную окружения
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
