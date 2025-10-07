# main.py
# Полноценный Telegram-бот "Нарды" с изображением доски, интерактивом и честными кубиками (commit-reveal HMAC).
# Установи переменную окружения TOKEN (на Render: Environment -> Add) и запусти.

import os
import io
import json
import time
import hmac
import hashlib
import secrets
import sqlite3
import random
from typing import Optional, Tuple, List

from PIL import Image, ImageDraw, ImageFont
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile

TOKEN = "8262738665:AAEyqjuQQnTxr4cyKff1SxgRaDUlCqjKbPI"
if not TOKEN:
    raise SystemExit("Токен не указан.")

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise SystemExit("Установи переменную окружения TOKEN (BotFather token).")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ----------------- DB -----------------
DB = os.getenv("DB_PATH", "nardy.db")
conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS games(
 id TEXT PRIMARY KEY,
 chat_id INTEGER,
 player1 INTEGER,
 player2 INTEGER,
 state TEXT,
 server_seed_hash TEXT,
 server_seed_revealed TEXT,
 client_seed TEXT,
 nonce INTEGER,
 created INTEGER
)
""")
conn.commit()

# In-memory private seed store (small-scale). For prod use vault.
PRIVATE_SEEDS = {}

# ----------------- Game constants -----------------
POINTS = 24
START_PIECES = 15

# ----------------- RNG commit-reveal -----------------
def make_server_seed() -> str:
    return secrets.token_hex(32)

def hash_seed(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()

def hmac_roll(server_seed: str, client_seed: str, nonce: int) -> Tuple[int,int,str]:
    msg = f"{client_seed}:{nonce}".encode()
    mac = hmac.new(server_seed.encode(), msg, hashlib.sha256).hexdigest()
    num = int(mac, 16)
    die1 = (num % 6) + 1
    die2 = ((num >> 8) % 6) + 1
    return die1, die2, mac

# ----------------- Helpers DB -----------------
def save_game(rec: dict):
    cur.execute("""
      INSERT OR REPLACE INTO games (id, chat_id, player1, player2, state, server_seed_hash, server_seed_revealed, client_seed, nonce, created)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rec["id"],
        rec["chat_id"],
        rec.get("player1"),
        rec.get("player2"),
        json.dumps(rec["state"], ensure_ascii=False),
        rec.get("server_seed_hash"),
        rec.get("server_seed_revealed"),
        rec.get("client_seed"),
        rec.get("nonce", 0),
        rec.get("created", int(time.time()))
    ))
    conn.commit()

def load_game(gid: str) -> Optional[dict]:
    cur.execute("SELECT id, chat_id, player1, player2, state, server_seed_hash, server_seed_revealed, client_seed, nonce, created FROM games WHERE id=?", (gid,))
    r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "chat_id": r[1],
        "player1": r[2],
        "player2": r[3],
        "state": json.loads(r[4]),
        "server_seed_hash": r[5],
        "server_seed_revealed": r[6],
        "client_seed": r[7],
        "nonce": r[8],
        "created": r[9]
    }

# ----------------- Game setup -----------------
def new_game_record(chat_id: int, creator_id: int, opponent_id: Optional[int]=None) -> dict:
    gid = secrets.token_hex(8)
    # Russian nardy standard start: all 15 on point 1 for player1, 24 for player2
    points = [(0,0) for _ in range(POINTS)]
    points[0] = (1, START_PIECES)
    points[23] = (2, START_PIECES)
    state = {
        "points": points,     # list of tuples (owner, count)
        "off": {1:0, 2:0},
        "turn": 1,
        "dice": [],
        "dice_used": [],
        "phase": "waiting" if opponent_id is None else "playing",
        "last_move": None
    }
    server_seed = make_server_seed()
    rec = {
        "id": gid,
        "chat_id": chat_id,
        "player1": creator_id,
        "player2": opponent_id,
        "state": state,
        "server_seed_hash": hash_seed(server_seed),
        "server_seed_revealed": None,
        "client_seed": secrets.token_hex(8),
        "nonce": 0,
        "created": int(time.time())
    }
    PRIVATE_SEEDS[gid] = server_seed
    save_game(rec)
    return rec

def get_player_num(rec: dict, user_id: int) -> Optional[int]:
    if rec["player1"] == user_id:
        return 1
    if rec["player2"] == user_id:
        return 2
    return None

