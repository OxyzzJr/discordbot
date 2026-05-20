from flask import Flask, jsonify
from threading import Thread
import time
import logging
from waitress import serve

app = Flask('')
logger = logging.getLogger(__name__)
_start_time = time.time()


@app.route('/')
def home():
    return "Bot de modération Discord en ligne !"


@app.route('/status')
def status():
    return jsonify({
        "statut": "en ligne",
        "timestamp": time.time(),
        "uptime_secondes": int(time.time() - _start_time)
    })


@app.route('/health')
def health():
    return jsonify({"sain": True, "service": "discord-bot"})


def run():
    try:
        serve(app, host='0.0.0.0', port=5000)
    except Exception as e:
        logger.error(f"Erreur serveur keep-alive : {e}")


def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    logger.info("Serveur keep-alive démarré sur le port 5000")
