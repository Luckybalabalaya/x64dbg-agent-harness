from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
import re

from click.testing import CliRunner

from cli_anything.x64dbg.core.session import SessionState
from cli_anything.x64dbg.utils.x64dbg_backend import build_native_command, find_headless, quote_argument
from cli_anything.x64dbg.utils.repl_skin import ReplSkin
import cli_anything.x64dbg.x64dbg_cli as cli_module
from cli_anything.x64dbg.x64dbg_cli import main


def test_session_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / "session.json"
    state = SessionState.load(str(state_path))
    state.apply(headless_path="C:/x64dbg/bin/x64/headless.exe", arch="x64", source_root="C:/x64dbg")
    state.save(str(state_path))
    loaded = SessionState.load(str(state_path))
    assert loaded.current.headless_path.endswith("headless.exe")
    assert loaded.current.arch == "x64"


def test_session_undo_redo() -> None:
    state = SessionState()
    state.apply(headless_path="one.exe")
    state.apply(headless_path="two.exe")
    assert state.undo() is not None
    assert state.current.headless_path == "one.exe"
    assert state.redo() is not None
    assert state.current.headless_path == "two.exe"


def test_quote_argument_and_build_native_command() -> None:
    assert quote_argument('C:\\Program Files\\a "b".exe') == '"C:\\\\Program Files\\\\a \\"b\\".exe"'
    assert build_native_command("init", '"a.exe"', "", '"cwd"') == 'init "a.exe", "cwd"'


def test_find_headless_prefers_explicit_path(tmp_path: Path) -> None:
    headless = tmp_path / "headless.exe"
    headless.write_text("", encoding="utf-8")
    assert find_headless(headless_path=str(headless)).endswith("headless.exe")


def test_find_headless_raises_when_missing(monkeypatch) -> None:
    monkeypatch.chdir(Path.cwd().anchor)
    try:
        find_headless(headless_path="", arch="x64", source_root="C:/definitely/missing")
    except RuntimeError as exc:
        assert "headless.exe not found" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_cli_session_show_json(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "session.json"
    state = SessionState()
    state.apply(headless_path="C:/x64dbg/bin/x64/headless.exe", arch="x64")
    state.save(str(state_file))
    result = runner.invoke(main, ["--json", "--state-file", str(state_file), "session", "show"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["arch"] == "x64"


def test_cli_batch_requires_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--state-file", str(tmp_path / "state.json"), "batch"])
    assert result.exit_code != 0


def test_cli_thread_switch_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "thread", "switch", "1234"])
    assert result.exit_code == 0
    assert captured == {"action": "thread.switch", "command": "switchthread 1234"}


def test_cli_memory_alloc_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "memory", "alloc", "--size", "1000", "--address", "401000"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "memory.alloc", "command": "alloc 1000, 401000"}


def test_cli_process_detach_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "process", "detach"])
    assert result.exit_code == 0
    assert captured == {"action": "process.detach", "command": "detach"}


def test_cli_process_step_out_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "process", "step-out"])
    assert result.exit_code == 0
    assert captured == {"action": "process.step-out", "command": "StepOut"}


def test_cli_process_run_skip_exceptions_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "process", "run-skip-exceptions"])
    assert result.exit_code == 0
    assert captured == {"action": "process.run-skip-exceptions", "command": "erun"}


def test_cli_thread_set_priority_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "thread", "set-priority", "1234", "Normal"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "thread.set-priority", "command": "setthreadpriority 1234, Normal"}


def test_cli_variable_new_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "variable", "new", "foo", "1"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "variable.new", "command": "varnew foo, 1"}


def test_cli_variable_set_string_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "variable", "set-string", "msg", "hello world"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "variable.set-string", "command": 'setstr msg, "hello world"'}


def test_cli_condbp_condition_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "condbp", "condition", "401000", "eax==1"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "condbp.condition", "command": "bpcond 401000, eax==1"}


def test_cli_trace_start_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "trace", "start-recording", "C:\\trace.trace64"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "trace.start-recording",
        "command": 'StartRunTrace "C:\\\\trace.trace64"',
    }


def test_cli_analyze_image_info_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "analyze", "image-info", "401000"])
    assert result.exit_code == 0
    assert captured == {"action": "analyze.image-info", "command": "imageinfo 401000"}


def test_cli_analyze_dump_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "analyze", "dump", "401000"])
    assert result.exit_code == 0
    assert captured == {"action": "analyze.dump", "command": "dump 401000"}