# ----------------- Game logic helpers -----------------
def can_bear_off(points, player) -> bool:
    if player == 1:
        home = range(0,6)
    else:
        home = range(18,24)
    total = 0
    for i,(owner,cnt) in enumerate(points):
        if owner == player:
            total += cnt
            if i not in home:
                return False
    return total == START_PIECES

def index_distance(player: int, src: int, dst: int) -> int:
    # returns positive distance if forward
    if player == 1:
        return dst - src
    else:
        return src - dst

def make_move(state: dict, player: int, src: int, dst: Optional[int], die: int) -> Tuple[bool,str]:
    points = state["points"]
    owner_src, cnt_src = points[src]
    if owner_src != player or cnt_src <= 0:
        return False, "Источник не содержит твою шашку."
    # bear off
    if dst is None:
        if not can_bear_off(points, player):
            return False, "Нельзя выносить: не все шашки в доме."
        if player == 1:
            distance = src + 1
        else:
            distance = 24 - src
        if die < distance:
            # standard rule: можно вынести с более дальних точек только если нет шашек ближе; simplify: allow only if die >= distance
            return False, "Кубик меньше, чем нужно для выноса с этой точки."
        # perform off
        # decrement
        if cnt_src-1 > 0:
            points[src] = (owner_src, cnt_src-1)
        else:
            points[src] = (0,0)
        state["off"][player] += 1
        state["dice_used"].append(die)
        state["last_move"] = f"Игрок {player} вынес шашку с {src+1} (кубик {die})"
        if state["off"][player] >= START_PIECES:
            state["phase"] = "ended"
        return True, "Шашка вынесена."
    # normal move
    dist = index_distance(player, src, dst)
    if dist <= 0:
        return False, "Ход в неверном направлении."
    if dist != die:
        return False, "Дистанция не соответствует выбранному кубику."
    owner_dst, cnt_dst = points[dst]
    if owner_dst != 0 and owner_dst != player:
        return False, "Точка занята соперником."
    # move
    if cnt_src-1 > 0:
        points[src] = (owner_src, cnt_src-1)
    else:
        points[src] = (0,0)
    if owner_dst == 0:
        points[dst] = (player, 1)
    else:
        points[dst] = (player, cnt_dst+1)
    state["dice_used"].append(die)
    state["last_move"] = f"Игрок {player} переместил {src+1} → {dst+1} (кубик {die})"
    return True, "Ход применён."

def available_moves(state: dict, player: int) -> List[Tuple[int,Optional[int],int]]:
    pts = state["points"]
    dice_left = [d for d in state["dice"] if d not in state["dice_used"]]
    moves = []
    for i,(owner,cnt) in enumerate(pts):
        if owner != player or cnt <= 0:
            continue
        for die in dice_left:
            if player == 1:
                dst = i + die
                if dst < POINTS:
                    owner_dst,_ = pts[dst]
                    if owner_dst == 0 or owner_dst == player:
                        moves.append((i,dst,die))
                else:
                    if can_bear_off(pts, player):
                        moves.append((i,None,die))
            else:
                dst = i - die
                if dst >= 0:
                    owner_dst,_ = pts[dst]
                    if owner_dst == 0 or owner_dst == player:
                        moves.append((i,dst,die))
                else:
                    if can_bear_off(pts, player):
                        moves.append((i,None,die))
    return moves

# ----------------- Render board image -----------------
try:
    FONT = ImageFont.truetype("DejaVuSans.ttf", 14)
except:
    FONT = ImageFont.load_default()

