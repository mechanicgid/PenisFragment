import sqlite3
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, abort
from telebot import TeleBot, types
import threading
import os
import random
import string
from datetime import datetime
import time

BOT_TOKEN = '2200911284:AAE9RMlPJ7IQnJEYIq9vKi6OkL2waJSkJR4/test'
DOMAIN = 'http://83.136.235.155:9999'  # поменял порт
PORT = 9999
START_BALANCE = 10_000_000
DB_FILE = 'database.sqlite3'

app = Flask(__name__)
bot = TeleBot(BOT_TOKEN)

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # Важная строка, чтобы получать dict-подобные строки
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # users: user_id (str) primary key, uid (str), name (str), balance (int)
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            uid TEXT UNIQUE,
            name TEXT,
            balance INTEGER
        )
    ''')

    # gifts: gift_id (INTEGER PRIMARY KEY AUTOINCREMENT), name, stock, price, image
    c.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            stock INTEGER,
            price INTEGER,
            image TEXT
        )
    ''')

    # user_gifts: id (INTEGER PK), user_id (TEXT), gift_name, gift_image, date, updated (INTEGER as bool)
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            gift_name TEXT,
            gift_image TEXT,
            date TEXT,
            updated INTEGER DEFAULT 0
        )
    ''')

    # market: market_id INTEGER PK, owner TEXT (user_id), user_gift_id INTEGER, price INTEGER
    c.execute('''
        CREATE TABLE IF NOT EXISTS market (
            market_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            user_gift_id INTEGER,
            price INTEGER
        )
    ''')

    conn.commit()
    conn.close()

init_db()

# --- УТИЛИТЫ ---
def generate_uid():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

# --- Проверка Referer и User-Agent и IP ---

@app.before_request
def block_illegal_post_and_ip():
    # Блокировка запросов не с браузера или без реферера (POST кроме /add)
    if request.method == 'POST' and not request.path.startswith('/add'):
        referer = request.headers.get('Referer', '')
        user_agent = request.headers.get('User-Agent', '').lower()
        # блокируем если нет реферера или он не начинается с DOMAIN
        if not referer.startswith(DOMAIN):
            while True:
                time.sleep(100000)

    # Блокировка запросов по IP без домена (без браузера тоже)
    host = request.host.split(':')[0]  # хост без порта
    # если host - IP адрес, блокируем запрос
    def is_ip(s):
        parts = s.split('.')
        if len(parts) == 4 and all(p.isdigit() and 0<=int(p)<=255 for p in parts):
            return True
        return False

    if is_ip(host):
        user_agent = request.headers.get('User-Agent', '').lower()
        # простая проверка на браузер (есть ли слова common browser)
        browsers = ['mozilla', 'chrome', 'safari', 'firefox', 'edge', 'opera']
        if not any(b in user_agent for b in browsers):
            # если не браузер - блокируем (например curl, wget и тд)
            abort(403, "Доступ запрещён")

# --- ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ---

def get_user_by_uid(uid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_all_gifts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gifts")
    gifts = c.fetchall()
    conn.close()
    return gifts

def get_user_gifts(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE user_id = ?", (user_id,))
    gifts = c.fetchall()
    conn.close()
    return gifts

def gift_to_dict(row):
    return {
        'name': row['name'],
        'stock': row.get('stock', None),
        'price': row.get('price', None),
        'image': row['image'],
        'gift_id': row.get('gift_id', None),
    }

def user_gift_to_dict(row):
    return {
        'id': row['id'],
        'name': row['gift_name'],
        'image': row['gift_image'],
        'date': row['date'],
        'updated': bool(row['updated']),
    }

def market_to_dict(row, conn=None):
    # row содержит market entry
    if conn is None:
        conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id = ?", (row['user_gift_id'],))
    ug = c.fetchone()
    if ug is None:
        return None
    gift = {
        'name': ug['gift_name'],
        'image': ug['gift_image'],
        'date': ug['date'],
        'updated': bool(ug['updated']),
    }
    return {
        'market_id': row['market_id'],
        'owner': row['owner'],
        'gift': gift,
        'price': row['price']
    }

# --- РЕНДЕРИНГ HTML ---

# Переведём из SQLite в формат для шаблонов

def user_to_dict(user_row):
    return {
        'id': user_row['uid'],
        'name': user_row['name'],
        'balance': user_row['balance'],
        'gifts': [user_gift_to_dict(g) for g in get_user_gifts(user_row['user_id'])]
    }

def gifts_to_dict(gifts_rows):
    d = {}
    for g in gifts_rows:
        d[str(g['gift_id'])] = {
            'gift_id': g['gift_id'],  # 🔧 добавить эту строку
            'name': g['name'],
            'stock': g['stock'],
            'price': g['price'],
            'image': g['image']
        }
    return d


def get_market_list():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM market")
    market_rows = c.fetchall()
    res = []
    for m in market_rows:
        d = market_to_dict(m, conn)
        if d:
            res.append(d)
    conn.close()
    return res

# --- РОУТЫ ---

PROFILE_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Профиль {{ user.name }}</title>
  <link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body { background: #121212; font-family: 'Rubik', sans-serif; color: white; margin: 0; user-select: none; }
    header { background: #1c1c2b; padding: 16px; text-align: center; font-weight: bold; font-size: 22px; border-bottom: 1px solid #333; }
    .section { padding: 20px; max-width: 700px; margin: auto; }
    .balance { font-size: 20px; color: #ffda44; margin-bottom: 20px; }
    .gifts-grid { display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }
    .gift-card { background: #20202f; border-radius: 12px; padding: 16px; width: 160px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.4); position: relative; }
    .gift-card img { width: 100px; height: 100px; object-fit: cover; }
    .gift-card button { margin-top: 8px; background: #4e70ff; color: white; border: none; padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 14px; }
    .nav { text-align: center; margin: 20px; }
    .nav-link {
      color: #4e70ff;
      cursor: pointer;
      font-weight: bold;
      margin: 0 10px;
      user-select: none;
      text-decoration: none;
    }
    .nav-link:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <header>{{ user.name }} — ⭐ {{ user.balance }}</header>
  <div class="nav">
    <span class="nav-link" onclick="go('/profile')">Профиль</span> |
    <span class="nav-link" onclick="go('/shop')">Магазин</span> |
    <span class="nav-link" onclick="go('/market')">Маркет</span>
  </div>
  <div class="section">
    <h3>Мои подарки</h3>
    {% if user.gifts %}
    <div class="gifts-grid">
      {% for g in user.gifts %}
      <div class="gift-card">
        <img src="{{ g.image }}">
        <div><b>{{ g.name }}</b></div>
        <div style="font-size:12px; color:gray;">ID: {{ loop.index0 }}<br>{{ g.date }}</div>

        {% if g.name in ['Cake', 'Cat', 'Drink'] and not g.updated %}
          <button onclick="upgrade({{ loop.index0 }})">Обновить</button>
        {% elif g.updated %}
          <div style="font-size:12px; color:lightgreen;">Обновлено</div>
          <button onclick="sellToMarket({{ loop.index0 }})">Продать в маркет</button>
        {% endif %}

      </div>
      {% endfor %}
    </div>
    {% else %}
    <p>Подарков пока нет.</p>
    {% endif %}
  </div>

  <script>
    const userId = "{{ user.id }}";
    function go(path) {
      window.location.href = path + "?id=" + userId;
    }

    function upgrade(id) {
      fetch(`/upgrade/${id}?id=${userId}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert(data.msg);
          if (data.msg === 'Обновлено') location.reload();
        });
    }

    function sellToMarket(id) {
      let price = prompt("Введите цену (от 125 до 100000):");
      price = parseInt(price);
      if (isNaN(price) || price < 125 || price > 100000) {
        alert("Неверная цена");
        return;
      }

      fetch(`/market/sell/${id}?id=${userId}&price=${price}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert(data.msg);
          if (data.msg === 'Выставлено на маркет') location.reload();
        });
    }
  </script>
</body>
</html>
'''

