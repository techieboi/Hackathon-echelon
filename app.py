from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import sqlite3
from datetime import datetime
import threading
import config
from telethon import TelegramClient, events
import asyncio

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this!

# --- Database setup ---
def init_db():
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            direction TEXT NOT NULL,
            chat_id TEXT,
            recipient TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Telegram setup ---
client = TelegramClient('tg_session', config.API_ID, config.API_HASH)

def store_message(platform, sender, message, direction, chat_id=None, recipient=None):
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (platform, sender, message, timestamp, direction, chat_id, recipient) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (platform, sender, message, datetime.now(), direction, chat_id, recipient))
    conn.commit()
    conn.close()

@client.on(events.NewMessage)
async def telegram_message_handler(event):
    sender = await event.get_sender()
    sender_name = sender.first_name if sender else "Unknown"
    chat_id = event.chat_id
    # For private chats, recipient is the sender
    store_message('telegram', sender_name, event.text, 'received', chat_id=chat_id, recipient=None)

def send_telegram_message(chat_id, message):
    # Use run_coroutine_threadsafe to send message in Telethon's event loop
    future = asyncio.run_coroutine_threadsafe(client.send_message(int(chat_id), message), client.loop)
    return future.result()

def start_telegram():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client.start(phone=config.PHONE)
    client.run_until_disconnected()

# Start Telegram client in a separate thread
threading.Thread(target=start_telegram, daemon=True).start()

# --- Flask routes ---
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/conversations')
def api_conversations():
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute('''
        SELECT platform, 
               COALESCE(recipient, sender) as chat_name, 
               MAX(timestamp) as timestamp, 
               COUNT(*) as msg_count, 
               chat_id
        FROM messages
        GROUP BY platform, chat_name, chat_id
        ORDER BY MAX(timestamp) DESC
    ''')
    conversations = [
        {'platform': row[0], 'chat_name': row[1], 'timestamp': row[2], 'msg_count': row[3], 'chat_id': row[4]}
        for row in c.fetchall()
    ]
    conn.close()
    return jsonify(conversations)

@app.route('/api/messages')
def api_messages():
    platform = request.args.get('platform')
    chat_id = request.args.get('chat_id')
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    if platform and chat_id:
        c.execute("SELECT sender, message, timestamp, direction, chat_id FROM messages WHERE platform=? AND chat_id=? ORDER BY timestamp ASC", (platform, chat_id))
    elif platform:
        c.execute("SELECT sender, message, timestamp, direction, chat_id FROM messages WHERE platform=? ORDER BY timestamp ASC", (platform,))
    else:
        c.execute("SELECT sender, message, timestamp, direction, chat_id FROM messages ORDER BY timestamp ASC")
    messages = [
        {'sender': row[0], 'message': row[1], 'timestamp': row[2], 'direction': row[3], 'chat_id': row[4]}
        for row in c.fetchall()
    ]
    conn.close()
    return jsonify(messages)

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    data = request.json
    platform = data.get('platform')
    message = data.get('message')
    chat_id = data.get('chat_id')
    chat_name = data.get('chat_name')
    sender = 'You'
    if not message or not chat_id:
        return jsonify({'status': 'error', 'message': 'No message or chat_id provided'})
    # Store in DB (recipient is chat_name)
    store_message(platform, sender, message, 'sent', chat_id, recipient=chat_name)
    # Send via Telegram if platform is telegram
    if platform == 'telegram':
        try:
            send_telegram_message(chat_id, message)
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    app.run(debug=True)