def render_board(state: dict) -> io.BytesIO:
    W, H = 1000, 460
    im = Image.new("RGBA", (W,H), (245,247,250))
    draw = ImageDraw.Draw(im)
    left = 40
    tri_w = (W - left*2) // 12
    top_y = 20
    bot_y = 420
    # triangles
    for i in range(12):
        x0 = left + i*tri_w
        x1 = x0 + tri_w
        color = (230,230,230) if i%2==0 else (210,210,210)
        draw.polygon([(x0, top_y),(x1, top_y),(x0+tri_w/2, top_y+140)], fill=color)
        color2 = (210,210,210) if i%2==0 else (230,230,230)
        draw.polygon([(x0, bot_y),(x1, bot_y),(x0+tri_w/2, bot_y-140)], fill=color2)
    # points mapping
    def coord(idx):
        if idx < 12:
            x = left + idx*tri_w + tri_w//2
            y = top_y + 40
            up = True
        else:
            mirror = 23 - idx
            x = left + mirror*tri_w + tri_w//2
            y = bot_y - 40
            up = False
        return int(x), int(y), up
    # pieces
    for idx,(owner,cnt) in enumerate(state["points"]):
        if cnt <= 0: continue
        x,y,up = coord(idx)
        r = 18
        for s in range(min(cnt,6)):
            off = s*(r*1.05)
            cy = y + off if up else y - off
            color = (30,30,30) if owner==1 else (200,40,40)
            draw.ellipse((x-r, cy-r, x+r, cy+r), fill=color, outline=(0,0,0))
        if cnt > 6:
            cy = y + (5*(r*1.05)) if up else y - (5*(r*1.05))
            draw.rectangle((x+r-6, cy-r-6, x+r+30, cy+r+6), fill=(255,255,255))
            draw.text((x+r-2, cy-r), f"x{cnt}", font=FONT, fill=(0,0,0))
    # sidebar
    dx = W-220; dy = 30
    draw.rectangle((dx,dy,dx+200,dy+220), fill=(255,255,255), outline=(200,200,200))
    draw.text((dx+10,dy+8), f"Ход: Игрок {state['turn']}", font=FONT, fill=(0,0,0))
    draw.text((dx+10,dy+36), f"Кубики: {' '.join(map(str,state['dice'])) if state['dice'] else '—'}", font=FONT, fill=(0,0,0))
    draw.text((dx+10,dy+64), f"Использованы: {' '.join(map(str,state['dice_used'])) if state['dice_used'] else '—'}", font=FONT, fill=(0,0,0))
    draw.text((dx+10,dy+92), f"Снятые: P1={state['off'][1]}  P2={state['off'][2]}", font=FONT, fill=(0,0,0))
    if state.get("last_move"):
        draw.text((dx+10,dy+124), f"Последний ход:", font=FONT, fill=(0,0,0))
        draw.text((dx+10,dy+144), f"{state['last_move']}", font=FONT, fill=(0,0,0))
    bio = io.BytesIO()
    im.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ----------------- Telegram handlers -----------------
from telebot import types

# /start: create or join minimal
@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    chat_id = m.chat.id
    # try find open game in this chat with waiting player
    cur.execute("SELECT id FROM games WHERE chat_id=? AND state LIKE ?", (chat_id, '%"phase": "waiting"%'))
    row = cur.fetchone()
    if row:
        gid = row[0]
        rec = load_game(gid)
        # if user is not player1 -> make him player2
        if rec["player2"] is None and rec["player1"] != m.from_user.id:
            rec["player2"] = m.from_user.id
            rec["state"]["phase"] = "playing"
            save_game(rec)
            bot.send_message(chat_id, f"Игрок присоединился. Игра {gid} начинается. ServerHash: {rec['server_seed_hash']}")
            send_board(chat_id, rec)
            return
    # else create new game
    rec = new_game_record(chat_id, m.from_user.id, None)
    save_game(rec)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Присоединиться", callback_data=f"join:{rec['id']}"))
    bot.send_photo(chat_id, photo=InputFile(render_board(rec["state"]), filename="board.png"),
                   caption=f"Создана партия {rec['id']}\nServerHash: {rec['server_seed_hash']}\nНажми: Присоединиться", reply_markup=kb)

@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("join:"))
def cb_join(cq: types.CallbackQuery):
    gid = cq.data.split(":")[1]
    rec = load_game(gid)
    if not rec:
        cq.answer("Игра не найдена", show_alert=True); return
    if rec["player2"] is not None:
        cq.answer("Уже есть второй игрок", show_alert=True); return
    if cq.from_user.id == rec["player1"]:
        cq.answer("Ты уже создатель игры", show_alert=True); return
    rec["player2"] = cq.from_user.id
    rec["state"]["phase"] = "playing"
    save_game(rec)
    PRIVATE_SEEDS.setdefault(gid, PRIVATE_SEEDS.get(gid, make_server_seed()))
    bot.answer_callback_query(cq.id, "Вы присоединились. Игра началась.")
    send_board(rec["chat_id"], rec)

