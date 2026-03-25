from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .project import DebugTarget


def _locked_save_json(path: str, data: dict[str, Any], **dump_kwargs: Any) -> None:
    try:
        f = open(path, "r+", encoding="utf-8")
    except FileNotFoundError:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        f = open(path, "w", encoding="utf-8")
    with f:
        locked = False
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass
        try:
            f.seek(0)
            f.truncate()
            json.dump(data, f, **dump_kwargs)
            f.flush()
        finally:
            if locked:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@dataclass
class SessionConfig:
    headless_path: str = ""
    arch: str = "x64"
    source_root: str = ""
    last_target: DebugTarget = field(default_factory=DebugTarget)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["last_target"] = self.last_target.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionConfig":
        target = DebugTarget(**data.get("last_target", {}))
        return cls(
            headless_path=data.get("headless_path", ""),
            arch=data.get("arch", "x64"),
            source_root=data.get("source_root", ""),
            last_target=target,
        )


@dataclass
class SessionState:
    current: SessionConfig = field(default_factory=SessionConfig)
    undo_stack: list[dict[str, Any]] = field(default_factory=list)
    redo_stack: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "SessionState":
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return cls(
            current=SessionConfig.from_dict(data.get("current", {})),
            undo_stack=data.get("undo_stack", []),
            redo_stack=data.get("redo_stack", []),
        )

    def save(self, path: str) -> None:
        _locked_save_json(
            path,
            {
                "current": self.current.to_dict(),
                "undo_stack": self.undo_stack,
                "redo_stack": self.redo_stack,
            },
            indent=2,
            ensure_ascii=False,
        )

    def snapshot(self) -> dict[str, Any]:
        return self.current.to_dict()

    def apply(self, **changes: Any) -> SessionConfig:
        self.undo_stack.append(self.snapshot())
        self.redo_stack.clear()
        if "last_target" in changes and isinstance(changes["last_target"], dict):
            changes["last_target"] = DebugTarget(**changes["last_target"])
        for key, value in changes.items():
            setattr(self.current, key, value)
        return self.current

    def reset(self) -> SessionConfig:
        self.undo_stack.append(self.snapshot())
        self.redo_stack.clear()
        self.current = SessionConfig()
        return self.current

    def undo(self) -> SessionConfig | None:
        if not self.undo_stack:
            return None
        self.redo_stack.append(self.snapshot())
        self.current = SessionConfig.from_dict(self.undo_stack.pop())
        return self.current

    def redo(self) -> SessionConfig | None:
        if not self.redo_stack:
            return None
        self.undo_stack.append(self.snapshot())
        self.current = SessionConfig.from_dict(self.redo_stack.pop())
        return self.current