def test_cli_analyze_recursive_analyse_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "analyze", "recursive-analyse", "401000"])
    assert result.exit_code == 0
    assert captured == {"action": "analyze.recursive-analyse", "command": "analrecur 401000"}


def test_cli_analyze_xrefs_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "analyze", "xrefs"])
    assert result.exit_code == 0
    assert captured == {"action": "analyze.xrefs", "command": "analxrefs"}


def test_cli_symbols_load_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "symbols", "load", "ntdll", "C:\\symbols\\ntdll.pdb", "--force"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "symbols.load",
        "command": 'symload ntdll, "C:\\\\symbols\\\\ntdll.pdb", 1',
    }


def test_cli_os_hide_debugger_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "os", "hide-debugger"])
    assert result.exit_code == 0
    assert captured == {"action": "os.hide-debugger", "command": "HideDebugger"}


def test_cli_os_jit_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "os", "jit-set", "C:\\jit\\dbg.exe"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "os.jit-set",
        "command": 'setjit "C:\\\\jit\\\\dbg.exe"',
    }


def test_cli_os_enable_privilege_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "os", "enable-privilege", "SeDebugPrivilege"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "os.enable-privilege",
        "command": "EnablePrivilege SeDebugPrivilege",
    }


def test_cli_database_save_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "database", "save", "C:\\temp\\sample.dd64"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "database.save",
        "command": 'dbsave "C:\\\\temp\\\\sample.dd64"',
    }


def test_cli_hwbp_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "hwbp", "set", "401000", "--type", "x", "--size", "1"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "hwbp.set", "command": "bph 401000, x, 1"}


def test_cli_membp_condition_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "membp", "condition", "401000", "eax==1"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "membp.condition", "command": "bpmcond 401000, eax==1"}


def test_cli_memory_minidump_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "memory", "minidump", "C:\\temp\\sample.dmp"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "memory.minidump",
        "command": 'minidump "C:\\\\temp\\\\sample.dmp"',
    }


def test_cli_memory_copy_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "memory", "copy", "402000", "401000", "40"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "memory.copy",
        "command": "memcpy 402000, 401000, 40",
    }


def test_cli_register_get_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "register", "get", "cip"])
    assert result.exit_code == 0
    assert captured == {
        "action": "register.get",
        "command": "cip",
    }


def test_cli_register_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "register", "set", "cax", "401000"])
    assert result.exit_code == 0
    assert captured == {
        "action": "register.set",
        "command": "mov cax, 401000",
    }


def test_cli_register_copy_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(main, ["--state-file", str(tmp_path / "state.json"), "register", "copy", "cbx", "cax"])
    assert result.exit_code == 0
    assert captured == {
        "action": "register.copy",
        "command": "mov cbx, cax",
    }


def test_cli_register_dump_uses_single_session_block(monkeypatch, tmp_path: Path) -> None:
    def fake_block(headless, commands, timeout=30.0):
        assert headless.endswith("headless.exe")
        assert commands[:3] == [
            'dprintf "cip={p:cip}\\n"',
            'dprintf "csp={p:csp}\\n"',
            'dprintf "cax={p:cax}\\n"',
        ]
        return SimpleNamespace(
            ok=True,
            command=" && ".join(commands),
            output="cip=0000000140001000\ncsp=0000000000002000",
        )

    monkeypatch.setattr(cli_module, "run_command_block", fake_block)
    monkeypatch.setattr(cli_module, "find_headless", lambda **kwargs: kwargs["headless_path"])
    state_file = tmp_path / "state.json"
    state = SessionState()
    state.apply(headless_path="C:/x64dbg/bin/x64/headless.exe", arch="x64")
    state.save(str(state_file))
    result = CliRunner().invoke(
        main,
        ["--json", "--state-file", str(state_file), "register", "dump", "--profile", "core"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "register.dump"
    assert payload["profile"] == "core"
    assert payload["registers"][:3] == ["cip", "csp", "cax"]
    assert "cip=0000000140001000" in payload["output"]


def test_cli_search_asm_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "search", "asm", "mov eax, ebx", "--address", "401000", "--size", "40"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "search.asm",
        "command": 'findasm "mov eax, ebx", 401000, 40',
    }


def test_cli_search_refs_range_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "search", "refs-range", "401000", "402000"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "search.refs-range",
        "command": "reffindrange 401000, 402000",
    }


def test_cli_search_function_pointers_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "search", "function-pointers", "401000", "--size", "200"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "search.function-pointers",
        "command": "reffunctionpointer 401000, 200",
    }


