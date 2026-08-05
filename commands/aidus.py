#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando `ds`: chat con IA (AIDUS / DeepSeek) manteniendo una sesión
por usuario. Subcomandos: /new, /clear, /help.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, Generator, List, Optional, Tuple

import requests

from core import config
from core.context import CommandContext
from core.registry import command

logger = logging.getLogger("bot.commands.aidus")

HELP_TEXT = (
    "🤖 AIDUS - Asistente IA\n\n"
    "Uso: ds <mensaje> — pregunta cualquier cosa\n\n"
    "Subcomandos:\n"
    "+ /new — nueva sesión\n"
    "+ /clear — limpiar historial\n"
    "+ /help — esta ayuda\n\n"
    "Siempre activos: pensamiento profundo y búsqueda web.\n\n"
    "Ejemplos:\n"
    "• ds ¿Cuál es la capital de Francia?\n"
    "• ds Explícame qué es la IA"
)


class DeepSeekClient:
    def __init__(self, api_url: str = config.DEEPSEEK_API_URL, timeout: int = 120):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self.thinking_enabled = True
        self.search_enabled = True
        self.session_created_at: Optional[datetime] = None

    def create_session(self) -> str:
        resp = requests.post(f"{self.api_url}/api/session", timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        self.session_id = data.get("session_id")
        if not self.session_id:
            raise RuntimeError(f"No se recibió session_id: {data}")
        self.session_created_at = datetime.now()
        return self.session_id

    def reset_session(self) -> str:
        self.session_id = None
        return self.create_session()

    def send_message(self, prompt: str) -> Generator[Tuple[str, str, Optional[int]], None, None]:
        if not self.session_id:
            raise RuntimeError("Primero hay que crear una sesión con create_session().")

        payload = {
            "session_id": self.session_id,
            "prompt": prompt,
            "thinking_enabled": self.thinking_enabled,
            "search_enabled": self.search_enabled,
        }

        try:
            with requests.post(f"{self.api_url}/api/chat", json=payload, stream=True, timeout=self.timeout) as r:
                if r.status_code != 200:
                    yield ("error", f"HTTP {r.status_code}: {r.text[:200]}", None)
                    return

                event_type = None
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                        continue
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:].strip()
                    if not data_str or data_str in ('""', '"'):
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        data = data_str

                    if event_type == "think":
                        text = re.sub(r"\s*FINISHED\s*", "", str(data), flags=re.IGNORECASE)
                        yield ("think", text, None)
                    elif event_type == "response":
                        text = re.sub(r"\s*FINISHED\s*", "", str(data), flags=re.IGNORECASE)
                        yield ("response", text, None)
                    elif event_type == "done":
                        yield ("done", None, data)
                        return
                    elif event_type == "error":
                        yield ("error", str(data), None)
                        return

        except requests.Timeout:
            yield ("error", "Tiempo de espera agotado.", None)
        except requests.RequestException as exc:
            yield ("error", f"Error de red: {exc}", None)


class SessionManager:
    def __init__(self):
        self.clients: Dict[str, DeepSeekClient] = {}
        self.message_counts: Dict[str, int] = {}

    def get_or_create(self, user_id: str) -> DeepSeekClient:
        if user_id not in self.clients:
            client = DeepSeekClient()
            client.create_session()
            self.clients[user_id] = client
            self.message_counts[user_id] = 0
        return self.clients[user_id]

    def reset(self, user_id: str) -> DeepSeekClient:
        client = self.clients.get(user_id)
        if client:
            client.reset_session()
        else:
            client = DeepSeekClient()
            client.create_session()
            self.clients[user_id] = client
        self.message_counts[user_id] = 0
        return client


_sessions = SessionManager()


def _clean_markdown(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s*FINISHED\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```[a-zA-Z]*\n.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_for_todus(text: str) -> str:
    text = _clean_markdown(text)
    text = re.sub(r"^\s*[\*\-]\s+", "+ ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "+ ", text, flags=re.MULTILINE)

    lines: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("### "):
            lines.append(f"*{line[4:]}*")
        elif line.startswith("## "):
            lines.append(f"**{line[3:]}**")
        elif line.startswith("# "):
            lines.append(f"**{line[2:]}**")
        else:
            lines.append(line)
    return "\n".join(lines)


@command("ds", help="Chatea con la IA de AIDUS", usage="ds <mensaje>")
def handle_ds(ctx: CommandContext) -> None:
    sub = ctx.args[0].lower() if ctx.args else ""

    if sub == "/new":
        _sessions.reset(ctx.sender_phone)
        ctx.reply("🆕 Nueva sesión creada. Escribe cualquier mensaje para empezar a chatear.")
        return

    if sub == "/clear":
        ctx.reply("🧹 Historial limpiado (la sesión sigue activa).")
        return

    if sub == "/help":
        ctx.reply(HELP_TEXT)
        return

    if sub.startswith("/"):
        ctx.reply_error("Subcomando no reconocido. Usa ds /help para ver las opciones.")
        return

    prompt = ctx.raw_args
    if not prompt:
        ctx.reply(HELP_TEXT)
        return

    try:
        ds_client = _sessions.get_or_create(ctx.sender_phone)
    except Exception:
        logger.exception("Error creando sesión de AIDUS para %s", ctx.sender_phone)
        ctx.reply_error("No se pudo crear la sesión de IA. Intenta de nuevo en unos segundos.")
        return

    msg_id = ctx.reply("🤔 Pensando...")

    full_think = ""
    full_response = ""
    has_think = False
    last_edit = time.time()
    last_response_len = 0
    last_think_len = 0

    def render(final: bool = False) -> str:
        parts = []
        if has_think and full_think:
            think_display = full_think if final else (full_think[:300] + ("..." if len(full_think) > 300 else ""))
            parts.append(f"🧠 {'Pensamiento' if final else 'Pensando...'}\n> {_clean_markdown(think_display)}\n")
        label = "💬 Respuesta:" if final else "💬 Respondiendo:"
        parts.append(f"{label}\n\n{_format_for_todus(full_response)}")
        if not final:
            parts.append("\n\n⏳ Generando...")
        text = "\n".join(parts)
        return text[:3997] + "..." if len(text) > 4000 else text

    try:
        for event_type, content, _done_id in ds_client.send_message(prompt):
            if event_type == "think":
                full_think += content
                has_think = True
                if len(full_think) - last_think_len >= 30 or time.time() - last_edit >= 1.0:
                    ctx.edit(render(), msg_id)
                    last_edit = time.time()
                    last_think_len = len(full_think)

            elif event_type == "response":
                full_response += content
                if len(full_response) - last_response_len >= 30 or time.time() - last_edit >= 1.0:
                    ctx.edit(render(), msg_id)
                    last_edit = time.time()
                    last_response_len = len(full_response)

            elif event_type == "done":
                ctx.edit(render(final=True), msg_id)
                _sessions.message_counts[ctx.sender_phone] = _sessions.message_counts.get(ctx.sender_phone, 0) + 1
                return

            elif event_type == "error":
                ctx.reply_error(f"Error en AIDUS: {content}\nUsa ds /new para reiniciar la sesión.")
                return

    except Exception as exc:
        logger.exception("Error en el comando ds para %s", ctx.sender_phone)
        ctx.reply_error(f"Error inesperado: {str(exc)[:150]}\nUsa ds /new para reiniciar la sesión.")


@command("dshelp", hidden=True, help="Ayuda del comando ds")
def handle_ds_help(ctx: CommandContext) -> None:
    ctx.reply(HELP_TEXT)
