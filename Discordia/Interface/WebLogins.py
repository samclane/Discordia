"""
Logins for the web map. Discord already vouches for who someone is, so there are no passwords: /weblogin
hands out a one-time link, and the link trades for a session cookie. Nothing to store, leak, or reset.

Only SHA-256 digests of the link tokens and session ids are kept, so whoever reads these tables can't log
in with what they find. The secrets are 256 random bits: a fast hash is enough, a password KDF buys nothing.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Callable, Dict, Optional, Tuple

LINK_SECONDS = 10 * 60
SESSION_SECONDS = 30 * 24 * 60 * 60


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class WebLogins:
    """Shared by the bot loop (issuing links) and the HTTP threads (redeeming them). Each dict operation
    is atomic under the GIL, and pop() is what makes a link good for one use even if two requests race.
    """

    # ponytail: in memory, so a restart logs everyone out and they /weblogin again. Give sessions a
    # database table if that grates.
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._links: Dict[str, Tuple[int, float]] = {}  # digest -> (member id, expiry)
        self._sessions: Dict[str, Tuple[int, float]] = {}

    def new_link_token(self, member_id: int) -> str:
        now = self._clock()
        # Forget what's expired, so neither table grows forever.
        for table in (self._links, self._sessions):
            for key, (_, expires) in list(table.items()):
                if expires < now:
                    table.pop(key, None)
        token = secrets.token_urlsafe(32)
        self._links[_digest(token)] = (member_id, now + LINK_SECONDS)
        return token

    def redeem(self, token: str) -> Optional[str]:
        """A new session id for a link token, once. None if it's unknown, already used, or stale."""
        member_id, expires = self._links.pop(_digest(token), (None, 0.0))
        now = self._clock()
        if member_id is None or expires < now:
            return None
        session = secrets.token_urlsafe(32)
        self._sessions[_digest(session)] = (member_id, now + SESSION_SECONDS)
        return session

    def end(self, session: str):
        """Log out: the session stops working here, whatever the browser keeps."""
        self._sessions.pop(_digest(session), None)

    def member_id(self, session: str) -> Optional[int]:
        member_id, expires = self._sessions.get(_digest(session), (None, 0.0))
        return member_id if expires >= self._clock() else None