def test_cli_search_module_calls_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "search", "module-calls", "401000", "--size", "200"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "search.module-calls",
        "command": "modcallfind 401000, 200",
    }


def test_cli_search_guids_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "search", "guids", "401000", "--size", "200"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "search.guids",
        "command": "guidfind 401000, 200",
    }


def test_cli_userdb_comment_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "comment-set", "401000", "interesting branch"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.comment-set",
        "command": 'commentset 401000, "interesting branch"',
    }


def test_cli_userdb_bookmark_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "bookmark-set", "401000"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.bookmark-set",
        "command": "bookmarkset 401000",
    }


def test_cli_userdb_function_add_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "function-add", "401000", "401040"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.function-add",
        "command": "functionadd 401000, 401040",
    }


def test_cli_userdb_argument_add_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "argument-add", "401000", "401010"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.argument-add",
        "command": "argumentadd 401000, 401010",
    }


def test_cli_userdb_loop_add_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "loop-add", "401000", "401050"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.loop-add",
        "command": "loopadd 401000, 401050",
    }


def test_cli_userdb_loop_delete_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "loop-delete", "401000"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.loop-delete",
        "command": "loopdel 401000",
    }


def test_cli_userdb_loop_delete_with_depth_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "loop-delete", "401000", "--depth", "2"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.loop-delete",
        "command": "loopdel 401000, 2",
    }


def test_cli_userdb_loop_list_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "loop-list"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.loop-list",
        "command": "looplist",
    }


def test_cli_userdb_loop_clear_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "userdb", "loop-clear"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "userdb.loop-clear",
        "command": "loopclear",
    }


def test_cli_watch_add_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "watch", "add", "[rax]", "--type", "uint"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "watch.add",
        "command": 'AddWatch "[rax]", "uint"',
    }


def test_cli_watch_set_expression_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "watch", "set-expression", "1", "[rbx+8]", "--type", "ascii"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "watch.set-expression",
        "command": 'SetWatchExpression 1, "[rbx+8]", "ascii"',
    }


def test_cli_watch_set_watchdog_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "watch", "set-watchdog", "1", "changed"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "watch.set-watchdog",
        "command": 'SetWatchdog 1, "changed"',
    }


def test_cli_watch_check_watchdog_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "watch", "check-watchdog"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "watch.check-watchdog",
        "command": "CheckWatchdog",
    }


