#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comando `ds`: chat con IA (DeepSeek) manteniendo una sesión por usuario.
Soporte completo para la API OpenAI-compatible de ds-flaskAPI.
Subcomandos: /new, /clear, /help, /reasoner, /chat, /search on/off, /temp N
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, Generator, List, Optional, Tuple, Any

import requests

from core import config
from core.context import CommandContext
from core.registry import command

logger = logging.getLogger("bot.commands.aidus")

HELP_TEXT = (
    "🤖 DeepSeek - Asistente IA\n\n"
    "Uso: ds <mensaje> — pregunta cualquier cosa\n\n"
    "Subcomandos:\n"
    "+ /new — nueva sesión (reinicia el historial)\n"
    "+ /clear — limpiar historial de la sesión actual\n"
    "+ /help — esta ayuda\n"
    "+ /reasoner — alterna modo razonador (deepseek-reasoner)\n"
    "+ /chat — alterna modo chat normal (deepseek-chat)\n"
    "+ /search on|off — activa/desactiva búsqueda web\n"
    "+ /temp N — ajusta temperatura (0-2)\n"
    "+ /status — muestra estado actual de la sesión\n\n"
    "Ejemplos:\n"
    "• ds ¿Cuál es la capital de Francia?\n"
    "• ds Explícame qué es la IA\n"
    "• ds /search on ¿Qué pasó hoy en el mundo?"
)


class DeepSeekClient:
    """Cliente para la API de DeepSeek (OpenAI-compatible)."""

    def __init__(
        self,
        api_url: str = config.DEEPSEEK_API_URL,
        timeout: int = 120,
        model: str = "deepseek-chat",
    ):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.model = model
        self.session_id: Optional[str] = None
        self.parent_message_id: Optional[int] = None
        self.thinking_enabled = False  # deepseek-chat no usa thinking
        self.search_enabled = True
        self.temperature = 0.7
        self.top_p = 0.9
        self.max_tokens = 2000
        self.session_created_at: Optional[datetime] = None
        self.message_count = 0
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        }

    def create_session(self) -> str:
        """Crea una nueva sesión de chat."""
        resp = requests.post(
            f"{self.api_url}/api/session",
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self.session_id = data.get("session_id")
        if not self.session_id:
            raise RuntimeError(f"No se recibió session_id: {data}")
        self.parent_message_id = None
        self.session_created_at = datetime.now()
        self.message_count = 0
        return self.session_id

    def reset_session(self) -> str:
        """Reinicia la sesión actual."""
        self.session_id = None
        self.parent_message_id = None
        return self.create_session()

    def send_message(self, prompt: str) -> Generator[Tuple[str, Any], None, None]:
        """
        Envía un mensaje y devuelve eventos: ('response', texto), ('done', metadata), ('error', mensaje)
        """
        if not self.session_id:
            raise RuntimeError("Primero hay que crear una sesión con create_session().")

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "session_id": self.session_id,
            "parent_message_id": self.parent_message_id,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "search_enabled": self.search_enabled,
            "reasoning_enabled": self.thinking_enabled,
            "stream": False,  # No usamos stream para evitar complejidad
        }

        try:
            resp = requests.post(
                f"{self.api_url}/v1/chat/completions",
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )

            if resp.status_code != 200:
                error_data = resp.json() if resp.text else {}
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                yield ("error", f"HTTP {resp.status_code}: {error_msg}")
                return

            data = resp.json()

            # Extraer respuesta
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            reasoning = message.get("reasoning_content", "")

            # Actualizar IDs para el siguiente mensaje
            self.parent_message_id = data.get("parent_message_id")
            self.message_count += 1

            # Emitir respuesta
            if reasoning:
                yield ("think", reasoning)
            yield ("response", content)

            # Metadata final
            yield ("done", {
                "message_id": self.parent_message_id,
                "usage": data.get("usage", {}),
                "finish_reason": choice.get("finish_reason"),
                "is_incomplete": data.get("is_incomplete", False),
            })

        except requests.Timeout:
            yield ("error", "Tiempo de espera agotado. El servidor tardó demasiado en responder.")
        except requests.RequestException as exc:
            yield ("error", f"Error de red: {exc}")
        except json.JSONDecodeError:
            yield ("error", "Error al procesar la respuesta del servidor (JSON inválido).")
        except Exception as exc:
            logger.exception("Error en send_message")
            yield ("error", f"Error inesperado: {str(exc)[:150]}")

    def toggle_search(self, enabled: Optional[bool] = None) -> bool:
        """Activa/desactiva búsqueda web."""
        if enabled is None:
            self.search_enabled = not self.search_enabled
        else:
            self.search_enabled = enabled
        return self.search_enabled

    def toggle_model(self, model_type: str) -> str:
        """Cambia entre 'chat' y 'reasoner'."""
        if model_type == "reasoner":
            self.model = "deepseek-reasoner"
            self.thinking_enabled = True
        else:
            self.model = "deepseek-chat"
            self.thinking_enabled = False
        return self.model

    def set_temperature(self, temp: float) -> float:
        """Ajusta la temperatura (0-2)."""
        self.temperature = max(0.0, min(2.0, temp))
        return self.temperature

    def get_status(self) -> Dict[str, Any]:
        """Devuelve el estado actual de la sesión."""
        return {
            "session_id": self.session_id,
            "model": self.model,
            "thinking_enabled": self.thinking_enabled,
            "search_enabled": self.search_enabled,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "message_count": self.message_count,
            "created_at": self.session_created_at.isoformat() if self.session_created_at else None,
        }