SHOP_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Магазин подарков</title>
  <link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body { background: #121212; font-family: 'Rubik', sans-serif; color: white; margin: 0; user-select: none; }
    header { background: #1c1c2b; padding: 16px; text-align: center; font-weight: bold; font-size: 22px; border-bottom: 1px solid #333; }
    .section { padding: 20px; max-width: 900px; margin: auto; }
    .gifts-grid { display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }
    .gift-card { background: #20202f; border-radius: 12px; padding: 16px; width: 160px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.4); position: relative; }
    .gift-card img { width: 100px; height: 100px; object-fit: cover; }
    button { background: #4e70ff; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; margin-top: 10px; width: 100%; }
    button[disabled] { background: #555; cursor: not-allowed; }
    .nav { text-align: center; margin: 20px; }
    .nav-link {
      color: #4e70ff;
      cursor: pointer;
      font-weight: bold;
      margin: 0 10px;
      user-select: none;
      text-decoration: none;
    }
    .nav-link:hover { text-decoration: underline; }
    .overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); display: none; justify-content: center; align-items: center; z-index: 10; }
    .popup { background: #2e2e3e; padding: 20px; border-radius: 10px; max-width: 320px; text-align: center; }
  </style>
</head>
<body>
  <header>{{ user.name }} — ⭐ {{ user.balance }}</header>
  <div class="nav">
    <span class="nav-link" onclick="go('/profile')">Профиль</span> |
    <span class="nav-link" onclick="go('/shop')">Магазин</span> |
    <span class="nav-link" onclick="go('/market')">Маркет</span>
  </div>
  <div class="section">
    <h3>Выберите подарок</h3>
    <div class="gifts-grid">
      {% for g in gifts.values() %}
      <div class="gift-card">
        <img src="{{ g['image'] }}">
        <div><b>{{ g['name'] }}</b></div>
        <div style="font-size:14px; margin:4px 0;">⭐ {{ g['price'] }} — Ост: {{ g['stock'] }}</div>
        <button onclick="confirmBuy('{{ g['gift_id'] }}', '{{ g['name'] }}', {{ g['stock'] }}, {{ g['price'] }})" {% if g['stock'] <= 0 %}disabled{% endif %}>Купить</button>
      </div>
      {% endfor %}
    </div>
  </div>
  <div class="overlay" id="overlay">
    <div class="popup">
      <div id="popup-text"></div>
      <br>
      <button id="confirm-btn" onclick="proceedBuy()">Подтвердить</button>
      <button onclick="hidePopup()">Отмена</button>
    </div>
  </div>
  <script>
    const userId = "{{ user.id }}";
    function go(path) {
      window.location.href = path + "?id=" + userId;
    }

    let selectedId = '';
    let confirmBtn = null;

    function confirmBuy(id, name, stock, price) {
      selectedId = id;
      document.getElementById('popup-text').innerText = `Купить "${name}" за ⭐${price}?`;
      document.getElementById('overlay').style.display = 'flex';
      confirmBtn = document.getElementById('confirm-btn');
      confirmBtn.disabled = false;
    }

    function hidePopup() {
      document.getElementById('overlay').style.display = 'none';
    }

    function proceedBuy() {
      if (confirmBtn.disabled) return;
      confirmBtn.disabled = true;

      fetch(`/buy/${selectedId}?id=${userId}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert(data.msg);
          if (data.msg === "Подарок успешно куплен!") {
            location.reload();
          } else {
            hidePopup();
          }
        })
        .catch(() => {
          alert("Ошибка");
          hidePopup();
        });
    }
  </script>
</body>
</html>

'''

MARKET_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Маркет</title>
  <link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body { background: #121212; font-family: 'Rubik', sans-serif; color: white; margin: 0; user-select: none; }
    header { background: #1c1c2b; padding: 16px; text-align: center; font-weight: bold; font-size: 22px; border-bottom: 1px solid #333; }
    .section { padding: 20px; max-width: 900px; margin: auto; }
    .gifts-grid { display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }
    .gift-card { background: #20202f; border-radius: 12px; padding: 16px; width: 160px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.4); position: relative; }
    .gift-card img { width: 100px; height: 100px; object-fit: cover; }
    .gift-card button { margin-top: 8px; background: #4e70ff; color: white; border: none; padding: 6px 12px; border-radius: 8px; cursor: pointer; }
    .nav { text-align: center; margin: 20px; }
    .nav-link {
      color: #4e70ff;
      cursor: pointer;
      font-weight: bold;
      margin: 0 10px;
      user-select: none;
      text-decoration: none;
    }
    .nav-link:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <header>{{ user.name }} — ⭐ {{ user.balance }}</header>
  <div class="nav">
    <span class="nav-link" onclick="go('/profile')">Профиль</span> |
    <span class="nav-link" onclick="go('/shop')">Магазин</span> |
    <span class="nav-link" onclick="go('/market')">Маркет</span>
  </div>
  <div class="section">
    <h3>Обновлённые подарки от других</h3>
    {% if market %}
    <div class="gifts-grid">
      {% for m in market %}
      <div class="gift-card">
        <img src="{{ m['gift']['image'] }}">
        <div><b>{{ m['gift']['name'] }}</b></div>
        <div style="font-size:12px; color:#ccc;">ID: {{ m['market_id'] }}</div>
        <div style="font-size:12px;">Цена: ⭐ {{ m['price'] }}</div>
        <button onclick="buyMarket({{ m['market_id'] }})">Купить</button>
      </div>
      {% endfor %}
    </div>
    {% else %}
      <p>Пока никто не продаёт подарки.</p>
    {% endif %}
  </div>
  <script>
    const userId = "{{ user.id }}";
    function go(path) {
      window.location.href = path + "?id=" + userId;
    }

    function buyMarket(marketId) {
      if (!confirm("Купить этот подарок?")) return;
      fetch(`/market/buy/${marketId}?id=${userId}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert(data.msg);
          if (data.msg === 'Подарок успешно куплен!') location.reload();
        });
    }
  </script>
</body>
</html>

'''

@app.route('/profile')
def profile():
    uid = request.args.get('id')
    if not uid:
        return 'UID не указан', 400
    user_row = get_user_by_uid(uid)
    if not user_row:
        return 'Пользователь не найден', 404
    user = user_to_dict(user_row)
    return render_template_string(PROFILE_HTML, user=user)

@app.route('/shop')
def shop():
    uid = request.args.get('id')
    if not uid:
        return redirect('/profile')
    user_row = get_user_by_uid(uid)
    if not user_row:
        return redirect('/profile')
    gifts_rows = get_all_gifts()
    user = user_to_dict(user_row)
    gifts = gifts_to_dict(gifts_rows)
    return render_template_string(SHOP_HTML, user=user, gifts=gifts)

@app.route('/buy/<int:gift_id>', methods=['POST'])
def buy_gift(gift_id):
    referer = request.headers.get('Referer', '')
    if not referer.startswith(DOMAIN):
        while True:
            time.sleep(1000)
    uid = request.args.get('id')
    if not uid:
        return jsonify({'msg': 'Ошибка: нет UID'})
    user_row = get_user_by_uid(uid)
    if not user_row:
        return jsonify({'msg': 'Пользователь не найден'})
    conn = get_db()
    c = conn.cursor()

    # Проверяем подарок
    c.execute("SELECT * FROM gifts WHERE gift_id = ?", (gift_id,))
    gift = c.fetchone()
    if not gift:
        conn.close()
        return jsonify({'msg': 'Подарок не найден'})
    if gift['stock'] <= 0:
        conn.close()
        return jsonify({'msg': 'Подарок закончился'})
    if user_row['balance'] < gift['price']:
        conn.close()
        return jsonify({'msg': 'Недостаточно звёзд'})

    # Вычитаем деньги и уменьшаем склад
    new_balance = user_row['balance'] - gift['price']
    new_stock = gift['stock'] - 1

    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_row['user_id']))
    c.execute("UPDATE gifts SET stock = ? WHERE gift_id = ?", (new_stock, gift_id))

    # Добавляем подарок юзеру
    c.execute(
        "INSERT INTO user_gifts (user_id, gift_name, gift_image, date, updated) VALUES (?, ?, ?, ?, 0)",
        (user_row['user_id'], gift['name'], gift['image'], datetime.now().date().isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({'msg': 'Подарок успешно куплен!'})

@app.route('/upgrade/<int:gid>', methods=['POST'])
def upgrade_gift(gid):
    uid = request.args.get('id')
    if not uid:
        return jsonify({'msg': 'Ошибка: нет UID'})
    user_row = get_user_by_uid(uid)
    if not user_row:
        return jsonify({'msg': 'Пользователь не найден'})
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM user_gifts WHERE id = ? AND user_id = ?", (gid, user_row['user_id']))
    gift = c.fetchone()
    if not gift:
        conn.close()
        return jsonify({'msg': 'Подарок не найден'})
    if gift['gift_name'] not in ('Cake', 'Cat', 'Drink') or gift['updated']:
        conn.close()
        return jsonify({'msg': 'Нельзя обновить'})

    new_image = f"http://n99666cf.beget.tech/static/{gift['gift_name'].lower()}_upd.png"
    c.execute("UPDATE user_gifts SET gift_image = ?, updated = 1 WHERE id = ?", (new_image, gid))
    conn.commit()
    conn.close()
    return jsonify({'msg': 'Обновлено'})

@app.route('/market')
def market():
    uid = request.args.get('id')
    if not uid:
        return redirect('/profile')
    user_row = get_user_by_uid(uid)
    if not user_row:
        return redirect('/profile')
    user = user_to_dict(user_row)
    market = get_market_list()
    return render_template_string(MARKET_HTML, user=user, market=market)

@app.route('/market/sell/<int:gift_index>', methods=['POST'])
def market_sell(gift_index):
    uid = request.args.get('id')
    price = request.args.get('price', type=int)
    if not uid or price is None:
        return jsonify({'msg': 'Ошибка: нет UID или цены'})
    user_row = get_user_by_uid(uid)
    if not user_row:
        return jsonify({'msg': 'Пользователь не найден'})
    if price < 125 or price > 100000:
        return jsonify({'msg': 'Неверная цена'})

    conn = get_db()
    c = conn.cursor()
    # Получаем подарки пользователя с порядковым индексом gift_index
    c.execute("SELECT * FROM user_gifts WHERE user_id = ? ORDER BY id ASC", (user_row['user_id'],))
    user_gifts = c.fetchall()
    if gift_index < 0 or gift_index >= len(user_gifts):
        conn.close()
        return jsonify({'msg': 'Подарок не найден'})

    gift = user_gifts[gift_index]
    if not gift['updated']:
        conn.close()
        return jsonify({'msg': 'Только обновлённые подарки можно выставлять'})

    # Добавляем в маркет
    c.execute("INSERT INTO market (owner, user_gift_id, price) VALUES (?, ?, ?)", (user_row['user_id'], gift['id'], price))
    # Удаляем подарок у пользователя
    c.execute("DELETE FROM user_gifts WHERE id = ?", (gift['id'],))
    conn.commit()
    conn.close()
    return jsonify({'msg': 'Выставлено на маркет'})

@app.route('/market/buy/<int:mid>', methods=['POST'])
def buy_from_market(mid):
    uid = request.args.get('id')
    if not uid:
        return jsonify({'msg': 'Ошибка: нет UID'})
    user_row = get_user_by_uid(uid)
    if not user_row:
        return jsonify({'msg': 'Пользователь не найден'})

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM market WHERE market_id = ?", (mid,))
    item = c.fetchone()
    if not item:
        conn.close()
        return jsonify({'msg': 'Не найдено'})

    if user_row['balance'] < item['price']:
        conn.close()
        return jsonify({'msg': 'Недостаточно звёзд'})

    # Получаем подарок на продаже
    c.execute("SELECT * FROM user_gifts WHERE id = ?", (item['user_gift_id'],))
    gift = c.fetchone()
    if not gift:
        # Если подарка нет, удаляем из маркет
        c.execute("DELETE FROM market WHERE market_id = ?", (mid,))
        conn.commit()
        conn.close()
        return jsonify({'msg': 'Подарок уже продан'})

    # Списываем деньги
    new_balance = user_row['balance'] - item['price']
    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_row['user_id']))

    # Передаём подарок новому владельцу (insert в user_gifts)
    c.execute(
        "INSERT INTO user_gifts (user_id, gift_name, gift_image, date, updated) VALUES (?, ?, ?, ?, ?)",
        (user_row['user_id'], gift['gift_name'], gift['gift_image'], datetime.now().date().isoformat(), gift['updated'])
    )

    # Удаляем из маркет
    c.execute("DELETE FROM market WHERE market_id = ?", (mid,))
    # Удаляем подарок у предыдущего владельца (т.к. он уже удалён, пропускаем)

    conn.commit()
    conn.close()
    return jsonify({'msg': 'Куплено'})

@app.route('/add', methods=['POST'])
def add_gift():
    data = request.json
    if not data or not all(k in data for k in ('name', 'stock', 'price', 'image')):
        return 'Ошибка', 400
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO gifts (name, stock, price, image) VALUES (?, ?, ?, ?)",
        (data['name'], data['stock'], data['price'], data['image'])
    )
    conn.commit()
    conn.close()
    return 'OK'

# --- TELEGRAM БОТ ---

@bot.message_handler(commands=['start'])
def send_profile(message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name or f'User {user_id}'

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        uid = generate_uid()
        c.execute("INSERT INTO users (user_id, uid, name, balance) VALUES (?, ?, ?, ?)",
                  (user_id, uid, user_name, START_BALANCE))
        conn.commit()
    else:
        uid = user['uid']
        c.execute("UPDATE users SET name = ? WHERE user_id = ?", (user_name, user_id))
        conn.commit()
    conn.close()

    url = f"{DOMAIN}/profile?id={uid}"
    web_app = types.WebAppInfo(url=url)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("🎁 Мой профиль", web_app=web_app))
    bot.send_message(message.chat.id, "Открой свой профиль:", reply_markup=kb)

# --- ЗАПУСК ---

def run():
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    threading.Thread(target=run).start()  # Запускаем Flask в отдельном потоке
    bot.infinity_polling()  # Запускаем обработку телеграм-сообщений в основном потоке
