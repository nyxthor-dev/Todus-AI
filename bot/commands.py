"""
Comandos del bot. Todos empiezan con '/'.

Comandos implementados:
  /chat <texto>     - habla con la IA (tambien vale escribir sin /chat en privado)
  /reset            - borra tu historial de conversacion
  /help             - muestra esta ayuda
  /ping             - prueba de vida
  /id               - tu numero de toDus
  /model            - modelo de IA activo
  /stats            - (solo owner) estadisticas de uso
  /broadcast <msg>  - (solo owner) envia mensaje a todos los usuarios conocidos
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from .config import settings
from .memory import Memory
from .rate_limiter import RateLimiter

log = logging.getLogger(__name__)


@dataclass
class CommandContext:
    sender_phone: str           # telefono del que mando el comando (sin @im.todus.cu)
    is_group: bool
    group_id: str | None        # si is_group
    raw_body: str               # texto completo recibido
    reply_to: str               # jid al que responder (privado o grupo)
    is_owner: bool


@dataclass
class CommandResult:
    text: str | None = None       # texto a responder (None = no responder)
    is_error: bool = False


class CommandRegistry:
    def __init__(self, memory: Memory, rate_limiter: RateLimiter, ai_model: str):
        self.memory = memory
        self.rate_limiter = rate_limiter
        self.ai_model = ai_model
        self._handlers: dict[str, Callable[[CommandContext, list[str]], CommandResult]] = {}
        self._register_defaults()

    # ----- Registro -----

    def register(self, name: str, fn: Callable[[CommandContext, list[str]], CommandResult]) -> None:
        self._handlers[name.lower()] = fn

    def _register_defaults(self) -> None:
        self.register("help", self._cmd_help)
        self.register("start", self._cmd_help)
        self.register("ping", self._cmd_ping)
        self.register("id", self._cmd_id)
        self.register("model", self._cmd_model)
        self.register("reset", self._cmd_reset)
        self.register("clear", self._cmd_reset)
        self.register("stats", self._cmd_stats)
        self.register("broadcast", self._cmd_broadcast)
        self.register("chat", self._cmd_chat)
        self.register("ai", self._cmd_chat)   # alias
        self.register("ask", self._cmd_chat)  # alias

    # ----- Despacho -----

    def try_handle(self, ctx: CommandContext) -> CommandResult | None:
        """
        Si el body empieza con '/', intenta ejecutar el comando.
        Retorna CommandResult, o None si no era un comando.
        """
        body = ctx.raw_body.strip()
        if not body.startswith("/"):
            return None
        parts = body[1:].split()
        if not parts:
            return CommandResult(text="?", is_error=True)
        cmd = parts[0].lower()
        args = parts[1:]
        handler = self._handlers.get(cmd)
        if handler is None:
            return CommandResult(
                text=f"Comando desconocido: /{cmd}\nMandame /help para ver que puedo hacer.",
                is_error=True,
            )
        try:
            return handler(ctx, args)
        except Exception as e:
            log.exception("Error ejecutando /%s", cmd)
            return CommandResult(text=f"Error ejecutando /{cmd}: {e}", is_error=True)

    # ----- Comandos default -----

    def _cmd_help(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        owner_extra = (
            "\n\n— Owner only —\n"
            "/stats            - estadisticas\n"
            "/broadcast <msg>  - mensaje masivo"
        ) if ctx.is_owner else ""
        text = (
            "NyxBot - comandos disponibles\n"
            "────────────────────────\n"
            "/chat <texto>     - hablar con la IA\n"
            "  (en privado podes escribir directo, sin /chat)\n"
            "/reset            - borrar tu historial\n"
            "/ping             - prueba de vida\n"
            "/id               - tu numero\n"
            "/model            - modelo de IA en uso"
            f"{owner_extra}\n"
            "────────────────────────\n"
            f"Limites: {settings.limit_private}/min privado, {settings.limit_group}/min grupo\n"
            "Owner: ilimitado"
        )
        return CommandResult(text=text)

    def _cmd_ping(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        return CommandResult(text="pong")

    def _cmd_id(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        return CommandResult(text=f"Tu numero: {ctx.sender_phone}")

    def _cmd_model(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        return CommandResult(text=f"Modelo IA: {self.ai_model}")

    def _cmd_reset(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        if ctx.is_group:
            session = Memory.session_id_for_group(ctx.group_id, ctx.sender_phone)
        else:
            session = Memory.session_id_for_private(ctx.sender_phone)
        n = self.memory.reset_session(session)
        return CommandResult(text=f"Listo, borre {n} mensajes de tu historial.")

    def _cmd_chat(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        # /chat <prompt> -> delega al flujo normal de IA
        if not args:
            return CommandResult(text="Uso: /chat <tu pregunta>", is_error=True)
        prompt = " ".join(args)
        # Marcar para que el handler principal lo procese como IA
        return CommandResult(text=None)  # None = no responder aca, dejar que fluya a IA

    def _cmd_stats(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        if not ctx.is_owner:
            return CommandResult(text="Solo el owner.", is_error=True)
        # Stats simples: total mensajes en memoria
        try:
            import sqlite3
            with sqlite3.connect(str(settings.memory_db_path)) as conn:
                cur = conn.execute("SELECT COUNT(*) FROM messages")
                total = cur.fetchone()[0]
                cur = conn.execute("SELECT COUNT(*) FROM user_meta")
                users = cur.fetchone()[0]
            return CommandResult(text=f"Stats:\n- {total} mensajes en memoria\n- {users} usuarios conocidos")
        except Exception as e:
            return CommandResult(text=f"Error stats: {e}", is_error=True)

    def _cmd_broadcast(self, ctx: CommandContext, args: list[str]) -> CommandResult:
        if not ctx.is_owner:
            return CommandResult(text="Solo el owner.", is_error=True)
        if not args:
            return CommandResult(text="Uso: /broadcast <mensaje>", is_error=True)
        # Solo confirmamos, el envio real lo hace el core via callback
        return CommandResult(text="BROADCAST:" + " ".join(args))
