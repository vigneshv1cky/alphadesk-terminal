"""Where a slow call spends its time (2026-10-06).

A call made of many stages — the earnings calendar's build, the candidates
tool's four sources — is timed stage by stage, and the split is logged only
when the whole call took long enough to be worth reading. Measured, so a slow
tool is fixed where its time goes rather than where it is guessed to go.
"""
from __future__ import annotations

import logging
import time


class Stages:
    def __init__(self, name: str, log: logging.Logger, threshold_s: float = 2.0) -> None:
        self.name, self.log, self.threshold_s = name, log, threshold_s
        self.t0 = self.last = time.perf_counter()
        self.parts: list[tuple[str, float]] = []

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self.parts.append((label, now - self.last))
        self.last = now

    def done(self, note: str = "") -> None:
        total = time.perf_counter() - self.t0
        if total >= self.threshold_s:
            split = ", ".join(f"{k} {v:.2f}s" for k, v in self.parts)
            self.log.info("%s took %.2fs%s: %s", self.name, total, f" ({note})" if note else "", split)
