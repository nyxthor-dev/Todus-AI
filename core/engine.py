#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Motor del bot: arma el cliente ToDus, carga los comandos automáticamente
y arranca el bucle de escucha de mensajes.
"""

from __future__ import annotations

import logging

from todus import ToDusClient2, util
from todus.errors import AuthenticationError, ConnectionLostError

from . import config
from .dispatcher import Dispatcher
from .logging_setup import console_status
from .registry import load_commands, registry

logger = logging.getLogger("bot.engine")


class BotEngine:
    def __init__(self):
        if not config.PHONE_NUMBER or not config.PASSWORD:
            raise RuntimeError(
                "PHONE_NUMBER y PASSWORD deben estar configurados (variables de entorno o .env)."
            )

        self.client = ToDusClient2(
            phone_number=config.PHONE_NUMBER,
            password=config.PASSWORD,
            verify_ssl=False,
        )
        self.bot_jid = util.build_jid(config.PHONE_NUMBER)
        self.dispatcher = Dispatcher(self.client, self.bot_jid)
        self._running = False

    # ------------------------------------------------------------------
    def load_commands(self) -> int:
        count = load_commands("commands")
        return count

    # ------------------------------------------------------------------
    def _print_startup_banner(self, loaded_count: int) -> None:
        prefixes = ", ".join(config.PREFIXES)
        console_status("=" * 56)
        console_status(" Bot ToDus iniciado")
        console_status("=" * 56)
        console_status(f" Teléfono:        {config.PHONE_NUMBER}")
        console_status(f" Prefijos activos: {prefixes}"
                        + (" (+ sin prefijo)" if config.ALLOW_NO_PREFIX else ""))
        console_status(f" Comandos cargados: {len(registry)} (de {loaded_count} archivos en commands/)")
        if len(registry):
            nombres = ", ".join(sorted(c.name for c in registry.all() if not c.hidden))
            console_status(f" Disponibles:      {nombres}")
        console_status(f" Anti-spam:        cooldown={config.ANTISPAM_COOLDOWN_SECONDS}s, "
                        f"cache={config.ANTISPAM_MAX_CACHE}")
        console_status(f" Log de detalle:   {config.LOG_FILE}")
        console_status("=" * 56)
        console_status(" La consola solo muestra advertencias y errores.")
        console_status(" Revisa el archivo de log para el detalle de actividad.")
        console_status("=" * 56)

    # ------------------------------------------------------------------
    def run(self) -> None:
        loaded_count = self.load_commands()
        self._print_startup_banner(loaded_count)

        self.client.events.on("message")(lambda event: self.dispatcher.handle(event))

        try:
            logger.info("Iniciando sesión de ToDus...")
            self.client.login()
            logger.info("Sesión iniciada correctamente para %s", config.PHONE_NUMBER)
            self._running = True
            self.client.listen_messages(self.client.token, lambda msg: None)

        except AuthenticationError as exc:
            logger.error("Error de autenticación: %s", exc)
        except ConnectionLostError as exc:
            logger.error("Conexión perdida: %s", exc)
        except KeyboardInterrupt:
            logger.warning("Bot detenido por el usuario (Ctrl+C).")
        except Exception:
            logger.exception("Error inesperado en el bucle principal del bot.")
        finally:
            self._running = False
            logger.warning("Bot detenido.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_logged(self) -> bool:
        return bool(getattr(self.client, "logged", False))
