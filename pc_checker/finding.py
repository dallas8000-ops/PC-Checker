from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    severity: str  # ok | warn | critical
    title: str
    detail: str
    next_steps: tuple[str, ...] = field(default_factory=tuple)
