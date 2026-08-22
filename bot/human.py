"""
Comportamientos humano-realistas:

- Mostrar "escribiendo..." (chat_state composing) antes de responder
- Stream-edit: mandar 1er mensaje y editarlo progresivamente
  a medida que la IA genera tokens (efecto "escribiendo en vivo")
- Pausa minima antes de responder
- Long messages: partir en multiples mensajes si > 4000 chars

Esto hace que el bot parezca un usuario real escribiendo.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

from .config import settings

log = logging.getLogger(__name__)

# Limite de caracteres por mensaje en toDus
MAX_MSG_LEN = 4000
# Caracteres minimos antes de hacer el primer edit
MIN_FIRST_EDIT = 60


class HumanBehavior:
    def __init__(self, send_message_fn: Callable[[str, str], str],
                 edit_message_fn: Callable[[str, str, str], str],
                 send_chat_state_fn: Callable[[str, str], None]):
        """
        send_message_fn(to, body) -> msg_id
        edit_message_fn(to, new_body, original_msg_id) -> msg_id
        send_chat_state_fn(to, state) -> None    state: 'composing'|'paused'
        """
        self._send = send_message_fn
        self._edit = edit_message_fn
        self._chat_state = send_chat_state_fn

    # ---------- Helpers bajo nivel ----------

    def _set_typing(self, to: str, on: bool) -> None:
        if not settings.human_typing:
            return
        try:
            self._chat_state(to, "composing" if on else "paused")
        except Exception as e:
            log.debug("chat_state failed: %s", e)

    @staticmethod
    def _normalize(text: str) -> str:
        """Limpia formato markdown basico que toDus no renderiza."""
        # Quitar **bold**, __italic__, *italic*, `code`
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _split_long(text: str, limit: int = MAX_MSG_LEN) -> list[str]:
        """Parte texto largo en chunks respetando lineas cuando sea posible."""
        if len(text) <= limit:
            return [text]
        chunks = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > limit:
                if current:
                    chunks.append(current.rstrip())
                current = ""
                # si la linea sola supera el limite, partir bruto
                while len(line) > limit:
                    chunks.append(line[:limit])
                    line = line[limit:]
            current += line + "\n"
        if current.strip():
            chunks.append(current.rstrip())
        return chunks

    # ---------- API publica ----------

    def reply_simple(self, to: str, text: str) -> str:
        """Reply sin streaming: typing delay + 1 mensaje."""
        text = self._normalize(text)
        # delay minimo
        if settings.human_min_delay > 0:
            time.sleep(settings.human_min_delay)
        self._set_typing(to, True)
        # delay proporcional (max 3s)
        delay = min(3.0, max(0.4, len(text) / 220.0))
        time.sleep(delay)
        self._set_typing(to, False)

        chunks = self._split_long(text)
        last_id = ""
        for i, chunk in enumerate(chunks):
            last_id = self._send(to, chunk)
        return last_id

    def reply_stream(
        self,
        to: str,
        stream_gen,
        placeholder: str = "…",
    ) -> str:
        """
        Reply con streaming: manda 1er mensaje placeholder y lo va editando
        a medida que llegan tokens.

        stream_gen: iterador que yield strings (fragmentos)
        Retorna el msg_id final del mensaje.
        """
        if not settings.human_stream_edit:
            # Sin stream: coleccionar todo y mandar simple
            full = "".join(stream_gen)
            return self.reply_simple(to, full)

        # delay minimo antes de arrancar
        if settings.human_min_delay > 0:
            time.sleep(settings.human_min_delay)

        self._set_typing(to, True)

        # mandar primer mensaje placeholder
        try:
            msg_id = self._send(to, placeholder)
        except Exception as e:
            log.error("No se pudo mandar placeholder: %s", e)
            self._set_typing(to, False)
            return ""

        accumulated = ""
        last_edit_len = 0
        last_edit_time = time.time()
        edit_interval_chars = settings.human_edit_interval
        edit_interval_time = 1.2  # segundos

        try:
            for piece in stream_gen:
                accumulated += piece
                # editar si: hay suficiente nuevo contenido O paso suficiente tiempo
                should_edit = (
                    len(accumulated) - last_edit_len >= edit_interval_chars
                    or (time.time() - last_edit_time >= edit_interval_time and len(accumulated) > MIN_FIRST_EDIT)
                )
                if should_edit:
                    try:
                        self._edit(to, self._normalize(accumulated), msg_id)
                        last_edit_len = len(accumulated)
                        last_edit_time = time.time()
                    except Exception as e:
                        log.debug("edit fallido (intermedio): %s", e)
        except Exception as e:
            log.error("stream falló: %s", e)
            accumulated += "\n\n[error generando respuesta]"

        # Si la IA no genero nada, dejar un fallback
        if not accumulated.strip():
            accumulated = "(sin respuesta)"

        # Edicion final con el texto completo (normalizado y partido si hace falta)
        self._set_typing(to, False)
        final_text = self._normalize(accumulated)
        chunks = self._split_long(final_text)

        if len(chunks) == 1:
            try:
                self._edit(to, chunks[0], msg_id)
            except Exception as e:
                log.warning("edit final fallido: %s", e)
            return msg_id
        else:
            # Primer chunk: editar el placeholder
            try:
                self._edit(to, chunks[0], msg_id)
            except Exception as e:
                log.warning("edit final 1 fallido: %s", e)
            # Resto: nuevos mensajes
            for chunk in chunks[1:]:
                try:
                    self._send(to, chunk)
                except Exception as e:
                    log.error("send chunk fallido: %s", e)
            return msg_id
