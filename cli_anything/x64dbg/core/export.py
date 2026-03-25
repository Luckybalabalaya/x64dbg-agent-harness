from __future__ import annotations

import json
from typing import Any

import click

EXPORT_PRESETS: dict[str, dict[str, Any]] = {
    "json": {"format": "json", "indent": 2, "ensure_ascii": False},
    "json-compact": {"format": "json", "indent": None, "ensure_ascii": False},
    "text": {"format": "text"},
}


def build_result(ok: bool, action: str, command: str | None = None, output: str = "", **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "action": action,
        "command": command,
        "output": output,
    }
    payload.update(extra)
    return payload


def emit(ctx: click.Context, payload: dict[str, Any], human: str | None = None) -> None:
    if ctx.obj.get("json"):
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if human is not None:
        click.echo(human)
        return
    output = payload.get("output")
    if output:
        click.echo(output.rstrip())
    else:
        click.echo(payload.get("action", "ok"))


def render(payload: dict[str, Any], preset: str = "json", human: str | None = None) -> str:
    config = EXPORT_PRESETS.get(preset)
    if config is None:
        raise ValueError(f"Unknown export preset: {preset}")
    if config["format"] == "text":
        if human is not None:
            return human
        output = payload.get("output")
        return output.rstrip() if isinstance(output, str) and output else str(payload.get("action", "ok"))
    return json.dumps(
        payload,
        indent=config["indent"],
        ensure_ascii=config["ensure_ascii"],
    )