def send_board(chat_id: int, rec: dict, caption: Optional[str]=None):
    bio = render_board(rec["state"])
    kb = InlineKeyboardMarkup()
    if rec["state"]["phase"] != "ended":
        kb.add(InlineKeyboardButton("Бросить кубики", callback_data=f"roll:{rec['id']}"))
        kb.add(InlineKeyboardButton("Сдаться", callback_data=f"resign:{rec['id']}"))
    bot.send_photo(chat_id, photo=InputFile(bio, filename="board.png"), caption=caption or f"Игра {rec['id']} — ход: Игрок {rec['state']['turn']}", reply_markup=kb)

@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("roll:"))
def cb_roll(cq: types.CallbackQuery):
    gid = cq.data.split(":")[1]
    rec = load_game(gid)
    if not rec:
        cq.answer("Игра не найдена", show_alert=True); return
    player_num = get_player_num(rec, cq.from_user.id)
    if player_num is None:
        cq.answer("Ты не участник игры", show_alert=True); return
    if rec["state"]["turn"] != player_num:
        cq.answer("Сейчас не твой ход", show_alert=True); return
    # perform commit-reveal roll
    server_seed = PRIVATE_SEEDS.get(gid)
    if not server_seed:
        server_seed = make_server_seed()
        PRIVATE_SEEDS[gid] = server_seed
    rec["nonce"] = (rec.get("nonce") or 0) + 1
    d1,d2,mac = hmac_roll(server_seed, rec["client_seed"], rec["nonce"])
    rec["state"]["dice"] = [d1,d2]
    rec["state"]["dice_used"] = []
    rec["server_seed_hash"] = hash_seed(server_seed)
    rec["server_seed_revealed"] = server_seed  # we reveal immediately for transparency
    save_game(rec)
    caption = f"Игрок {player_num} бросил: {d1} и {d2}\nNonce: {rec['nonce']}\nServerSeed(revealed): {rec['server_seed_revealed']}\nServerHash: {rec['server_seed_hash']}"
    send_board(rec["chat_id"], rec, caption=caption)
    cq.answer("Кубики брошены", show_alert=False)

@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("resign:"))
def cb_resign(cq: types.CallbackQuery):
    gid = cq.data.split(":")[1]
    rec = load_game(gid)
    if not rec:
        cq.answer("Игра не найдена", show_alert=True); return
    p = get_player_num(rec, cq.from_user.id)
    if p is None:
        cq.answer("Ты не участник", show_alert=True); return
    rec["state"]["phase"] = "ended"
    winner = 1 if p==2 else 2
    rec["state"]["last_move"] = f"Игрок {p} сдался. Победил игрок {winner}."
    save_game(rec)
    send_board(rec["chat_id"], rec, caption=rec["state"]["last_move"])
    cq.answer("Сдача зафиксирована", show_alert=False)

# Move flow: player clicks "Сделать ход" -> pick source -> pick target
@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("move_start:"))
def cb_move_start(cq: types.CallbackQuery):
    gid = cq.data.split(":")[1]
    rec = load_game(gid)
    if not rec:
        cq.answer("Игра не найдена", show_alert=True); return
    p = get_player_num(rec, cq.from_user.id)
    if p is None:
        cq.answer("Ты не участник", show_alert=True); return
    if rec["state"]["turn"] != p:
        cq.answer("Не твой ход", show_alert=True); return
    # list player's points
    kb = InlineKeyboardMarkup(row_width=6)
    for i,(owner,cnt) in enumerate(rec["state"]["points"]):
        if owner == p and cnt>0:
            kb.insert(InlineKeyboardButton(str(i+1), callback_data=f"select_from:{gid}:{i}"))
    kb.add(InlineKeyboardButton("Отмена", callback_data=f"cancel:{gid}"))
    bot.send_message(cq.message.chat.id, "Выбери откуда ходить (номер точки):", reply_markup=kb)
    cq.answer()

