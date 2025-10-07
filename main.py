import telebot
import random

TOKEN = '8262738665:AAEyqjuQQnTxr4cyKff1SxgRaDUlCqjKbPI'  # вставь сюда свой токен
bot = telebot.TeleBot(TOKEN)

games = {}

def draw_board():
    top = "🏁 Верхнее поле:\n" + " | ".join([f"{i:2}" for i in range(13, 25)]) + "\n"
    bottom = "\n🏁 Нижнее поле:\n" + " | ".join([f"{i:2}" for i in range(12, 0, -1)]) + "\n"
    return top + bottom

def roll_dice():
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    return d1, d2

@bot.message_handler(commands=['start'])
def start_game(message):
    chat_id = message.chat.id
    if chat_id not in games:
        games[chat_id] = {'players': [], 'turn': 0}
    if message.from_user.username not in games[chat_id]['players']:
        games[chat_id]['players'].append(message.from_user.username)
    players = games[chat_id]['players']
    bot.send_message(chat_id, f"🎯 Добро пожаловать в нарды!\nИгроки: {', '.join(players)}")
    bot.send_message(chat_id, "Кидай кости — /roll")

@bot.message_handler(commands=['roll'])
def handle_roll(message):
    chat_id = message.chat.id
    if chat_id not in games or len(games[chat_id]['players']) == 0:
        bot.send_message(chat_id, "Сначала начни игру /start")
        return

    game = games[chat_id]
    current_player = game['players'][game['turn'] % len(game['players'])]
    if message.from_user.username != current_player:
        bot.send_message(chat_id, f"⏳ Сейчас ход {current_player}")
        return

    d1, d2 = roll_dice()
    board = draw_board()
    bot.send_message(chat_id, f"🎲 {current_player} выкинул: {d1} и {d2}\n\n{board}")

    game['turn'] += 1

@bot.message_handler(commands=['reset'])
def reset_game(message):
    chat_id = message.chat.id
    if chat_id in games:
        del games[chat_id]
        bot.send_message(chat_id, "♻️ Игра сброшена. Начни заново командой /start.")
    else:
        bot.send_message(chat_id, "Нет активной игры.")

bot.polling(non_stop=True)