def test_cli_workflow_capture_init_writes_manifest(monkeypatch, tmp_path: Path) -> None:
    def fake_block(headless, commands, timeout=30.0):
        assert headless.endswith("headless.exe")
        assert commands[0] == 'init "C:\\\\sample.exe"'
        assert commands[1:4] == ["state", "disasm cip", "bplist"]
        assert commands[4] == f'dbsave "{str(tmp_path / "out" / "capture.dd64").replace("\\", "\\\\")}"'
        return SimpleNamespace(
            ok=True,
            command=" && ".join(commands),
            output=(
                "Breakpoint at 0000000140001000 (entry breakpoint) set!\n"
                "Database file: C:\\temp\\orig.dd64\n"
                "Process stopped with exit code 0x0 (0)\n"
            ),
        )

    monkeypatch.setattr(cli_module, "run_command_block", fake_block)
    monkeypatch.setattr(cli_module, "find_headless", lambda **kwargs: kwargs["headless_path"])
    state_file = tmp_path / "state.json"
    state = SessionState()
    state.apply(headless_path="C:/x64dbg/bin/x64/headless.exe", arch="x64")
    state.save(str(state_file))
    result = CliRunner().invoke(
        main,
        [
            "--json",
            "--state-file",
            str(state_file),
            "workflow",
            "capture-init",
            "C:\\sample.exe",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "workflow.capture-init"
    assert payload["entry_breakpoint"] == "0x0000000140001000"
    assert payload["process_exit"] == "0x0"
    assert Path(payload["log_path"]).is_file()
    manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["database_copy"].endswith("capture.dd64")
    loaded = SessionState.load(str(state_file))
    assert loaded.current.last_target.executable == "C:\\sample.exe"


def test_cli_workflow_capture_trace_writes_manifest(monkeypatch, tmp_path: Path) -> None:
    def fake_block(headless, commands, timeout=30.0):
        assert headless.endswith("headless.exe")
        assert commands[0] == 'init "C:\\\\sample.exe"'
        assert commands[1].startswith('StartRunTrace "')
        assert "TraceSetStepFilter user" in commands
        assert "rtu" in commands
        assert "TraceIntoIntoTraceRecord 5" in commands
        return SimpleNamespace(
            ok=True,
            command=" && ".join(commands),
            output=(
                "Breakpoint at 0000000140002000 (entry breakpoint) set!\n"
                "Process stopped with exit code 0x0 (0)\n"
            ),
        )

    monkeypatch.setattr(cli_module, "run_command_block", fake_block)
    monkeypatch.setattr(cli_module, "find_headless", lambda **kwargs: kwargs["headless_path"])
    state_file = tmp_path / "state.json"
    state = SessionState()
    state.apply(headless_path="C:/x64dbg/bin/x64/headless.exe", arch="x64")
    state.save(str(state_file))
    result = CliRunner().invoke(
        main,
        [
            "--json",
            "--state-file",
            str(state_file),
            "workflow",
            "capture-trace",
            "C:\\sample.exe",
            "--output-dir",
            str(tmp_path / "trace-out"),
            "--run-to-user",
            "--step-filter",
            "user",
            "--max-steps",
            "5",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["action"] == "workflow.capture-trace"
    assert payload["entry_breakpoint"] == "0x0000000140002000"
    assert Path(payload["log_path"]).is_file()
    manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["trace_file"].endswith("capture.trace64")


def test_skill_md_mentions_current_command_groups() -> None:
    skill = Path(r"C:\Users\Administrator\x64dbg\agent-harness\cli_anything\x64dbg\skills\SKILL.md").read_text(encoding="utf-8")
    assert "### `register`" in skill
    assert "### `variable`" in skill
    assert "### `os`" in skill
    assert "### `workflow`" in skill
    assert "register dump --profile core" in skill
    assert "workflow capture-init" in skill


def test_skill_md_has_yaml_frontmatter() -> None:
    skill = Path(r"C:\Users\Administrator\x64dbg\agent-harness\cli_anything\x64dbg\skills\SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", skill, flags=re.DOTALL)
    assert match is not None
    frontmatter = match.group(1)
    assert "name:" in frontmatter
    assert "description:" in frontmatter


def test_pyproject_packages_skill_md() -> None:
    pyproject_content = Path(r"C:\Users\Administrator\x64dbg\agent-harness\pyproject.toml").read_text(encoding="utf-8")
    assert '[tool.setuptools.package-data]' in pyproject_content
    assert '"cli_anything.x64dbg" = ["README.md", "skills/*.md", "tests/*.md", "tests/*.py"]' in pyproject_content


def test_repl_skin_autodetects_packaged_skill_md() -> None:
    skin = ReplSkin("x64dbg", version="1.0.0")
    assert skin.skill_path is not None
    assert skin.skill_path.endswith(r"cli_anything\x64dbg\skills\SKILL.md")
    assert Path(skin.skill_path).is_file()


def test_cli_libbp_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "libbp", "set", "ntdll.dll", "--break-on-load"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "libbp.set", "command": 'SetLibrarianBPX "ntdll.dll", load'}


def test_cli_libbp_delete_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "libbp", "delete", "ntdll.dll"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "libbp.delete", "command": 'DeleteLibrarianBPX "ntdll.dll"'}


def test_cli_libbp_enable_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "libbp", "enable", "kernel32.dll"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "libbp.enable", "command": 'EnableLibrarianBPX "kernel32.dll"'}


def test_cli_libbp_disable_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "libbp", "disable", "kernel32.dll"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "libbp.disable", "command": 'DisableLibrarianBPX "kernel32.dll"'}


def test_cli_exbp_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "exbp", "set", "C0000005", "--first-chance"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "exbp.set", "command": "SetExceptionBPX C0000005, 1"}


def test_cli_exbp_delete_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "exbp", "delete", "C0000005"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "exbp.delete", "command": "DeleteExceptionBPX C0000005"}


def test_cli_exbp_enable_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "exbp", "enable", "C000001D"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "exbp.enable", "command": "EnableExceptionBPX C000001D"}


def test_cli_exbp_disable_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "exbp", "disable", "C000001D"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "exbp.disable", "command": "DisableExceptionBPX C000001D"}


def test_cli_analyze_asm_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "analyze", "asm", "401000", "mov eax, ebx"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "analyze.asm", "command": 'asm 401000, "mov eax, ebx"'}


def test_cli_analyze_gpa_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "analyze", "gpa", "CreateFileW"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "analyze.gpa", "command": 'gpa "CreateFileW"'}