class SessionManager:
    """Gestiona sesiones por usuario."""

    def __init__(self):
        self.clients: Dict[str, DeepSeekClient] = {}

    def get_or_create(self, user_id: str) -> DeepSeekClient:
        if user_id not in self.clients:
            client = DeepSeekClient()
            client.create_session()
            self.clients[user_id] = client
        return self.clients[user_id]

    def reset(self, user_id: str) -> DeepSeekClient:
        client = self.clients.get(user_id)
        if client:
            client.reset_session()
        else:
            client = DeepSeekClient()
            client.create_session()
            self.clients[user_id] = client
        return client

    def clear(self, user_id: str) -> None:
        """Limpia el historial (reinicia parent_message_id sin perder sesión)."""
        client = self.clients.get(user_id)
        if client:
            client.parent_message_id = None
            client.message_count = 0


_sessions = SessionManager()


def _clean_markdown(text: str) -> str:
    """Limpia texto markdown para mostrarlo en mensajes cortos."""
    if not text:
        return ""
    text = re.sub(r"```[a-zA-Z]*\n.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_for_display(text: str) -> str:
    """Formatea texto para mostrarlo en mensajes."""
    text = _clean_markdown(text)

    # Convertir markdown simple a formato legible
    lines: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("### "):
            lines.append(f"*{line[4:]}*")
        elif line.startswith("## "):
            lines.append(f"**{line[3:]}**")
        elif line.startswith("# "):
            lines.append(f"**{line[2:]}**")
        elif line.startswith("- ") or line.startswith("* "):
            lines.append(f"+ {line[2:]}")
        elif re.match(r"^\d+\.\s+", line):
            lines.append(f"+ {re.sub(r'^\d+\.\s+', '', line)}")
        else:
            lines.append(line)
    return "\n".join(lines)


@command("ds", help="Chatea con la IA de DeepSeek", usage="ds <mensaje>")
def handle_ds(ctx: CommandContext) -> None:
    sub = ctx.args[0].lower() if ctx.args else ""

    # --- Subcomandos ---
    if sub == "/new":
        _sessions.reset(ctx.sender_phone)
        ctx.reply("🆕 Nueva sesión creada. Escribe cualquier mensaje para empezar a chatear.")
        return

    if sub == "/clear":
        _sessions.clear(ctx.sender_phone)
        ctx.reply("🧹 Historial limpiado (la sesión sigue activa).")
        return

    if sub == "/help":
        ctx.reply(HELP_TEXT)
        return

    if sub == "/status":
        try:
            client = _sessions.get_or_create(ctx.sender_phone)
            status = client.get_status()
            lines = [
                "📊 **Estado de la sesión**",
                f"• ID: `{status['session_id'][:8]}...`",
                f"• Modelo: `{status['model']}`",
                f"• Búsqueda web: {'✅' if status['search_enabled'] else '❌'}",
                f"• Temperatura: {status['temperature']}",
                f"• Mensajes: {status['message_count']}",
                f"• Creada: {status['created_at'] or 'N/A'}",
            ]
            ctx.reply("\n".join(lines))
        except Exception as e:
            ctx.reply_error(f"Error obteniendo estado: {str(e)[:100]}")
        return

    if sub == "/reasoner":
        try:
            client = _sessions.get_or_create(ctx.sender_phone)
            model = client.toggle_model("reasoner")
            ctx.reply(f"🧠 Cambiado a modo **razonador** ({model})")
        except Exception as e:
            ctx.reply_error(f"Error cambiando modelo: {str(e)[:100]}")
        return

    if sub == "/chat":
        try:
            client = _sessions.get_or_create(ctx.sender_phone)
            model = client.toggle_model("chat")
            ctx.reply(f"💬 Cambiado a modo **chat normal** ({model})")
        except Exception as e:
            ctx.reply_error(f"Error cambiando modelo: {str(e)[:100]}")
        return

    if sub == "/search":
        try:
            client = _sessions.get_or_create(ctx.sender_phone)
            rest = ctx.args[1].lower() if len(ctx.args) > 1 else ""
            if rest == "on":
                client.toggle_search(True)
                ctx.reply("🔍 Búsqueda web **activada**")
            elif rest == "off":
                client.toggle_search(False)
                ctx.reply("🔍 Búsqueda web **desactivada**")
            else:
                current = client.toggle_search(None)
                ctx.reply(f"🔍 Búsqueda web: **{'activada' if current else 'desactivada'}**")
        except Exception as e:
            ctx.reply_error(f"Error cambiando búsqueda: {str(e)[:100]}")
        return

    if sub.startswith("/temp"):
        try:
            client = _sessions.get_or_create(ctx.sender_phone)
            if len(ctx.args) > 1:
                temp = float(ctx.args[1])
                client.set_temperature(temp)
                ctx.reply(f"🌡️ Temperatura ajustada a **{client.temperature}**")
            else:
                ctx.reply(f"🌡️ Temperatura actual: **{client.temperature}**")
        except ValueError:
            ctx.reply_error("La temperatura debe ser un número entre 0 y 2.")
        except Exception as e:
            ctx.reply_error(f"Error ajustando temperatura: {str(e)[:100]}")
        return

    if sub.startswith("/"):
        ctx.reply_error(f"Subcomando no reconocido: `{sub}`. Usa `ds /help` para ver las opciones.")
        return

    # --- Mensaje normal ---
    prompt = ctx.raw_args
    if not prompt:
        ctx.reply(HELP_TEXT)
        return

    try:
        ds_client = _sessions.get_or_create(ctx.sender_phone)
    except Exception:
        logger.exception("Error creando sesión de DeepSeek para %s", ctx.sender_phone)
        ctx.reply_error("No se pudo crear la sesión de IA. Intenta de nuevo en unos segundos.")
        return

    # Mensaje inicial "Generando..."
    msg_id = ctx.reply("🤔 Generando respuesta...")

    full_response = ""
    full_think = ""
    has_think = False
    last_update = time.time()
    last_response_len = 0
    update_interval = 0.5  # segundos entre actualizaciones

    def render(final: bool = False) -> str:
        parts = []
        if has_think and full_think:
            think_display = full_think if final else (full_think[:200] + ("..." if len(full_think) > 200 else ""))
            parts.append(f"🧠 Pensamiento:\n> {_clean_markdown(think_display)}\n")
        label = "💬 Respuesta:" if final else "💬 Respondiendo:"
        parts.append(f"{label}\n\n{_format_for_display(full_response)}")
        if not final:
            parts.append("\n\n⏳ Generando...")
        text = "\n".join(parts)
        # Límite de caracteres para mensajes de Telegram (4000 aprox)
        return text[:3990] + ("..." if len(text) > 3990 else "")

    try:
        for event_type, content in ds_client.send_message(prompt):
            if event_type == "think":
                full_think += str(content)
                has_think = True
                # Actualizar cada cierto tiempo o si se acumuló suficiente texto
                if (len(full_think) - last_response_len >= 50 or time.time() - last_update >= update_interval):
                    ctx.edit(render(), msg_id)
                    last_update = time.time()
                    last_response_len = len(full_think)

            elif event_type == "response":
                full_response += str(content)
                # Actualizar cada cierto tiempo o si se acumuló suficiente texto
                if (len(full_response) - last_response_len >= 50 or time.time() - last_update >= update_interval):
                    ctx.edit(render(), msg_id)
                    last_update = time.time()
                    last_response_len = len(full_response)

            elif event_type == "done":
                # Actualización final
                ctx.edit(render(final=True), msg_id)
                return

            elif event_type == "error":
                ctx.edit(f"❌ Error: {content}\n\nUsa `ds /new` para reiniciar la sesión.", msg_id)
                return

        # Si no hubo respuesta (caso raro)
        if not full_response:
            ctx.edit("❌ No se recibió respuesta del servidor. Intenta de nuevo.", msg_id)

    except Exception as exc:
        logger.exception("Error en el comando ds para %s", ctx.sender_phone)
        ctx.edit(f"❌ Error inesperado: {str(exc)[:150]}\n\nUsa `ds /new` para reiniciar la sesión.", msg_id)


@command("dshelp", hidden=True, help="Ayuda del comando ds")
def handle_ds_help(ctx: CommandContext) -> None:
    ctx.reply(HELP_TEXT)
