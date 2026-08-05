#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Registro automático de comandos.

Cada comando se define en su propio archivo dentro de commands/ y se
autoregistra usando el decorador `@command(...)`. No hace falta tocar
main.py ni ningún __init__ para añadir, quitar o modificar un comando:
basta con crear/editar/borrar el archivo .py correspondiente.

Uso típico en commands/saludo.py:

    from core.registry import command

    @command("saludo", aliases=["hola"], help="Saluda al usuario")
    def handle_saludo(ctx):
        ctx.reply("¡Hola! 👋")

`ctx` es un CommandContext (ver core.context) con toda la información
del mensaje y helpers para responder.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("bot.registry")


@dataclass
class CommandSpec:
    name: str
    handler: Callable
    aliases: List[str] = field(default_factory=list)
    help: str = ""
    usage: str = ""
    hidden: bool = False
    admin_only: bool = False
    source_module: str = ""


class CommandRegistry:
    """Contiene todos los comandos registrados, indexados por nombre y alias."""

    def __init__(self) -> None:
        self._commands: Dict[str, CommandSpec] = {}   # nombre principal -> spec
        self._aliases: Dict[str, str] = {}             # alias -> nombre principal

    def register(self, spec: CommandSpec) -> None:
        key = spec.name.lower()
        if key in self._commands:
            logger.warning(
                "El comando '%s' ya estaba registrado (definido en %s); "
                "se sobrescribe con la versión de %s.",
                key, self._commands[key].source_module, spec.source_module,
            )
        self._commands[key] = spec
        for alias in spec.aliases:
            alias_key = alias.lower()
            if alias_key in self._aliases or alias_key in self._commands:
                logger.warning(
                    "El alias '%s' del comando '%s' choca con otro comando/alias existente.",
                    alias_key, key,
                )
            self._aliases[alias_key] = key

    def resolve(self, name: str) -> Optional[CommandSpec]:
        key = name.lower()
        if key in self._commands:
            return self._commands[key]
        if key in self._aliases:
            return self._commands.get(self._aliases[key])
        return None

    def all(self) -> List[CommandSpec]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    def __len__(self) -> int:
        return len(self._commands)


registry = CommandRegistry()


def command(
    name: str,
    *,
    aliases: Optional[List[str]] = None,
    help: str = "",
    usage: str = "",
    hidden: bool = False,
    admin_only: bool = False,
):
    """Decorador para registrar una función como comando del bot."""

    def decorator(func: Callable) -> Callable:
        spec = CommandSpec(
            name=name,
            handler=func,
            aliases=list(aliases or []),
            help=help,
            usage=usage,
            hidden=hidden,
            admin_only=admin_only,
            source_module=func.__module__,
        )
        registry.register(spec)
        return func

    return decorator


def load_commands(package_name: str = "commands") -> int:
    """Importa todos los módulos dentro de commands/ para que se autoregistren.

    Devuelve la cantidad de módulos cargados correctamente. Un error en un
    archivo de comando individual se registra como error pero no impide
    que se carguen los demás.
    """
    try:
        package = importlib.import_module(package_name)
    except ImportError:
        logger.error("No se encontró el paquete de comandos '%s'.", package_name)
        return 0

    loaded = 0
    for _finder, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
        if is_pkg or module_name.startswith("_"):
            continue
        full_name = f"{package_name}.{module_name}"
        try:
            importlib.import_module(full_name)
            loaded += 1
        except Exception:
            logger.exception("Error cargando el comando '%s'. Se omite.", full_name)

    return loaded


def reload_commands(package_name: str = "commands") -> int:
    """Recarga en caliente todos los comandos (útil tras editar un archivo)."""
    import sys

    to_reload = [
        mod_name for mod_name in list(sys.modules)
        if mod_name == package_name or mod_name.startswith(package_name + ".")
    ]
    for mod_name in to_reload:
        sys.modules.pop(mod_name, None)

    registry._commands.clear()
    registry._aliases.clear()
    return load_commands(package_name)
