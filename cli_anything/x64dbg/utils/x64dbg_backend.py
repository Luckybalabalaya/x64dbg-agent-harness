from __future__ import annotations

import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

LANG_MARKERS = ("0:Default", "1:Script DLL")


def quote_argument(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_native_command(name: str, *args: str) -> str:
    filtered = [arg for arg in args if arg not in ("", None)]
    if not filtered:
        return name
    return f"{name} " + ", ".join(filtered)


def find_headless(headless_path: str = "", arch: str = "x64", source_root: str = "") -> str:
    candidates: list[str] = []
    if headless_path:
        candidates.append(headless_path)
    if source_root:
        candidates.append(str(Path(source_root) / "bin" / arch / "headless.exe"))
    candidates.extend(
        [
            str(Path.cwd() / "bin" / arch / "headless.exe"),
            str(Path.cwd() / "x64dbg" / "bin" / arch / "headless.exe"),
        ]
    )
    which = shutil.which("headless.exe")
    if which:
        candidates.append(which)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError(
        "headless.exe not found. Configure it with `session configure --headless <path>` "
        "or set `--source-root` to the x64dbg checkout."
    )


@dataclass
class BackendResult:
    ok: bool
    command: str
    output: str


class HeadlessSession:
    def __init__(self, executable: str):
        self.executable = executable
        self.process: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    def __enter__(self) -> "HeadlessSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return
        self.process = subprocess.Popen(
            [self.executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdout is not None
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()

    def _pump_stdout(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._queue.put(line)
        self._queue.put(None)

    def execute(self, command: str, timeout: float = 30.0) -> BackendResult:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("headless session is not running")
        self.process.stdin.write(command + "\n")
        self.process.stdin.write("langs\n")
        self.process.stdin.flush()
        lines: list[str] = []
        marker_index = 0
        while True:
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError(f"Timed out while waiting for command: {command}") from exc
            if item is None:
                break
            line = item.rstrip("\r\n")
            lines.append(line)
            if marker_index < len(LANG_MARKERS) and line == LANG_MARKERS[marker_index]:
                marker_index += 1
                if marker_index == len(LANG_MARKERS):
                    lines = lines[: -len(LANG_MARKERS)]
                    break
            else:
                marker_index = 0
        output = "\n".join(lines).strip()
        ok = "[FAIL]" not in output
        return BackendResult(ok=ok, command=command, output=output)

    def execute_many(self, commands: list[str], timeout: float = 30.0) -> list[BackendResult]:
        return [self.execute(command, timeout=timeout) for command in commands]

    def close(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin:
                try:
                    self.process.stdin.write("exit\n")
                    self.process.stdin.flush()
                except OSError:
                    pass
                self.process.stdin.close()
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        finally:
            self.process = None


def run_one_shot(executable: str, commands: list[str], timeout: float = 30.0) -> list[BackendResult]:
    if len(commands) != 1:
        raise ValueError("run_one_shot expects exactly one command")
    result = run_command_block(executable, commands, timeout=timeout)
    return [BackendResult(ok=result.ok, command=commands[0], output=result.output)]


def run_command_block(executable: str, commands: list[str], timeout: float = 30.0) -> BackendResult:
    payload = "\n".join([*commands, "exit", ""])
    completed = subprocess.run(
        [executable],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = completed.stdout.strip()
    ok = completed.returncode == 0 and "[FAIL]" not in output
    return BackendResult(ok=ok, command=" && ".join(commands), output=output)