@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("select_from:"))
def cb_select_from(cq: types.CallbackQuery):
    _, gid, src_s = cq.data.split(":")
    src = int(src_s)
    rec = load_game(gid)
    if not rec:
        cq.answer("Игра не найдена", show_alert=True); return
    p = get_player_num(rec, cq.from_user.id)
    if p is None:
        cq.answer("Не участник", show_alert=True); return
    dice_left = [d for d in rec["state"]["dice"] if d not in rec["state"]["dice_used"]]
    if not dice_left:
        cq.answer("Кубики не брошены или уже использованы", show_alert=True); return
    options = []
    for die in dice_left:
        if p==1:
            dst = src + die
            if dst < POINTS:
                owner_dst,_ = rec["state"]["points"][dst]
                if owner_dst == 0 or owner_dst == p:
                    options.append((dst,die))
            else:
                if can_bear_off(rec["state"]["points"], p):
                    options.append((None,die))
        else:
            dst = src - die
            if dst >= 0:
                owner_dst,_ = rec["state"]["points"][dst]
                if owner_dst == 0 or owner_dst == p:
                    options.append((dst,die))
            else:
                if can_bear_off(rec["state"]["points"], p):
                    options.append((None,die))
    if not options:
        cq.answer("Нет доступных ходов из этой точки", show_alert=True); return
    kb = InlineKeyboardMarkup(row_width=3)
    for dst,die in options:
        label = f"→ {dst+1}" if dst is not None else "→ Вынос"
        kb.insert(InlineKeyboardButton(f"{label} ({die})", callback_data=f"do_move:{gid}:{src}:{dst if dst is not None else 'off'}:{die}"))
    kb.add(InlineKeyboardButton("Отмена", callback_data=f"cancel:{gid}"))
    bot.send_message(cq.message.chat.id, f"Доступные ходы из {src+1}:", reply_markup=kb)
    cq.answer()

@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("do_move:"))
def cb_do_move(cq: types.CallbackQuery):
    _, gid, src_s, dst_s, die_s = cq.data.split(":")
    src = int(src_s)
    dst = None if dst_s == "off" else int(dst_s)
    die = int(die_s)
    rec = load_game(gid)
    if not rec:
        cq.answer("Игра не найдена", show_alert=True); return
    p = get_player_num(rec, cq.from_user.id)
    if p is None:
        cq.answer("Не участник", show_alert=True); return
    if die in rec["state"]["dice_used"]:
        cq.answer("Этот кубик уже использован", show_alert=True); return
    ok,msg = make_move(rec["state"], p, src, dst, die)
    if not ok:
        cq.answer(msg, show_alert=True); return
    # if no dice left -> change turn
    dice_left = [d for d in rec["state"]["dice"] if d not in rec["state"]["dice_used"]]
    if not dice_left:
        rec["state"]["turn"] = 1 if rec["state"]["turn"]==2 else 2
        rec["state"]["dice"] = []
        rec["state"]["dice_used"] = []
    save_game(rec)
    send_board(rec["chat_id"], rec, caption=rec["state"].get("last_move"))
    cq.answer("Ход выполнен", show_alert=False)

@bot.callback_query_handler(func=lambda cq: cq.data and cq.data.startswith("cancel:"))
def cb_cancel(cq: types.CallbackQuery):
    cq.answer("Отменено", show_alert=False)

# simple command to list active games in chat
@bot.message_handler(commands=["games"])
def cmd_games(m: types.Message):
    cur.execute("SELECT id, state FROM games WHERE chat_id=?", (m.chat.id,))
    rows = cur.fetchall()
    if not rows:
        m.reply("Нет партий в этом чате.")
        return
    text = "Партии:\n"
    for r in rows:
        st = json.loads(r[1])
        text += f"{r[0]} — фаза {st.get('phase')} — ход: {st.get('turn')}\n"
    m.reply(text)

# /debug <gameid> - show seed hash and revealed seed
@bot.message_handler(commands=["debug"])
def cmd_debug(m: types.Message):
    parts = m.text.split()
    if len(parts) < 2:
        m.reply("Использование: /debug <gameid>")
        return
    gid = parts[1]
    rec = load_game(gid)
    if not rec:
        m.reply("Игра не найдена")
        return
    seed = PRIVATE_SEEDS.get(gid)
    m.reply(f"ServerHash: {rec['server_seed_hash']}\nServerSeed (private): {seed}\nRevealed: {rec.get('server_seed_revealed')}")

# fallback
@bot.message_handler(func=lambda m: True)
def fallback(m: types.Message):
    m.reply("Команды: /start, /games, /debug <gameid>.")

# ----------------- Start polling -----------------
if __name__ == "__main__":
    print("Bot started...")
    bot.infinity_polling()
