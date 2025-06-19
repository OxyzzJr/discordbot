from flask import Flask
from threading import Thread
import time
import logging

app = Flask('')
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return "Discord Moderation Bot is running!"

@app.route('/status')
def status():
    return {
        "status": "online",
        "timestamp": time.time(),
        "uptime": "24/7"
    }

@app.route('/health')
def health():
    return {"healthy": True, "service": "discord-bot"}

def run():
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"Keep-alive server error: {e}")

def keep_alive():
    """Start the Flask server in a separate thread for 24/7 uptime"""
    t = Thread(target=run)
    t.daemon = True
    t.start()
    logger.info("Keep-alive server started on port 5000")
