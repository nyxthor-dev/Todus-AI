#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CommandContext: objeto que recibe cada handler de comando.

Envuelve el mensaje crudo del SDK de ToDus y expone helpers cómodos
(reply, edit, send_image, etc.) para que los comandos no tengan que
repetir boilerplate de client.send_message(sender_phone, ...) en cada
archivo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger("bot.context")


@dataclass
class CommandContext:
    client: Any                 # instancia de ToDusClient2
    message: dict                # mensaje crudo recibido del SDK
    command_name: str            # nombre del comando ya resuelto (sin prefijo/alias)
    args: List[str] = field(default_factory=list)   # argumentos separados por espacio
    raw_args: str = ""           # todo el texto después del comando, sin separar

    # -- Datos derivados del mensaje, calculados una sola vez --
    @property
    def sender_jid(self) -> str:
        return self.message.get("from", "") or ""

    @property
    def sender_phone(self) -> str:
        return self.sender_jid.split("@")[0].split("/")[0]

    @property
    def is_group(self) -> bool:
        return bool(self.message.get("is_group"))

    @property
    def body(self) -> str:
        return self.message.get("body", "") or ""

    # -- Helpers de respuesta --
    def reply(self, text: str) -> Optional[str]:
        """Envía un mensaje de texto de vuelta al remitente."""
        try:
            return self.client.send_message(self.sender_phone, text)
        except Exception:
            logger.exception("Error enviando respuesta a %s", self.sender_phone)
            return None

    def edit(self, new_text: str, message_id: str) -> Optional[str]:
        """Edita un mensaje previamente enviado (por ejemplo, de progreso)."""
        try:
            return self.client.edit_message(self.sender_phone, new_text, message_id)
        except Exception:
            logger.exception("Error editando mensaje %s para %s", message_id, self.sender_phone)
            return None

    def reply_error(self, text: str) -> Optional[str]:
        return self.reply(f"❌ {text}")
