from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class DebugTarget:
    executable: str = ""
    arguments: str = ""
    cwd: str = ""
    attached_pid: int | None = None

    def normalized(self) -> "DebugTarget":
        return DebugTarget(
            executable=str(Path(self.executable).expanduser()) if self.executable else "",
            arguments=self.arguments,
            cwd=str(Path(self.cwd).expanduser()) if self.cwd else "",
            attached_pid=self.attached_pid,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_summary(target: DebugTarget) -> str:
    parts: list[str] = []
    if target.executable:
        parts.append(target.executable)
    if target.attached_pid is not None:
        parts.append(f"pid={target.attached_pid}")
    if target.arguments:
        parts.append(f"args={target.arguments}")
    if target.cwd:
        parts.append(f"cwd={target.cwd}")
    return ", ".join(parts) if parts else "no target"


def create(executable: str = "", arguments: str = "", cwd: str = "", attached_pid: int | None = None) -> DebugTarget:
    return DebugTarget(
        executable=executable,
        arguments=arguments,
        cwd=cwd,
        attached_pid=attached_pid,
    ).normalized()


def open(path: str) -> dict[str, Any]:
    project_path = Path(path).expanduser()
    data = json.loads(project_path.read_text(encoding="utf-8"))
    target_data = data.get("target", data)
    target = DebugTarget(**target_data).normalized()
    return {
        "path": str(project_path),
        "target": target,
        "profile": data.get("profile", "default"),
        "metadata": data.get("metadata", {}),
        "exists": project_path.exists(),
    }


def save(path: str, target: DebugTarget, profile: str = "default", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    project_path = Path(path).expanduser()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": profile,
        "target": target.normalized().to_dict(),
        "metadata": metadata or {},
    }
    project_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "path": str(project_path),
        "target": DebugTarget(**payload["target"]),
        "profile": profile,
        "metadata": payload["metadata"],
    }


def info(path: str, state_file: str | None = None) -> dict[str, Any]:
    from .session import SessionState

    project = open(path)
    target: DebugTarget = project["target"]
    state = SessionState.load(state_file) if state_file else SessionState()
    return {
        "path": project["path"],
        "profile": project["profile"],
        "target": target,
        "summary": project_summary(target),
        "exists": project["exists"],
        "metadata": project["metadata"],
        "current_session_target": state.current.last_target.to_dict(),
    }


def list_profiles() -> list[str]:
    return ["default", "attach", "trace", "capture-init", "capture-trace"]
