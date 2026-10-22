"""Internal authentication and bounded sliding-window request limits."""
import hmac
import time
from collections import deque

from fastapi import Header, HTTPException

from src.config import settings


def valid_internal_key(value):
    return isinstance(value, str) and hmac.compare_digest(value.encode(), settings.INTERNAL_API_KEY.encode())


def require_internal_key(x_internal_key: str = Header(default="")):
    if not valid_internal_key(x_internal_key):
        raise HTTPException(401, "Invalid internal key")


class RateLimiter:
    def __init__(self):
        self.events = {}

    def check(self, operation, username, ip):
        now = time.monotonic()
        cutoff = now - settings.RATE_LIMIT_WINDOW_SECONDS
        for key in list(self.events):
            queue = self.events[key]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if not queue:
                del self.events[key]
        keys = [(operation, "username", username), (operation, "ip", ip)]
        limits = [settings.RATE_LIMIT_USERNAME, settings.RATE_LIMIT_IP]
        if any(len(self.events.get(key, ())) >= limit for key, limit in zip(keys, limits)):
            raise HTTPException(429, "Too many requests")
        for key in keys:
            self.events.setdefault(key, deque()).append(now)
