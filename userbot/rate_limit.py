"""
Rate limiter for userbot sends.
"""

import time
from collections import deque
from typing import Deque


class RateLimiter:
    def __init__(self, max_calls: int = 30, time_window: int = 60) -> None:
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls: Deque[float] = deque()

    def can_make_call(self) -> bool:
        now = time.time()
        while self.calls and self.calls[0] <= now - self.time_window:
            self.calls.popleft()
        return len(self.calls) < self.max_calls

    def record_call(self) -> None:
        self.calls.append(time.time())
