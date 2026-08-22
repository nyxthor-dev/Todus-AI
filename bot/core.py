"""
Nucleo del bot.

Conecta toDus SDK + IA + memoria + rate limiter + comportamiento humano.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from todus import ToDusClient2
from todus.errors import (
    AuthenticationError,
    ConnectionLostError,
    TokenExpiredError,
)

from .ai_client import AIClient
from .commands import CommandContext, CommandRegistry
from .config import settings
from .human import HumanBehavior
from .memory import Memory
from .rate_limiter import RateLimiter

log = logging.getLogger(__name__)


def _extract_phone(jid_or_phone: str) -> str:
    """Convierte '5312345678@im.todus.cu' o '5312345678' a '5312345678'."""
    if not jid_or_phone:
        return ""
    s = str(jid_or_phone).strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    return s


def _is_group_jid(jid: str) -> bool:
    """Los grupos tienen JID tipo 'xxxxx@muclight.im.todus.cu' o similar."""
    if not jid:
        return False
    return "@muclight." in jid or "@muc." in jid or "@conference." in jid


class NyxBot:
    def __init__(self):
        # Validar config
        errs = settings.validate()
        if errs:
            raise RuntimeError("Config incompleta: " + ", ".join(errs))

        # Componentes
        self.memory = Memory()
        self.rate_limiter = RateLimiter(
            owner_phone=settings.owner_phone,
            limit_private=settings.limit_private,
            limit_group=settings.limit_group,
        )
        self.ai = AIClient()
        self.commands = CommandRegistry(
            memory=self.memory,
            rate_limiter=self.rate_limiter,
            ai_model=settings.ai_model,
        )

        # Cliente toDus
        self.client = ToDusClient2(
            phone_number=settings.todus_phone,
            password=settings.todus_password,
        )

        # Comportamiento humano - se conecta despues del login
        self.human: Optional[HumanBehavior] = None

        # Stop general
        self._stop_main = threading.Event()
        self._stop_presence = threading.Event()
        self._presence_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # LOGIN / STARTUP
    # ------------------------------------------------------------------

    def _login(self) -> None:
        log.info("Logueando en toDus como %s ...", settings.todus_phone)
        for attempt in range(1, 4):
            try:
                self.client.login()
                log.info("Login OK. Token obtenido.")
                # Conectar comportamiento humano a los metodos del cliente
                self.human = HumanBehavior(
                    send_message_fn=self._safe_send,
                    edit_message_fn=self._safe_edit,
                    send_chat_state_fn=self._safe_chat_state,
                )
                return
            except AuthenticationError as e:
                log.error("Auth error: %s", e)
                raise
            except Exception as e:
                log.warning("Login intento %d fallido: %s", attempt, e)
                time.sleep(5 * attempt)
        raise RuntimeError("No se pudo loguear tras 3 intentos")

    def _setup_profile(self) -> None:
        """Configura perfil del bot para parecer usuario real."""
        try:
            self.client.update_profile(alias="NyxBot", bio="Asistente con IA")
            log.info("Perfil actualizado")
        except Exception as e:
            log.warning("No se pudo actualizar perfil: %s", e)

    # ------------------------------------------------------------------
    # PRESENCIA (punto verde "en linea")
    # ------------------------------------------------------------------

    def _presence_worker(self) -> None:
        """
        Vigila que la sesion siga activa y re-loguea si hace falta.
        El keepalive del SDK mantiene la presencia XMPP automaticamente.
        """
        while not self._stop_presence.wait(30):
            try:
                if not getattr(self.client, "logged", False):
                    log.warning("Sesion no logueada, re-login")
                    self._login()
            except Exception as e:
                log.debug("presence worker: %s", e)

    # ------------------------------------------------------------------
    # WRAPPERS DE ENVIO CON RE-AUTH
    # ------------------------------------------------------------------

    def _safe_send(self, to: str, body: str) -> str:
        try:
            return self.client.send_message(to, body)
        except TokenExpiredError:
            log.warning("Token expirado al enviar, re-login")
            self._login()
            return self.client.send_message(to, body)

    def _safe_edit(self, to: str, body: str, mid: str) -> str:
        try:
            return self.client.edit_message(to, body, mid)
        except TokenExpiredError:
            log.warning("Token expirado al editar, re-login")
            self._login()
            return self.client.edit_message(to, body, mid)

    def _safe_chat_state(self, to: str, state: str) -> None:
        try:
            self.client.send_chat_state(to, state)
        except TokenExpiredError:
            self._login()
            try:
                self.client.send_chat_state(to, state)
            except Exception:
                pass
        except Exception as e:
            log.debug("chat_state err: %s", e)

    # ------------------------------------------------------------------
    # MANEJO DE MENSAJES
    # ------------------------------------------------------------------

    def _on_message(self, msg: dict) -> None:
        try:
            self._handle_message(msg)
        except Exception:
            log.exception("Error manejando mensaje")

    def _handle_message(self, msg: dict) -> None:
        # Solo mensajes con body de texto
        body = (msg.get("body") or "").strip()
        if not body:
            return

        from_jid = msg.get("from", "") or ""
        if not from_jid:
            return

        # Determinar grupo vs privado
        is_group = bool(msg.get("is_group")) or _is_group_jid(from_jid)

        # En grupo, from_jid es el JID del grupo; el usuario real viene en 'from_user'
        if is_group:
            sender_phone = _extract_phone(msg.get("from_user") or "")
            group_id = from_jid
            reply_to = from_jid
        else:
            sender_phone = _extract_phone(from_jid)
            group_id = None
            reply_to = sender_phone

        if not sender_phone:
            log.debug("No pude determinar sender_phone: %s", msg)
            return

        # Ignorar mensajes del propio bot
        if sender_phone == settings.todus_phone:
            return

        # Registrar actividad
        self.memory.touch_user(sender_phone)

        # Enviar "visto" (solo en privado)
        if not is_group:
            msg_id = msg.get("id", "")
            if msg_id:
                try:
                    self.client.send_read_receipt(sender_phone, msg_id)
                except Exception as e:
                    log.debug("read_receipt err: %s", e)

        is_owner = (sender_phone == settings.owner_phone)

        ctx = CommandContext(
            sender_phone=sender_phone,
            is_group=is_group,
            group_id=group_id,
            raw_body=body,
            reply_to=reply_to,
            is_owner=is_owner,
        )

        log.info(
            "MSG de %s (owner=%s group=%s): %s",
            sender_phone, is_owner, is_group, body[:80],
        )

        # 1) Intentar como comando
        cmd_result = self.commands.try_handle(ctx)
        if cmd_result is not None:
            # Era un comando
            if cmd_result.text is None:
                # /chat <prompt>: extraer prompt y seguir como IA
                parts = body.split(None, 1)
                prompt = parts[1] if len(parts) > 1 else ""
                if not prompt:
                    self._safe_send(reply_to, "Uso: /chat <tu pregunta>")
                    return
                body = prompt
                # Continuar al flujo de IA
            else:
                # Respuesta directa de comando
                if cmd_result.text.startswith("BROADCAST:"):
                    msg_text = cmd_result.text[len("BROADCAST:"):]
                    self._do_broadcast(msg_text)
                    return
                self.human.reply_simple(reply_to, cmd_result.text)
                return

        # 2) Flujo de IA
        # Reglas de acceso:
        #   - Owner: siempre, ilimitado (privado y grupo)
        #   - Grupo no-owner: limite LIMIT_GROUP/min
        #   - Privado no-owner: limite LIMIT_PRIVATE/min
        if is_group:
            if not self.rate_limiter.allow_group(sender_phone):
                self._safe_send(
                    reply_to,
                    f"Ya pediste mucho por ahora. Limite: "
                    f"{settings.limit_group}/min. Intenta en un rato.",
                )
                return
        else:
            if not self.rate_limiter.allow_private(sender_phone):
                self._safe_send(
                    reply_to,
                    f"Ya pediste mucho por ahora. Limite: "
                    f"{settings.limit_private}/min. Intenta en un rato.",
                )
                return

        # En grupo, no-owner: solo responder si menciona al bot o es pregunta
        if is_group and not is_owner:
            mention = re.compile(
                r"@?" + re.escape(settings.todus_phone), re.IGNORECASE
            )
            if not mention.search(body) and not body.endswith("?"):
                # Probablemente no es para nosotros
                log.debug("Ignorando en grupo (no mencio'n ni pregunta): %s", body[:50])
                return

        # Procesar con IA
        self._process_ai(ctx, body)

    # ------------------------------------------------------------------
    # LLAMADA A LA IA
    # ------------------------------------------------------------------

    def _process_ai(self, ctx: CommandContext, prompt: str) -> None:
        """Llama a la IA con contexto del usuario y responde con streaming."""
        if ctx.is_group:
            session = Memory.session_id_for_group(ctx.group_id, ctx.sender_phone)
        else:
            session = Memory.session_id_for_private(ctx.sender_phone)

        # Guardar pregunta del usuario en memoria
        self.memory.add_message(session, "user", prompt)

        # Construir messages
        history = self.memory.get_history(session, limit=settings.memory_max_messages)
        messages = [{"role": "system", "content": settings.system_prompt}] + history

        log.info("IA call: %s (msgs=%d)", ctx.sender_phone, len(messages))

        # Capturar el stream para guardarlo en memoria despues
        captured: list[str] = []

        def tee(gen):
            for piece in gen:
                captured.append(piece)
                yield piece

        try:
            stream = self.ai.chat_stream(messages)
            self.human.reply_stream(ctx.reply_to, tee(stream))
        except Exception as e:
            log.exception("Error en IA")
            self._safe_send(
                ctx.reply_to,
                f"No pude procesar eso ahora. Error: {str(e)[:200]}",
            )
            return

        # Guardar respuesta final en memoria
        full_response = "".join(captured).strip()
        if full_response:
            self.memory.add_message(session, "assistant", full_response)

        # Trim para no crecer infinito
        self.memory.trim_session(session)

    # ------------------------------------------------------------------
    # BROADCAST (owner only)
    # ------------------------------------------------------------------

    def _do_broadcast(self, message: str) -> None:
        try:
            import sqlite3
            with sqlite3.connect(str(settings.memory_db_path)) as conn:
                cur = conn.execute("SELECT phone FROM user_meta")
                phones = [r[0] for r in cur.fetchall()]
        except Exception as e:
            log.error("broadcast: %s", e)
            return

        log.info("Broadcast a %d usuarios", len(phones))
        sent = 0
        for phone in phones:
            if phone == settings.owner_phone:
                continue
            try:
                self._safe_send(phone, message)
                sent += 1
                time.sleep(1.0)
            except Exception as e:
                log.warning("broadcast a %s fallo: %s", phone, e)
        log.info("Broadcast enviado a %d/%d", sent, len(phones))

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Bucle principal. Bloqueante."""
        self._login()
        self._setup_profile()

        # Presence worker
        self._presence_thread = threading.Thread(
            target=self._presence_worker, daemon=True
        )
        self._presence_thread.start()

        log.info("Bot iniciado. Escuchando mensajes... (Ctrl+C para detener)")

        while not self._stop_main.is_set():
            try:
                # IMPORTANTE: listen_messages requiere token como primer arg
                self.client.listen_messages(self.client.token, self._on_message)
            except TokenExpiredError:
                log.warning("Token expirado, re-login")
                self._login()
                continue
            except ConnectionLostError as e:
                log.warning("Conexion perdida: %s. Reintentando en 5s", e)
                time.sleep(5)
                continue
            except KeyboardInterrupt:
                log.info("Interrumpido por teclado")
                break
            except Exception:
                log.exception("Error inesperado en listen_messages, retry en 10s")
                time.sleep(10)

        log.info("Bot detenido")

    def stop(self) -> None:
        self._stop_main.set()
        self._stop_presence.set()
