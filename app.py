from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import timedelta
import sqlite3
from datetime import datetime
import config
from telethon import TelegramClient, events
import asyncio
import threading
import traceback
import os
import requests
from transformers import BlenderbotTokenizer, BlenderbotForConditionalGeneration
import torch
from instagrapi import Client

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
client = TelegramClient('tg_session.session', config.API_ID, config.API_HASH)  # Use file-based session
client_started = False

# Global event loop for Telethon
telethon_loop = None
telethon_ready = threading.Event()

def run_telegram_client():
    global telethon_loop
    telethon_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(telethon_loop)
    try:
        print("Starting Telegram client...")
        client.start(phone=config.PHONE)
        print("Telegram client started and connected.")
        telethon_ready.set()
        client.run_until_disconnected()
    except Exception as e:
        print("Telegram client failed to start:", e)
        traceback.print_exc()
        # If database is locked, delete session file and ask user to restart
        if "database is locked" in str(e):
            print("Session file is locked. Please stop all Python processes, delete 'tg_session.session', and restart the app.")
        telethon_ready.clear()

def wait_for_telegram_ready(timeout=30):
    import time
    waited = 0
    while not telethon_ready.is_set() and waited < timeout:
        print(f"Waiting for Telegram client to be ready... ({waited+1}s)")
        time.sleep(1)
        waited += 1
    if not telethon_ready.is_set():
        print("Telegram client did not become ready in time.")
        return False
    return True

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
    # Wait for Telethon client and loop to be ready
    if not telethon_ready.is_set():
        print("Telegram client not ready, waiting up to 30 seconds...")
        if not wait_for_telegram_ready(timeout=30):
            raise Exception("Telegram client not ready")
    try:
        # Try to convert chat_id to int, fallback to string if fails
        try:
            chat_id_val = int(chat_id)
        except Exception:
            chat_id_val = chat_id
        print(f"Sending Telegram message to chat_id={chat_id_val}: {message}")
        future = asyncio.run_coroutine_threadsafe(
            client.send_message(chat_id_val, message), telethon_loop
        )
        result = future.result(timeout=10)
        store_message('telegram', 'You', message, 'sent', chat_id=chat_id, chat_name=chat_name)
        return result
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        traceback.print_exc()
        raise e

# Dummy data for other platforms (Instagram, Twitter)
CONVERSATIONS = [
    {'chat_id': '2', 'chat_name': 'Bob', 'platform': 'instagram', 'timestamp': '2024-06-10 09:30', 'msg_count': 3},
    {'chat_id': '3', 'chat_name': 'Charlie', 'platform': 'twitter', 'timestamp': '2024-06-09 18:00', 'msg_count': 2},
]
MESSAGES = {
    '2': [
        {'direction': 'received', 'message': 'Hey!', 'sender': 'Bob', 'timestamp': '2024-06-10 09:30'},
        {'direction': 'sent', 'message': 'Hi Bob, how are you?', 'sender': 'You', 'timestamp': '2024-06-10 09:31'},
        {'direction': 'received', 'message': 'I am good, thanks!', 'sender': 'Bob', 'timestamp': '2024-06-10 09:32'},
    ],
    '3': [
        {'direction': 'received', 'message': 'Hello from Twitter!', 'sender': 'Charlie', 'timestamp': '2024-06-09 18:00'},
        {'direction': 'sent', 'message': 'Hi Charlie!', 'sender': 'You', 'timestamp': '2024-06-09 18:01'},
    ]
}

# --- Local BlenderBot setup ---
BLENDERBOT_MODEL = "facebook/blenderbot-400M-distill"
tokenizer = BlenderbotTokenizer.from_pretrained(BLENDERBOT_MODEL)
model = BlenderbotForConditionalGeneration.from_pretrained(BLENDERBOT_MODEL)

