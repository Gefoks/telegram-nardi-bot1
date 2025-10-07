import telebot
import random
import os

# Берём токен из переменной окружения
TOKEN = "8262738665:AAEyqjuQQnTxr4cyKff1SxgRaDUlCqjKbPI"

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id,
                     "🎲 Добро пожаловать в Нарды!\n"
                     "Команда для броска кубиков: /roll")

@bot.message_handler(commands=['roll'])
def roll(message):
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    bot.send_message(message.chat.id, f"🎯 Кубики: [{dice1}] и [{dice2}]")
    if dice1 == dice2:
        bot.send_message(message.chat.id, "Дубль! Ходишь снова 🔁")

bot.polling()
