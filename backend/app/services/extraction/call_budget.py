"""Hard ceiling on real Gemini calls per process lifetime (GEMINI_MAX_CALLS_PER_RUN).
A backstop against a runaway retry loop or a batch script gone wrong burning
API budget -- not a substitute for the Gemini/Google AI Studio dashboard's own
monthly spend cap, which CLAUDE.md's manual-prerequisites step asks the operator
to set separately.
"""

from __future__ import annotations

import threading


class CallBudgetExceeded(RuntimeError):
    pass


class CallBudget:
    def __init__(self, max_calls: int) -> None:
        self._max_calls = max_calls
        self._used = 0
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> None:
        with self._lock:
            if self._used + n > self._max_calls:
                raise CallBudgetExceeded(
                    f"GEMINI_MAX_CALLS_PER_RUN={self._max_calls} exceeded "
                    f"(already used {self._used}, requested {n} more)"
                )
            self._used += n

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self._max_calls - self._used
