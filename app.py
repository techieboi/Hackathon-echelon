from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import timedelta
import sqlite3
from datetime import datetime
import config
from telethon import TelegramClient, events
import asyncio
import threading

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this!
app.permanent_session_lifetime = timedelta(hours=2)

# Updated user for demo
USER = {'email': 'devbysomya@gmail.com', 'password': '123'}

# --- Database setup ---
def init_db():
    conn = sqlite3.connect('messages.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            direction TEXT NOT NULL,
            chat_id TEXT,
            recipient TEXT,
            chat_name TEXT
        )
    ''')
    conn.commit()
    conn.close()
init_db()

# --- Telegram setup ---
client = TelegramClient('tg_session', config.API_ID, config.API_HASH)
client_started = False

# Global event loop for Telethon
telethon_loop = None

def run_telegram_client():
    global telethon_loop
    telethon_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(telethon_loop)
    client.start(phone=config.PHONE)
    client.run_until_disconnected()

def start_telegram_background():
    global client_started
    if not client_started:
        threading.Thread(target=run_telegram_client, daemon=True).start()
        client_started = True

def start_telegram():
    global client_started
    if not client_started:
        client.start(phone=config.PHONE)
        client_started = True

def store_message(platform, sender, message, direction, chat_id=None, recipient=None, chat_name=None):
    with sqlite3.connect('messages.db', check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO messages (platform, sender, message, timestamp, direction, chat_id, recipient, chat_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (platform, sender, message, datetime.now(), direction, chat_id, recipient, chat_name))
        conn.commit()

@client.on(events.NewMessage)
async def telegram_message_handler(event):
    try:
        sender = await event.get_sender()
        sender_name = sender.first_name if sender else "Unknown"
        if sender and sender.last_name:
            sender_name += " " + sender.last_name
        chat = await event.get_chat()
        chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Unknown')
        chat_id = str(event.chat_id)
        store_message('telegram', sender_name, event.text, 'received', chat_id=chat_id, chat_name=chat_name)
    except Exception as e:
        print(f"Error handling Telegram message: {e}")

def send_telegram_message(chat_id, message, chat_name=None):
    global telethon_loop
    start_telegram_background()
    # Wait for Telethon client and loop to be ready
    import time
    for _ in range(20):  # Wait up to 2 seconds
        if telethon_loop and client.is_connected():
            break
        time.sleep(0.1)
    if not telethon_loop or not client.is_connected():
        raise Exception("Telegram client not ready")
    try:
        future = asyncio.run_coroutine_threadsafe(
            client.send_message(int(chat_id), message), telethon_loop
        )
        result = future.result(timeout=10)
        store_message('telegram', 'You', message, 'sent', chat_id=chat_id, chat_name=chat_name)
        return result
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        raise e

# --- Flask routes ---
@app.route('/')
def index():
    # Always serve index.html as the main page, even if logged in
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    if email == USER['email'] and password == USER['password']:
        session['user'] = email
        # AJAX/fetch request returns JSON, otherwise redirect
        if request.headers.get('Accept') == 'application/json' or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True})
        return redirect(url_for('dashboard'))
    if request.headers.get('Accept') == 'application/json' or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False})
    return render_template('index.html', error='Invalid credentials')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

@app.route('/api/conversations')
def api_conversations():
    if 'user' not in session:
        return jsonify([]), 401
    with sqlite3.connect('messages.db', check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT chat_id, COALESCE(chat_name, 'Unknown'), platform, MAX(timestamp) as timestamp, COUNT(*) as msg_count
            FROM messages
            WHERE platform='telegram'
            GROUP BY chat_id
            ORDER BY timestamp DESC
        """)
        telegram_convs = [
            {
                'chat_id': row[0],
                'chat_name': row[1],
                'platform': row[2],
                'timestamp': row[3],
                'msg_count': row[4]
            }
            for row in c.fetchall()
        ]
    # Dummy for other platforms
    dummy_convs = [
        {'chat_id': '2', 'chat_name': 'Bob', 'platform': 'instagram', 'timestamp': '2024-06-10 09:30', 'msg_count': 1},
        {'chat_id': '3', 'chat_name': 'Charlie', 'platform': 'twitter', 'timestamp': '2024-06-09 18:00', 'msg_count': 0},
    ]
    return jsonify(telegram_convs + dummy_convs)

@app.route('/api/messages')
def api_messages():
    if 'user' not in session:
        return jsonify([]), 401
    chat_id = request.args.get('chat_id')
    platform = request.args.get('platform')
    if platform == 'telegram':
        with sqlite3.connect('messages.db', check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT direction, message, sender, timestamp
                FROM messages
                WHERE platform='telegram' AND chat_id=?
                ORDER BY timestamp ASC
            """, (chat_id,))
            msgs = [
                {
                    'direction': row[0],
                    'message': row[1],
                    'sender': row[2],
                    'timestamp': row[3]
                }
                for row in c.fetchall()
            ]
        return jsonify(msgs)
    # Dummy for other platforms
    return jsonify([
        {'direction': 'received', 'message': 'Hey!', 'sender': 'Bob', 'timestamp': '2024-06-10 09:30'}
    ] if chat_id == '2' else [])

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json()
    chat_id = data.get('chat_id')
    message = data.get('message')
    platform = data.get('platform')
    chat_name = data.get('chat_name')
    if not chat_id or not message:
        return jsonify({'status': 'error', 'message': 'Missing data'}), 400
    if platform == 'telegram':
        try:
            start_telegram_background()
            send_telegram_message(chat_id, message, chat_name)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    # Dummy logic for other platforms
    # Add message to dummy data
    MESSAGES.setdefault(chat_id, []).append({
        'direction': 'sent',
        'message': message,
        'sender': 'You',
        'timestamp': '2024-06-10 12:00'
    })
    # Update conversation msg_count
    for conv in CONVERSATIONS:
        if conv['chat_id'] == chat_id:
            conv['msg_count'] += 1
            conv['timestamp'] = '2024-06-10 12:00'
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    # Only start Flask, Telegram client will start in background as needed
    app.run(debug=True)