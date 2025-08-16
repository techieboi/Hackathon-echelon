import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

# --- Database: SQLite (site.db) ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Message Model ---
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50), nullable=False)  # e.g. "Web"
    sender = db.Column(db.String(100), nullable=False)
    recipient = db.Column(db.String(100), nullable=True)
    content = db.Column(db.Text, nullable=False)
    direction = db.Column(db.String(10), nullable=False, default="in")  # in/out
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "platform": self.platform,
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "direction": self.direction,
            "timestamp": self.timestamp.isoformat()
        }

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# API to fetch all messages
@app.route("/api/messages", methods=["GET"])
def get_messages():
    messages = Message.query.order_by(Message.timestamp.asc()).all()
    return jsonify([m.to_dict() for m in messages])

# API to add a new message
@app.route("/api/messages", methods=["POST"])
def add_message():
    data = request.get_json()
    if not data or not data.get("content"):
        return jsonify({"error": "Message content is required"}), 400

    msg = Message(
        platform=data.get("platform", "Web"),
        sender=data.get("sender", "You"),
        recipient=data.get("recipient"),
        content=data.get("content"),
        direction=data.get("direction", "out"),
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify(msg.to_dict()), 201


if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Creates site.db and messages table if not exists
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