def generate_ai_reply(message_text):
    # Run BlenderBot locally for reply suggestion
    inputs = tokenizer([message_text], return_tensors="pt")
    reply_ids = model.generate(**inputs, max_length=100, pad_token_id=tokenizer.eos_token_id)
    reply = tokenizer.decode(reply_ids[0], skip_special_tokens=True)
    return reply

@app.route('/api/suggest_reply', methods=['POST'])
def api_suggest_reply():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json()
    chat_id = data.get('chat_id')
    platform = data.get('platform')
    if not chat_id or not platform:
        return jsonify({'status': 'error', 'message': 'Missing data'}), 400

    def get_last_received_not_sent(received_list, last_sent):
        for msg in received_list:
            if msg and msg != last_sent:
                return msg
        return received_list[0] if received_list else None

    if platform == 'telegram':
        with sqlite3.connect('messages.db', check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT message FROM messages
                WHERE platform='telegram' AND chat_id=? AND direction='sent'
                ORDER BY timestamp DESC LIMIT 1
            """, (chat_id,))
            last_sent_row = c.fetchone()
            last_sent = last_sent_row[0] if last_sent_row else None

            c.execute("""
                SELECT message FROM messages
                WHERE platform='telegram' AND chat_id=? AND direction='received'
                ORDER BY timestamp DESC
            """, (chat_id,))
            received_rows = [row[0] for row in c.fetchall()]
            last_received = get_last_received_not_sent(received_rows, last_sent)

            if not last_received:
                return jsonify({'status': 'error', 'message': 'No suitable received message found'})
        ai_reply = generate_ai_reply(last_received)
        return jsonify({'status': 'success', 'reply': ai_reply})

    # Dummy for other platforms
    msgs = MESSAGES.get(chat_id, [])
    last_sent = next((m['message'] for m in reversed(msgs) if m['direction'] == 'sent'), None)
    received_msgs = [m['message'] for m in reversed(msgs) if m['direction'] == 'received']
    last_received = get_last_received_not_sent(received_msgs, last_sent)
    if last_received:
        ai_reply = generate_ai_reply(last_received)
        return jsonify({'status': 'success', 'reply': ai_reply})
    return jsonify({'status': 'success', 'reply': 'Hey! How can I help you?'})

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
    telegram_convs = []
    with sqlite3.connect('messages.db', check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT chat_id, COALESCE(chat_name, 'Unknown'), platform, MAX(timestamp) as timestamp, COUNT(*) as msg_count
            FROM messages
            WHERE platform='telegram'
            GROUP BY platform, chat_id
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
    insta_convs = []
    if instagram_client:
        try:
            threads = instagram_client.direct_threads()
            for t in threads:
                # Only show threads with messages and at least one other user
                if not t.messages or not t.users or len(t.users) < 2:
                    continue
                # Find the other user (not yourself)
                other_user = next((u for u in t.users if u.pk != instagram_client.user_id), None)
                if not other_user:
                    continue
                chat_name = other_user.username
                timestamp = ""
                if t.last_message and hasattr(t.last_message, "timestamp"):
                    timestamp = t.last_message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                insta_convs.append({
                    'chat_id': str(t.id),
                    'chat_name': chat_name,
                    'platform': 'instagram',
                    'timestamp': timestamp,
                    'msg_count': len(t.messages),
                    'user_pk': other_user.pk  # needed for sending
                })
        except Exception as e:
            print("Instagram fetch error:", e)
    dummy_twitter = {
        'chat_id': '3',
        'chat_name': 'Charlie',
        'platform': 'twitter',
        'timestamp': MESSAGES['3'][-1]['timestamp'] if MESSAGES['3'] else '2024-06-09 18:00',
        'msg_count': len(MESSAGES['3'])
    }
    return jsonify(telegram_convs + insta_convs + [dummy_twitter])

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
    elif platform == 'instagram':
        msgs = []
        if instagram_client:
            try:
                thread = instagram_client.direct_thread(chat_id)
                for m in thread.messages:
                    try:
                        if not hasattr(m, "text") or m.text is None:
                            continue
                        direction = 'sent' if m.user_id == instagram_client.user_id else 'received'
                        sender = instagram_client.username if direction == 'sent' else (getattr(m.user, 'username', "Unknown") if m.user else "Unknown")
                        timestamp = m.timestamp.strftime("%Y-%m-%d %H:%M:%S") if hasattr(m, "timestamp") else ""
                        msgs.append({
                            'direction': direction,
                            'message': m.text,
                            'sender': sender,
                            'timestamp': timestamp
                        })
                    except Exception as msg_err:
                        print("Instagram message skipped due to error:", msg_err)
            except Exception as e:
                print("Instagram messages fetch error:", e)
        return jsonify(msgs)
    # Always show dummy messages for Twitter
    return jsonify(MESSAGES.get(chat_id, []))

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    data = request.get_json()
    chat_id = data.get('chat_id')
    message = data.get('message')
    platform = data.get('platform')
    chat_name = data.get('chat_name')
    user_pk = data.get('user_pk')  # for Instagram
    if not chat_id or not message:
        return jsonify({'status': 'error', 'message': 'Missing data'}), 400
    if platform == 'telegram':
        try:
            send_telegram_message(chat_id, message, chat_name)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    elif platform == 'instagram':
        try:
            # Use user_pk for sending, not thread id
            if not user_pk:
                # fallback: get user_pk from thread
                thread = instagram_client.direct_thread(chat_id)
                other_user = next((u for u in thread.users if u.pk != instagram_client.user_id), None)
                if not other_user:
                    raise Exception("No recipient found for Instagram message.")
                user_pk = other_user.pk
            instagram_client.direct_send(message, [user_pk])
            return jsonify({'status': 'success'})
        except Exception as e:
            print("Instagram send error:", e)
            return jsonify({'status': 'error', 'message': str(e)})
    # Dummy logic for other platforms
    MESSAGES.setdefault(chat_id, []).append({
        'direction': 'sent',
        'message': message,
        'sender': 'You',
        'timestamp': '2024-06-10 12:00'
    })
    for conv in CONVERSATIONS:
        if conv['chat_id'] == chat_id:
            conv['msg_count'] += 1
            conv['timestamp'] = '2024-06-10 12:00'
    return jsonify({'status': 'success'})

def ensure_telegram_login():
    # Run this in main thread before starting Flask
    with TelegramClient('tg_session.session', config.API_ID, config.API_HASH) as temp_client:
        # Fix: Await the coroutine properly
        authorized = temp_client.loop.run_until_complete(temp_client.is_user_authorized())
        if not authorized:
            print("Telegram not authorized. Starting login flow in main thread.")
            temp_client.start(phone=config.PHONE)
            print("Telegram login complete.")

INSTAGRAM_USERNAME = "unibox233"
INSTAGRAM_PASSWORD = "YDVh 006 1"

instagram_client = None

def login_instagram():
    global instagram_client
    if instagram_client is None:
        instagram_client = Client()
        try:
            instagram_client.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("Instagram client logged in.")
        except Exception as e:
            print("Instagram login failed:", e)
            instagram_client = None

login_instagram()

if __name__ == '__main__':
    # Check for session file lock before starting
    session_file = 'tg_session.session'
    journal_file = 'tg_session.session-journal'
    for f in [session_file, journal_file]:
        if os.path.exists(f):
            try:
                with open(f, 'rb+') as file_check:
                    file_check.write(b'')  # Try to write to check for lock
            except Exception as e:
                print(f"Session file '{f}' is locked or in use. Please close all Python processes and delete this file before starting.")
                exit(1)
    # Ensure Telegram login in main thread so OTP can be entered
    ensure_telegram_login()
    start_telegram_background()
    # Wait for Telegram client to be ready before starting Flask
    wait_for_telegram_ready(timeout=30)
    app.run(debug=False)  # Disable debug auto-reload