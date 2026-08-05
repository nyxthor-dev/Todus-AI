#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Dispatcher central: recibe cada mensaje entrante del SDK de ToDus y
decide qué hacer con él.

Flujo:
1. Ignorar mensajes propios del bot.
2. Filtrar duplicados/offline-spam y rate limit por usuario.
3. Si es multimedia (imagen/video/archivo/sticker/...), delegar al
   manejador de multimedia.
4. Si es texto y coincide con un comando registrado (según los
   prefijos configurados), ejecutar su handler.
5. Cualquier error de un comando se atrapa, se loguea como error
   (visible en consola) y se informa al usuario sin tumbar el bot.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from . import config
from .antispam import AntiSpamManager
from .context import CommandContext
from .media import handle_incoming_media
from .parsing import detect_media_type, parse_command
from .registry import registry

logger = logging.getLogger("bot.dispatcher")


class Dispatcher:
    def __init__(self, client, bot_jid: str):
        self.client = client
        self.bot_jid = bot_jid
        self.antispam = AntiSpamManager(
            max_messages=config.ANTISPAM_MAX_CACHE,
            cooldown_seconds=config.ANTISPAM_COOLDOWN_SECONDS,
        )

    # ------------------------------------------------------------------
    # Helpers de identificación de mensajes
    # ------------------------------------------------------------------
    def _is_own_message(self, message: dict) -> bool:
        sender = message.get("from", "")
        if not sender or not self.bot_jid:
            return False
        return sender.split("/")[0] == self.bot_jid

    @staticmethod
    def _extract_user_id(message: dict) -> str:
        sender = message.get("from", "")
        return sender.split("/")[0] if sender else ""

    @staticmethod
    def _unique_id(message: dict) -> str:
        msg_id = message.get("id", "")
        if msg_id:
            return f"id_{msg_id}"

        sender = message.get("from", "")
        body = message.get("body", "")
        url = message.get("url", "")
        if url:
            return hashlib.md5(f"{sender}:url:{url}".encode()).hexdigest()
        if body:
            return hashlib.md5(f"{sender}:body:{body}".encode()).hexdigest()

        timestamp = message.get("sent_at", time.time())
        return hashlib.md5(f"{sender}:{timestamp}".encode()).hexdigest()

    # ------------------------------------------------------------------
    # Entrada principal
    # ------------------------------------------------------------------
    def handle(self, message: dict) -> None:
        if self._is_own_message(message):
            return

        msg_id = message.get("id", "") or self._unique_id(message)
        user_id = self._extract_user_id(message)

        if self.antispam.is_duplicate_id(msg_id):
            logger.debug("Mensaje duplicado/offline ignorado (id=%s)", msg_id)
            return

        if self.antispam.is_rate_limited(user_id):
            logger.debug("Rate limit aplicado a %s", user_id)
            return

        self.antispam.register_message(msg_id, user_id)

        media_label = detect_media_type(message)
        if media_label:
            handle_incoming_media(self.client, message, media_label)
            return

        body = (message.get("body") or "").strip()
        if not body or message.get("is_group"):
            return

        if not user_id:
            return

        self._dispatch_command(message, body)

    # ------------------------------------------------------------------
    # Ejecución de comandos
    # ------------------------------------------------------------------
    def _dispatch_command(self, message: dict, body: str) -> None:
        parsed = parse_command(body)
        if not parsed:
            return

        spec = registry.resolve(parsed.command)
        if not spec:
            return

        ctx = CommandContext(
            client=self.client,
            message=message,
            command_name=spec.name,
            args=parsed.args,
            raw_args=parsed.raw_args,
        )
        ctx._antispam_stats = self.antispam.get_stats()

        try:
            spec.handler(ctx)
        except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo de un comando
            logger.error("Error ejecutando el comando '%s': %s", spec.name, exc, exc_info=True)
            try:
                ctx.reply_error(f"Ocurrió un error al ejecutar '{spec.name}': {str(exc)[:150]}")
            except Exception:
                logger.exception("Además falló el aviso de error al usuario.")
