#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
API Flask mínima: health check para mantener el servicio despierto en
plataformas como Render, más un par de endpoints para inspeccionar el
estado del anti-spam.
"""

from __future__ import annotations

import logging
import time

from flask import Flask, jsonify

from . import config

logger = logging.getLogger("bot.webapi")


def create_app(engine) -> Flask:
    app = Flask(__name__)

    # Silenciar el logger propio de Flask/Werkzeug en consola
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    @app.route("/health", methods=["GET"])
    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({
            "status": "healthy",
            "bot_running": engine.is_running,
            "bot_connected": engine.is_logged,
            "phone": config.PHONE_NUMBER or "not_set",
            "timestamp": time.time(),
            "commands_loaded": len(engine.dispatcher.antispam.stats) and True,
            "anti_spam": engine.dispatcher.antispam.get_stats(),
        })

    @app.route("/anti-spam/stats", methods=["GET"])
    def anti_spam_stats():
        return jsonify(engine.dispatcher.antispam.get_stats())

    @app.route("/anti-spam/reset", methods=["POST"])
    def anti_spam_reset():
        engine.dispatcher.antispam.reset()
        return jsonify({"status": "reset"})

    @app.route("/")
    def index():
        return jsonify({
            "name": "ToDus Bot",
            "status": "running",
            "endpoints": ["/health", "/api/health", "/anti-spam/stats", "/anti-spam/reset"],
        })

    return app


def run_flask(engine) -> None:
    app = create_app(engine)
    try:
        app.run(host="0.0.0.0", port=config.PORT, debug=False, use_reloader=False)
    except Exception:
        logger.exception("Error al iniciar el servidor Flask.")
