from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_cli(name: str) -> list[str]:
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = "cli_anything.x64dbg.x64dbg_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-x64dbg")
    HEADLESS = Path(r"C:\Users\Administrator\x64dbg\bin\x64\headless.exe")
    SOURCE_ROOT = Path(r"C:\Users\Administrator\x64dbg")
    TARGET = Path(r"C:\Windows\System32\notepad.exe")

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(r"C:\Users\Administrator\x64dbg\agent-harness"))
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            check=check,
            env=env,
        )

    def test_help(self) -> None:
        result = self._run(["--help"])
        assert result.returncode == 0
        assert "Stateful CLI harness for x64dbg" in result.stdout

    def test_session_configure_and_show_json(self, tmp_path: Path) -> None:
        state_file = tmp_path / "session.json"
        result = self._run(
            [
                "--state-file",
                str(state_file),
                "session",
                "configure",
                "--headless",
                str(self.HEADLESS),
                "--arch",
                "x64",
                "--source-root",
                str(self.SOURCE_ROOT),
            ]
        )
        assert result.returncode == 0
        result = self._run(["--json", "--state-file", str(state_file), "session", "show"])
        payload = json.loads(result.stdout)
        assert payload["headless_path"].endswith("headless.exe")
        assert payload["source_root"].endswith("x64dbg")

    def test_script_langs_real_backend(self, tmp_path: Path) -> None:
        state_file = tmp_path / "session.json"
        self._run(
            [
                "--state-file",
                str(state_file),
                "session",
                "configure",
                "--headless",
                str(self.HEADLESS),
                "--arch",
                "x64",
                "--source-root",
                str(self.SOURCE_ROOT),
            ]
        )
        result = self._run(["--json", "--state-file", str(state_file), "script", "langs"])
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        print(f"\n  headless: {self.HEADLESS}")

    def test_process_init_real_backend(self, tmp_path: Path) -> None:
        state_file = tmp_path / "session.json"
        self._run(
            [
                "--state-file",
                str(state_file),
                "session",
                "configure",
                "--headless",
                str(self.HEADLESS),
                "--arch",
                "x64",
                "--source-root",
                str(self.SOURCE_ROOT),
            ]
        )
        init_result = self._run(["--json", "--state-file", str(state_file), "process", "init", str(self.TARGET)])
        init_payload = json.loads(init_result.stdout)
        assert init_payload["ok"] is True
        assert "Initialization successful!" in init_payload["output"]

    def test_batch_entry_workflow_real_backend(self, tmp_path: Path) -> None:
        state_file = tmp_path / "session.json"
        self._run(
            [
                "--state-file",
                str(state_file),
                "session",
                "configure",
                "--headless",
                str(self.HEADLESS),
                "--arch",
                "x64",
                "--source-root",
                str(self.SOURCE_ROOT),
            ]
        )
        result = self._run(
            [
                "--json",
                "--state-file",
                str(state_file),
                "batch",
                "--command",
                f'init "{self.TARGET}"',
                "--command",
                'bp cip, "entry"',
                "--command",
                "run",
                "--command",
                "state",
                "--command",
                "bplist",
            ]
        )
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert "cip:" in payload["output"] or "entry breakpoint" in payload["output"] or '"entry"' in payload["output"]

    def test_workflow_capture_init_real_backend(self, tmp_path: Path) -> None:
        state_file = tmp_path / "session.json"
        out_dir = tmp_path / "capture"
        self._run(
            [
                "--state-file",
                str(state_file),
                "session",
                "configure",
                "--headless",
                str(self.HEADLESS),
                "--arch",
                "x64",
                "--source-root",
                str(self.SOURCE_ROOT),
            ]
        )
        result = self._run(
            [
                "--json",
                "--state-file",
                str(state_file),
                "workflow",
                "capture-init",
                str(self.TARGET),
                "--output-dir",
                str(out_dir),
                "--no-minidump",
            ]
        )
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert Path(payload["log_path"]).is_file()
        assert Path(payload["manifest_path"]).is_file()