def test_cli_analyze_gpa_with_module_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "analyze", "gpa", "malloc", "--module", "ucrtbase.dll"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "analyze.gpa", "command": 'gpa "malloc", ucrtbase.dll'}


def test_cli_plugin_load_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "plugin", "load", "C:\\plugins\\myplugin.dp64"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "plugin.load",
        "command": 'pluginload "C:\\\\plugins\\\\myplugin.dp64"',
    }


def test_cli_plugin_unload_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "plugin", "unload", "C:\\plugins\\myplugin.dp64"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "plugin.unload",
        "command": 'pluginunload "C:\\\\plugins\\\\myplugin.dp64"',
    }


def test_cli_plugin_reload_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "plugin", "reload", "C:\\plugins\\myplugin.dp64"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "plugin.reload",
        "command": 'pluginreload "C:\\\\plugins\\\\myplugin.dp64"',
    }


def test_cli_plugin_reload_no_prompt_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "plugin", "reload", "C:\\plugins\\myplugin.dp64", "--no-prompt"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "plugin.reload",
        "command": 'pluginreload "C:\\\\plugins\\\\myplugin.dp64", 1',
    }


def test_cli_misc_meminfo_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "misc", "meminfo", "a", "401000"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "misc.meminfo",
        "command": "meminfo a, 401000",
    }


def test_cli_misc_meminfo_with_size_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "misc", "meminfo", "r", "401000", "1000"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "misc.meminfo",
        "command": "meminfo r, 401000,1000",
    }


def test_cli_misc_flushlog_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "misc", "flushlog"],
    )
    assert result.exit_code == 0
    assert captured == {
        "action": "misc.flushlog",
        "command": "flushlog",
    }


def test_cli_math_inc_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "inc", "eax"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.inc", "command": "eax++"}


def test_cli_math_dec_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "dec", "ebx"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.dec", "command": "ebx--"}


def test_cli_math_add_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "add", "eax", "10"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.add", "command": "eax+=10"}


def test_cli_math_sub_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "sub", "ecx", "5"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.sub", "command": "ecx-=5"}


def test_cli_math_mul_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "mul", "eax", "2"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.mul", "command": "eax*=2"}


def test_cli_math_div_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "div", "eax", "4"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.div", "command": "eax/=4"}


def test_cli_math_and_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "and", "eax", "0xFF"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.and", "command": "eax&=0xFF"}


def test_cli_math_or_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "or", "eax", "0x100"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.or", "command": "eax|=0x100"}


def test_cli_math_xor_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "xor", "eax", "0x55"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.xor", "command": "eax^=0x55"}


def test_cli_math_not_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "not", "eax"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.not", "command": "eax=~eax"}


def test_cli_math_neg_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "neg", "eax"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.neg", "command": "eax=-eax"}


def test_cli_math_shl_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "shl", "eax", "4"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.shl", "command": "eax<<=4"}


def test_cli_math_shr_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "shr", "eax", "2"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.shr", "command": "eax>>=2"}


def test_cli_math_rol_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "rol", "eax", "8"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.rol", "command": "rol eax, 8"}


def test_cli_math_ror_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "ror", "eax", "4"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.ror", "command": "ror eax, 4"}


def test_cli_math_bswap_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "math", "bswap", "eax"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "math.bswap", "command": "bswap eax"}


def test_cli_stack_push_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "stack", "push", "12345678"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "stack.push", "command": "push 12345678"}


def test_cli_stack_pop_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "stack", "pop"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "stack.pop", "command": "pop"}


def test_cli_stack_pop_dest_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "stack", "pop", "eax"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "stack.pop", "command": "pop eax"}


def test_cli_compare_test_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "compare", "test", "eax", "0xFF"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "compare.test", "command": "test eax, 0xFF"}


def test_cli_compare_cmp_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "compare", "cmp", "eax", "ebx"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "compare.cmp", "command": "cmp eax, ebx"}


def test_cli_mov_set_builds_native_command(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def fake_run(ctx, action, command, target=None):
        captured["action"] = action
        captured["command"] = command

    monkeypatch.setattr(cli_module, "_run_single", fake_run)
    result = CliRunner().invoke(
        main,
        ["--state-file", str(tmp_path / "state.json"), "mov", "set", "eax", "12345678"],
    )
    assert result.exit_code == 0
    assert captured == {"action": "mov.set", "command": "mov eax, 12345678"}
