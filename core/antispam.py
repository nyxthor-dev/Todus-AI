#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Anti-spam: detecta mensajes duplicados (reenvíos offline de ToDus) y
aplica un cooldown por usuario para evitar flood.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict

logger = logging.getLogger("bot.antispam")


class AntiSpamManager:
    def __init__(self, max_messages: int = 2000, cooldown_seconds: float = 2):
        self.max_messages = max_messages
        self.cooldown_seconds = cooldown_seconds

        self.processed_ids = set()
        self.recent_ids = deque(maxlen=200)

        self.user_last_message: Dict[str, float] = {}
        self.user_message_count: Dict[str, int] = {}

        self.stats = {
            "total_processed": 0,
            "duplicates_blocked": 0,
            "rate_limited_blocked": 0,
            "last_cleanup": time.time(),
        }

    def _cleanup(self) -> None:
        now = time.time()
        if now - self.stats["last_cleanup"] <= 300:
            return

        if len(self.processed_ids) > self.max_messages:
            old_ids = list(self.processed_ids)[: self.max_messages // 2]
            for old_id in old_ids:
                self.processed_ids.discard(old_id)

        inactive_users = [
            user for user, ts in self.user_last_message.items() if now - ts > 3600
        ]
        for user in inactive_users:
            self.user_last_message.pop(user, None)
            self.user_message_count.pop(user, None)

        self.stats["last_cleanup"] = now

    def is_duplicate_id(self, msg_id: str) -> bool:
        if not msg_id:
            return False
        if msg_id in self.processed_ids or msg_id in self.recent_ids:
            self.stats["duplicates_blocked"] += 1
            return True
        return False

    def register_message(self, msg_id: str, user_id: str) -> None:
        if msg_id:
            self.processed_ids.add(msg_id)
            self.recent_ids.append(msg_id)
            self._cleanup()

        if user_id:
            self.user_last_message[user_id] = time.time()
            self.user_message_count[user_id] = self.user_message_count.get(user_id, 0) + 1

        self.stats["total_processed"] += 1

    def is_rate_limited(self, user_id: str) -> bool:
        if not user_id:
            return False

        now = time.time()
        last_time = self.user_last_message.get(user_id, 0)
        if last_time == 0:
            return False

        if now - last_time < self.cooldown_seconds:
            self.stats["rate_limited_blocked"] += 1
            return True

        return False

    def get_stats(self) -> dict:
        return {
            **self.stats,
            "cache_size": len(self.processed_ids),
            "recent_size": len(self.recent_ids),
            "active_users": len(self.user_last_message),
            "cooldown_seconds": self.cooldown_seconds,
            "max_messages": self.max_messages,
        }

    def reset(self) -> None:
        self.processed_ids.clear()
        self.recent_ids.clear()
        self.user_last_message.clear()
        self.user_message_count.clear()
        self.stats = {
            "total_processed": 0,
            "duplicates_blocked": 0,
            "rate_limited_blocked": 0,
            "last_cleanup": time.time(),
        }
        logger.warning("Anti-spam reiniciado manualmente.")
