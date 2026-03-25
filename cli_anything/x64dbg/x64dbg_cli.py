from __future__ import annotations

import functools
import json
import re
import shlex
from pathlib import Path

import click

from . import __version__
from .core.export import build_result, emit
from .core.project import DebugTarget, project_summary
from .core.session import SessionState
from .utils.repl_skin import ReplSkin
from .utils.x64dbg_backend import (
    HeadlessSession,
    build_native_command,
    find_headless,
    quote_argument,
    run_command_block,
    run_one_shot,
)


DEFAULT_STATE_FILE = str(Path.home() / ".cli-anything-x64dbg" / "session.json")


def handle_error(func):
    """Decorator for consistent CLI error handling."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except click.ClickException:
            raise
        except RuntimeError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(f"Unexpected error: {e}")
    return wrapper


def _resolve_settings(ctx: click.Context) -> tuple[SessionState, str]:
    state = SessionState.load(ctx.obj["state_file"])
    headless = find_headless(
        headless_path=ctx.obj["headless"] or state.current.headless_path,
        arch=ctx.obj["arch"] or state.current.arch,
        source_root=ctx.obj["source_root"] or state.current.source_root,
    )
    return state, headless


def _emit_backend_result(ctx: click.Context, action: str, result, **extra) -> None:
    payload = build_result(result.ok, action, command=result.command, output=result.output, **extra)
    emit(ctx, payload)


def _capture_output_markers(output: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    entry = re.search(r"Breakpoint at ([0-9A-Fa-f]+) \(entry breakpoint\) set!", output)
    if entry:
        markers["entry_breakpoint"] = f"0x{entry.group(1).upper()}"
    exit_code = re.search(r"Process stopped with exit code (0x[0-9A-Fa-f]+)", output)
    if exit_code:
        markers["process_exit"] = exit_code.group(1)
    database = re.search(r"Database file: (.+?\.dd(?:32|64))", output)
    if database:
        markers["database_file"] = database.group(1).strip()
    return markers


@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON output.")
@click.option("--state-file", default=DEFAULT_STATE_FILE, show_default=True, help="Path to the session state JSON file.")
@click.option("--headless", default=None, help="Path to x64dbg headless.exe.")
@click.option("--arch", default=None, type=click.Choice(["x32", "x64"]), help="Debugger architecture.")
@click.option("--source-root", default=None, help="Path to the x64dbg source tree.")
@click.version_option(version=__version__)
@click.pass_context
def main(ctx: click.Context, json_mode: bool, state_file: str, headless: str | None, arch: str | None, source_root: str | None) -> None:
    """Stateful CLI harness for x64dbg."""
    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "json": json_mode,
            "state_file": state_file,
            "headless": headless,
            "arch": arch,
            "source_root": source_root,
        }
    )
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@main.group()
def session() -> None:
    """Session state and backend configuration."""


@session.command("show")
@click.pass_context
def session_show(ctx: click.Context) -> None:
    state = SessionState.load(ctx.obj["state_file"])
    payload = build_result(
        True,
        "session.show",
        headless_path=state.current.headless_path,
        arch=state.current.arch,
        source_root=state.current.source_root,
        last_target=state.current.last_target.to_dict(),
        undo_depth=len(state.undo_stack),
        redo_depth=len(state.redo_stack),
    )
    human = (
        f"headless={state.current.headless_path or '<unset>'}\n"
        f"arch={state.current.arch}\n"
        f"source_root={state.current.source_root or '<unset>'}\n"
        f"last_target={project_summary(state.current.last_target)}\n"
        f"undo={len(state.undo_stack)} redo={len(state.redo_stack)}"
    )
    emit(ctx, payload, human)


@session.command("configure")
@click.option("--headless", required=False, help="Path to headless.exe.")
@click.option("--arch", type=click.Choice(["x32", "x64"]), required=False)
@click.option("--source-root", required=False, help="Path to the x64dbg checkout.")
@click.pass_context
def session_configure(ctx: click.Context, headless: str | None, arch: str | None, source_root: str | None) -> None:
    state = SessionState.load(ctx.obj["state_file"])
    changes = {}
    if headless is not None:
        changes["headless_path"] = headless
    if arch is not None:
        changes["arch"] = arch
    if source_root is not None:
        changes["source_root"] = source_root
    if not changes:
        raise click.ClickException("No changes provided.")
    current = state.apply(**changes)
    state.save(ctx.obj["state_file"])
    payload = build_result(True, "session.configure", **current.to_dict())
    emit(ctx, payload, f"configured {current.arch} backend at {current.headless_path or '<unset>'}")


@session.command("reset")
@click.pass_context
def session_reset(ctx: click.Context) -> None:
    state = SessionState.load(ctx.obj["state_file"])
    current = state.reset()
    state.save(ctx.obj["state_file"])
    payload = build_result(True, "session.reset", **current.to_dict())
    emit(ctx, payload, "session reset")


@session.command("undo")
@click.pass_context
def session_undo(ctx: click.Context) -> None:
    state = SessionState.load(ctx.obj["state_file"])
    current = state.undo()
    if current is None:
        raise click.ClickException("No configuration undo state available.")
    state.save(ctx.obj["state_file"])
    payload = build_result(True, "session.undo", **current.to_dict())
    emit(ctx, payload, "session configuration undone")


@session.command("redo")
@click.pass_context
def session_redo(ctx: click.Context) -> None:
    state = SessionState.load(ctx.obj["state_file"])
    current = state.redo()
    if current is None:
        raise click.ClickException("No configuration redo state available.")
    state.save(ctx.obj["state_file"])
    payload = build_result(True, "session.redo", **current.to_dict())
    emit(ctx, payload, "session configuration redone")


@main.group()
def process() -> None:
    """Debuggee lifecycle and stepping commands."""


def _run_single(ctx: click.Context, action: str, command: str, target: DebugTarget | None = None) -> None:
    state, headless = _resolve_settings(ctx)
    result = run_one_shot(headless, [command])[0]
    if target is not None:
        state.apply(last_target=target.to_dict())
        state.save(ctx.obj["state_file"])
    _emit_backend_result(ctx, action, result, target=target.to_dict() if target else None)


@process.command("init")
@click.argument("executable")
@click.argument("arguments", required=False, default="")
@click.option("--cwd", default="", help="Debuggee working directory.")
@click.pass_context
def process_init(ctx: click.Context, executable: str, arguments: str, cwd: str) -> None:
    target = DebugTarget(executable=executable, arguments=arguments, cwd=cwd).normalized()
    command = build_native_command(
        "init",
        quote_argument(target.executable),
        quote_argument(target.arguments) if target.arguments else "",
        quote_argument(target.cwd) if target.cwd else "",
    )
    _run_single(ctx, "process.init", command, target=target)


@process.command("attach")
@click.argument("pid", type=int)
@click.pass_context
def process_attach(ctx: click.Context, pid: int) -> None:
    target = DebugTarget(attached_pid=pid)
    _run_single(ctx, "process.attach", build_native_command("attach", str(pid)), target=target)


@process.command("detach")
@click.pass_context
def process_detach(ctx: click.Context) -> None:
    _run_single(ctx, "process.detach", "detach")


@process.command("run")
@click.option("--to", "run_to", default="", help="Optional single-shot run target.")
@click.pass_context
def process_run(ctx: click.Context, run_to: str) -> None:
    _run_single(ctx, "process.run", build_native_command("run", run_to))


@process.command("run-skip-exceptions")
@click.pass_context
def process_run_skip_exceptions(ctx: click.Context) -> None:
    _run_single(ctx, "process.run-skip-exceptions", "erun")


@process.command("run-swallow-exception")
@click.pass_context
def process_run_swallow_exception(ctx: click.Context) -> None:
    _run_single(ctx, "process.run-swallow-exception", "serun")


@process.command("pause")
@click.pass_context
def process_pause(ctx: click.Context) -> None:
    _run_single(ctx, "process.pause", "pause")


@process.command("continue")
@click.pass_context
def process_continue(ctx: click.Context) -> None:
    _run_single(ctx, "process.continue", "con")


@process.command("stop")
@click.pass_context
def process_stop(ctx: click.Context) -> None:
    _run_single(ctx, "process.stop", "stop")


@process.command("step-into")
@click.option("--count", default=1, type=int, show_default=True)
@click.pass_context
def process_step_into(ctx: click.Context, count: int) -> None:
    _run_single(ctx, "process.step-into", build_native_command("StepInto", str(count)))


@process.command("step-into-skip-exceptions")
@click.pass_context
def process_step_into_skip_exceptions(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-into-skip-exceptions", "eStepInto")


@process.command("step-into-swallow-exception")
@click.pass_context
def process_step_into_swallow_exception(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-into-swallow-exception", "seStepInto")


@process.command("step-over")
@click.pass_context
def process_step_over(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-over", "StepOver")


@process.command("step-over-skip-exceptions")
@click.pass_context
def process_step_over_skip_exceptions(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-over-skip-exceptions", "eStepOver")


@process.command("step-over-swallow-exception")
@click.pass_context
def process_step_over_swallow_exception(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-over-swallow-exception", "seStepOver")


@process.command("step-out")
@click.pass_context
def process_step_out(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-out", "StepOut")


@process.command("step-out-skip-exceptions")
@click.pass_context
def process_step_out_skip_exceptions(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-out-skip-exceptions", "eStepOut")


@process.command("skip")
@click.pass_context
def process_skip(ctx: click.Context) -> None:
    _run_single(ctx, "process.skip", "skip")


@process.command("step-user")
@click.pass_context
def process_step_user(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-user", "StepUser")


@process.command("step-system")
@click.pass_context
def process_step_system(ctx: click.Context) -> None:
    _run_single(ctx, "process.step-system", "StepSystem")


@process.command("cmdline-get")
@click.pass_context
def process_cmdline_get(ctx: click.Context) -> None:
    _run_single(ctx, "process.cmdline-get", "getcommandline")


@process.command("cmdline-set")
@click.argument("value")
@click.pass_context
def process_cmdline_set(ctx: click.Context, value: str) -> None:
    _run_single(ctx, "process.cmdline-set", build_native_command("setcommandline", quote_argument(value)))


@main.group()
def breakpoint() -> None:
    """INT3 breakpoint helpers."""


@breakpoint.command("set")
@click.argument("address")
@click.option("--name", default="", help="Breakpoint display name.")
@click.option("--type", "bp_type", default="", help="x64dbg breakpoint type string, e.g. ssud2.")
@click.pass_context
def breakpoint_set(ctx: click.Context, address: str, name: str, bp_type: str) -> None:
    command = build_native_command(
        "bp",
        address,
        quote_argument(name) if name else "",
        quote_argument(bp_type) if bp_type else "",
    )
    _run_single(ctx, "breakpoint.set", command)


@breakpoint.command("list")
@click.pass_context
def breakpoint_list(ctx: click.Context) -> None:
    _run_single(ctx, "breakpoint.list", "bplist")


@breakpoint.command("delete")
@click.argument("target", required=False, default="")
@click.pass_context
def breakpoint_delete(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "breakpoint.delete", build_native_command("bpc", target))


@breakpoint.command("enable")
@click.argument("target", required=False, default="")
@click.pass_context
def breakpoint_enable(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "breakpoint.enable", build_native_command("bpe", target))


@breakpoint.command("disable")
@click.argument("target", required=False, default="")
@click.pass_context
def breakpoint_disable(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "breakpoint.disable", build_native_command("bpd", target))


@main.group()
def hwbp() -> None:
    """Hardware breakpoint helpers."""


@hwbp.command("set")
@click.argument("address")
@click.option("--type", "bp_type", default="", help="Hardware breakpoint type: x, r, or w.")
@click.option("--size", default="", help="Breakpoint size: 1, 2, 4, or 8.")
@click.pass_context
def hwbp_set(ctx: click.Context, address: str, bp_type: str, size: str) -> None:
    _run_single(ctx, "hwbp.set", build_native_command("bph", address, bp_type, size))


@hwbp.command("delete")
@click.argument("target", required=False, default="")
@click.pass_context
def hwbp_delete(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "hwbp.delete", build_native_command("bphc", target))


@hwbp.command("enable")
@click.argument("target", required=False, default="")
@click.pass_context
def hwbp_enable(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "hwbp.enable", build_native_command("bphe", target))


@hwbp.command("disable")
@click.argument("target", required=False, default="")
@click.pass_context
def hwbp_disable(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "hwbp.disable", build_native_command("bphd", target))


@hwbp.command("condition")
@click.argument("address")
@click.argument("expression", required=False, default="")
@click.pass_context
def hwbp_condition(ctx: click.Context, address: str, expression: str) -> None:
    _run_single(ctx, "hwbp.condition", build_native_command("bphwcond", address, expression))


@main.group()
def membp() -> None:
    """Memory breakpoint helpers."""


@membp.command("set")
@click.argument("address")
@click.option("--restore", default="", help="Restore flag: 1 or 0.")
@click.option("--type", "bp_type", default="", help="Memory breakpoint type: a, r, w, or x.")
@click.pass_context
def membp_set(ctx: click.Context, address: str, restore: str, bp_type: str) -> None:
    _run_single(ctx, "membp.set", build_native_command("bpm", address, restore, bp_type))


@membp.command("delete")
@click.argument("target", required=False, default="")
@click.pass_context
def membp_delete(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "membp.delete", build_native_command("bpmc", target))


@membp.command("enable")
@click.argument("target", required=False, default="")
@click.pass_context
def membp_enable(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "membp.enable", build_native_command("bpme", target))


@membp.command("disable")
@click.argument("target", required=False, default="")
@click.pass_context
def membp_disable(ctx: click.Context, target: str) -> None:
    _run_single(ctx, "membp.disable", build_native_command("bpmd", target))


@membp.command("condition")
@click.argument("address")
@click.argument("expression", required=False, default="")
@click.pass_context
def membp_condition(ctx: click.Context, address: str, expression: str) -> None:
    _run_single(ctx, "membp.condition", build_native_command("bpmcond", address, expression))


@main.group()
def libbp() -> None:
    """Librarian (DLL load/unload) breakpoint helpers."""


@libbp.command("set")
@click.argument("dll_name")
@click.option("--break-on-load", is_flag=True, default=False, help="Break when DLL loads.")
@click.option("--break-on-unload", is_flag=True, default=False, help="Break when DLL unloads.")
@click.pass_context
def libbp_set(ctx: click.Context, dll_name: str, break_on_load: bool, break_on_unload: bool) -> None:
    flags = []
    if break_on_load:
        flags.append("load")
    if break_on_unload:
        flags.append("unload")
    flag_str = ",".join(flags) if flags else ""
    _run_single(ctx, "libbp.set", build_native_command("SetLibrarianBPX", quote_argument(dll_name), flag_str))


@libbp.command("delete")
@click.argument("dll_name", required=False, default="")
@click.pass_context
def libbp_delete(ctx: click.Context, dll_name: str) -> None:
    _run_single(ctx, "libbp.delete", build_native_command("DeleteLibrarianBPX", quote_argument(dll_name) if dll_name else ""))


@libbp.command("enable")
@click.argument("dll_name", required=False, default="")
@click.pass_context
def libbp_enable(ctx: click.Context, dll_name: str) -> None:
    _run_single(ctx, "libbp.enable", build_native_command("EnableLibrarianBPX", quote_argument(dll_name) if dll_name else ""))


@libbp.command("disable")
@click.argument("dll_name", required=False, default="")
@click.pass_context
def libbp_disable(ctx: click.Context, dll_name: str) -> None:
    _run_single(ctx, "libbp.disable", build_native_command("DisableLibrarianBPX", quote_argument(dll_name) if dll_name else ""))


@libbp.command("condition")
@click.argument("dll_name")
@click.argument("expression", required=False, default="")
@click.pass_context
def libbp_condition(ctx: click.Context, dll_name: str, expression: str) -> None:
    _run_single(ctx, "libbp.condition", build_native_command("SetLibrarianBPXCondition", quote_argument(dll_name), expression))


@main.group()
def exbp() -> None:
    """Exception breakpoint helpers."""


@exbp.command("set")
@click.argument("exception_code")
@click.option("--first-chance", is_flag=True, default=False, help="Break on first chance exception.")
@click.pass_context
def exbp_set(ctx: click.Context, exception_code: str, first_chance: bool) -> None:
    flag = "1" if first_chance else ""
    _run_single(ctx, "exbp.set", build_native_command("SetExceptionBPX", exception_code, flag))


@exbp.command("delete")
@click.argument("exception_code", required=False, default="")
@click.pass_context
def exbp_delete(ctx: click.Context, exception_code: str) -> None:
    _run_single(ctx, "exbp.delete", build_native_command("DeleteExceptionBPX", exception_code))


@exbp.command("enable")
@click.argument("exception_code", required=False, default="")
@click.pass_context
def exbp_enable(ctx: click.Context, exception_code: str) -> None:
    _run_single(ctx, "exbp.enable", build_native_command("EnableExceptionBPX", exception_code))


@exbp.command("disable")
@click.argument("exception_code", required=False, default="")
@click.pass_context
def exbp_disable(ctx: click.Context, exception_code: str) -> None:
    _run_single(ctx, "exbp.disable", build_native_command("DisableExceptionBPX", exception_code))


@main.group()
def condbp() -> None:
    """Conditional software-breakpoint configuration."""


@condbp.command("condition")
@click.argument("address")
@click.argument("expression", required=False, default="")
@click.pass_context
def condbp_condition(ctx: click.Context, address: str, expression: str) -> None:
    _run_single(ctx, "condbp.condition", build_native_command("bpcond", address, expression))


@condbp.command("log")
@click.argument("address")
@click.argument("text", required=False, default="")
@click.pass_context
def condbp_log(ctx: click.Context, address: str, text: str) -> None:
    _run_single(ctx, "condbp.log", build_native_command("bplog", address, quote_argument(text) if text else ""))


@condbp.command("command")
@click.argument("address")
@click.argument("command_text", required=False, default="")
@click.pass_context
def condbp_command(ctx: click.Context, address: str, command_text: str) -> None:
    _run_single(
        ctx,
        "condbp.command",
        build_native_command("SetBreakpointCommand", address, quote_argument(command_text) if command_text else ""),
    )


@condbp.command("hit-count")
@click.argument("address")
@click.pass_context
def condbp_hit_count(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "condbp.hit-count", build_native_command("GetBreakpointHitCount", address))


@condbp.command("reset-hit-count")
@click.argument("address")
@click.option("--value", default=0, type=int, show_default=True)
@click.pass_context
def condbp_reset_hit_count(ctx: click.Context, address: str, value: int) -> None:
    _run_single(ctx, "condbp.reset-hit-count", build_native_command("ResetBreakpointHitCount", address, str(value)))


@main.group()
def thread() -> None:
    """Thread-control wrappers."""


@thread.command("switch")
@click.argument("tid", required=False, default="")
@click.pass_context
def thread_switch(ctx: click.Context, tid: str) -> None:
    _run_single(ctx, "thread.switch", build_native_command("switchthread", tid))


@thread.command("suspend")
@click.argument("tid", required=False, default="")
@click.pass_context
def thread_suspend(ctx: click.Context, tid: str) -> None:
    _run_single(ctx, "thread.suspend", build_native_command("suspendthread", tid))


@thread.command("resume")
@click.argument("tid", required=False, default="")
@click.pass_context
def thread_resume(ctx: click.Context, tid: str) -> None:
    _run_single(ctx, "thread.resume", build_native_command("resumethread", tid))


@thread.command("kill")
@click.argument("tid", required=False, default="")
@click.option("--exit-code", default=0, type=int, show_default=True)
@click.pass_context
def thread_kill(ctx: click.Context, tid: str, exit_code: int) -> None:
    _run_single(ctx, "thread.kill", build_native_command("killthread", tid, str(exit_code) if tid else ""))


@thread.command("suspend-all")
@click.pass_context
def thread_suspend_all(ctx: click.Context) -> None:
    _run_single(ctx, "thread.suspend-all", "suspendallthreads")


@thread.command("resume-all")
@click.pass_context
def thread_resume_all(ctx: click.Context) -> None:
    _run_single(ctx, "thread.resume-all", "resumeallthreads")


@thread.command("set-priority")
@click.argument("tid")
@click.argument("priority")
@click.pass_context
def thread_set_priority(ctx: click.Context, tid: str, priority: str) -> None:
    _run_single(ctx, "thread.set-priority", build_native_command("setthreadpriority", tid, priority))


@thread.command("set-name")
@click.argument("tid")
@click.argument("name")
@click.pass_context
def thread_set_name(ctx: click.Context, tid: str, name: str) -> None:
    _run_single(ctx, "thread.set-name", build_native_command("threadsetname", tid, quote_argument(name)))


@main.group()
def memory() -> None:
    """Memory-operation wrappers."""


@memory.command("alloc")
@click.option("--size", default="", help="Allocation size expression, e.g. 1000.")
@click.option("--address", default="", help="Optional target base address.")
@click.pass_context
def memory_alloc(ctx: click.Context, size: str, address: str) -> None:
    _run_single(ctx, "memory.alloc", build_native_command("alloc", size, address))


@memory.command("free")
@click.argument("address", required=False, default="")
@click.pass_context
def memory_free(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "memory.free", build_native_command("free", address))


@memory.command("save")
@click.argument("path")
@click.argument("address")
@click.argument("size")
@click.pass_context
def memory_save(ctx: click.Context, path: str, address: str, size: str) -> None:
    _run_single(ctx, "memory.save", build_native_command("savedata", quote_argument(path), address, size))


@memory.command("minidump")
@click.argument("path")
@click.pass_context
def memory_minidump(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "memory.minidump", build_native_command("minidump", quote_argument(path)))


@memory.command("fill")
@click.argument("address")
@click.argument("value")
@click.option("--size", default="", help="Optional fill size expression.")
@click.pass_context
def memory_fill(ctx: click.Context, address: str, value: str, size: str) -> None:
    _run_single(ctx, "memory.fill", build_native_command("Fill", address, value, size))


@memory.command("copy")
@click.argument("destination")
@click.argument("source")
@click.argument("size")
@click.pass_context
def memory_copy(ctx: click.Context, destination: str, source: str, size: str) -> None:
    _run_single(ctx, "memory.copy", build_native_command("memcpy", destination, source, size))


@memory.command("rights-get")
@click.argument("address")
@click.pass_context
def memory_rights_get(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "memory.rights-get", build_native_command("getpagerights", address))


@memory.command("rights-set")
@click.argument("address")
@click.argument("rights")
@click.pass_context
def memory_rights_set(ctx: click.Context, address: str, rights: str) -> None:
    _run_single(ctx, "memory.rights-set", build_native_command("setpagerights", address, rights))


@main.group()
def register() -> None:
    """Register probes and mutation helpers."""


_REGISTER_PROFILES: dict[str, tuple[str, ...]] = {
    "core": ("cip", "csp", "cax", "cbx", "ccx", "cdx", "csi", "cdi", "cbp", "cflags"),
    "debug": ("dr0", "dr1", "dr2", "dr3", "dr6", "dr7"),
}


def _register_printf_command(name: str) -> str:
    return f'dprintf "{name}={{p:{name}}}\\n"'


@register.command("get")
@click.argument("name")
@click.pass_context
def register_get(ctx: click.Context, name: str) -> None:
    _run_single(ctx, "register.get", name)


@register.command("set")
@click.argument("name")
@click.argument("value")
@click.pass_context
def register_set(ctx: click.Context, name: str, value: str) -> None:
    _run_single(ctx, "register.set", build_native_command("mov", name, value))


@register.command("copy")
@click.argument("destination")
@click.argument("source")
@click.pass_context
def register_copy(ctx: click.Context, destination: str, source: str) -> None:
    _run_single(ctx, "register.copy", build_native_command("mov", destination, source))


@register.command("dump")
@click.option("--profile", type=click.Choice(sorted(_REGISTER_PROFILES)), default="core", show_default=True)
@click.pass_context
def register_dump(ctx: click.Context, profile: str) -> None:
    _, headless = _resolve_settings(ctx)
    commands = [_register_printf_command(name) for name in _REGISTER_PROFILES[profile]]
    result = run_command_block(headless, commands)
    payload = build_result(
        result.ok,
        "register.dump",
        command=result.command,
        output=result.output,
        profile=profile,
        registers=list(_REGISTER_PROFILES[profile]),
    )
    emit(ctx, payload, result.output)


@main.group()
def variable() -> None:
    """Variable and string-variable helpers."""


@variable.command("new")
@click.argument("name")
@click.argument("value", required=False, default="")
@click.pass_context
def variable_new(ctx: click.Context, name: str, value: str) -> None:
    _run_single(ctx, "variable.new", build_native_command("varnew", name, value))


@variable.command("delete")
@click.argument("name")
@click.pass_context
def variable_delete(ctx: click.Context, name: str) -> None:
    _run_single(ctx, "variable.delete", build_native_command("vardel", name))


@variable.command("list")
@click.argument("type_filter", required=False, default="")
@click.pass_context
def variable_list(ctx: click.Context, type_filter: str) -> None:
    _run_single(ctx, "variable.list", build_native_command("varlist", type_filter))


@variable.command("set-string")
@click.argument("name")
@click.argument("value")
@click.pass_context
def variable_set_string(ctx: click.Context, name: str, value: str) -> None:
    _run_single(ctx, "variable.set-string", build_native_command("setstr", name, quote_argument(value)))


@variable.command("get-string")
@click.argument("name")
@click.pass_context
def variable_get_string(ctx: click.Context, name: str) -> None:
    _run_single(ctx, "variable.get-string", build_native_command("getstr", name))


@variable.command("copy-string")
@click.argument("address")
@click.argument("name")
@click.pass_context
def variable_copy_string(ctx: click.Context, address: str, name: str) -> None:
    _run_single(ctx, "variable.copy-string", build_native_command("copystr", address, name))


@main.group()
def analyze() -> None:
    """Debugger inspection commands."""


@analyze.command("state")
@click.pass_context
def analyze_state(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.state", "state")


@analyze.command("disasm")
@click.argument("address", required=False, default="")
@click.pass_context
def analyze_disasm(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "analyze.disasm", build_native_command("disasm", address))


@analyze.command("dump")
@click.argument("address", required=False, default="")
@click.pass_context
def analyze_dump(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "analyze.dump", build_native_command("dump", address))


@analyze.command("stack-dump")
@click.argument("address", required=False, default="")
@click.pass_context
def analyze_stack_dump(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "analyze.stack-dump", build_native_command("sdump", address))


@analyze.command("memmap-dump")
@click.argument("address", required=False, default="")
@click.pass_context
def analyze_memmap_dump(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "analyze.memmap-dump", build_native_command("memmapdump", address))


@analyze.command("image-info")
@click.argument("base", required=False, default="")
@click.pass_context
def analyze_image_info(ctx: click.Context, base: str) -> None:
    _run_single(ctx, "analyze.image-info", build_native_command("imageinfo", base))


@analyze.command("reloc-size")
@click.argument("address")
@click.pass_context
def analyze_reloc_size(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "analyze.reloc-size", build_native_command("GetRelocSize", address))


@analyze.command("exception-info")
@click.pass_context
def analyze_exception_info(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.exception-info", "exinfo")


@analyze.command("exception-handlers")
@click.pass_context
def analyze_exception_handlers(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.exception-handlers", "exhandlers")


@analyze.command("virtual-module")
@click.argument("name")
@click.argument("base")
@click.option("--size", default="", help="Optional module size expression.")
@click.pass_context
def analyze_virtual_module(ctx: click.Context, name: str, base: str, size: str) -> None:
    _run_single(
        ctx,
        "analyze.virtual-module",
        build_native_command("virtualmod", quote_argument(name), base, size),
    )


@analyze.command("xrefs")
@click.pass_context
def analyze_xrefs(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.xrefs", "analxrefs")


@analyze.command("analyse")
@click.pass_context
def analyze_analyse(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.analyse", "analyse")


@analyze.command("exception-analyse")
@click.pass_context
def analyze_exception_analyse(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.exception-analyse", "exanal")


@analyze.command("cf-analyse")
@click.option("--exception-directory", is_flag=True, help="Enable exception-directory-aware control flow analysis.")
@click.pass_context
def analyze_cf_analyse(ctx: click.Context, exception_directory: bool) -> None:
    _run_single(ctx, "analyze.cf-analyse", build_native_command("cfanal", "1" if exception_directory else ""))


@analyze.command("recursive-analyse")
@click.argument("address")
@click.pass_context
def analyze_recursive_analyse(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "analyze.recursive-analyse", build_native_command("analrecur", address))


@analyze.command("advanced-analyse")
@click.pass_context
def analyze_advanced_analyse(ctx: click.Context) -> None:
    _run_single(ctx, "analyze.advanced-analyse", "analadv")


@analyze.command("print-stack")
@click.argument("count", required=False, default="")
@click.pass_context
def analyze_print_stack(ctx: click.Context, count: str) -> None:
    _run_single(ctx, "analyze.print-stack", build_native_command("printstack", count))


@analyze.command("asm")
@click.argument("address")
@click.argument("instruction")
@click.pass_context
def analyze_asm(ctx: click.Context, address: str, instruction: str) -> None:
    """Assemble an instruction at the specified address."""
    _run_single(ctx, "analyze.asm", build_native_command("asm", address, quote_argument(instruction)))


@analyze.command("gpa")
@click.argument("function_name")
@click.option("--module", "module_name", default="", help="Optional module name to search within.")
@click.pass_context
def analyze_gpa(ctx: click.Context, function_name: str, module_name: str) -> None:
    """Get procedure address by name (optionally within a module)."""
    _run_single(ctx, "analyze.gpa", build_native_command("gpa", quote_argument(function_name), module_name))


@main.group()
def script() -> None:
    """Script engine helpers."""


@script.command("langs")
@click.pass_context
def script_langs(ctx: click.Context) -> None:
    _run_single(ctx, "script.langs", "langs")


@script.command("load")
@click.argument("script_path")
@click.pass_context
def script_load(ctx: click.Context, script_path: str) -> None:
    _run_single(ctx, "script.load", build_native_command("scriptload", quote_argument(script_path)))


@script.command("run")
@click.option("--line", type=int, default=None, help="Optional stop line.")
@click.pass_context
def script_run(ctx: click.Context, line: int | None) -> None:
    _run_single(ctx, "script.run", build_native_command("scriptrun", str(line) if line is not None else ""))


@main.group()
def symbols() -> None:
    """Symbol loading helpers."""


@symbols.command("load")
@click.argument("module")
@click.argument("path")
@click.option("--force", is_flag=True, help="Force-load the symbol file.")
@click.pass_context
def symbols_load(ctx: click.Context, module: str, path: str, force: bool) -> None:
    _run_single(
        ctx,
        "symbols.load",
        build_native_command("symload", module, quote_argument(path), "1" if force else ""),
    )


@symbols.command("unload")
@click.argument("module")
@click.pass_context
def symbols_unload(ctx: click.Context, module: str) -> None:
    _run_single(ctx, "symbols.unload", build_native_command("symunload", module))


@main.group()
def os() -> None:
    """OS, loader, and JIT helpers."""


@os.command("hide-debugger")
@click.pass_context
def os_hide_debugger(ctx: click.Context) -> None:
    _run_single(ctx, "os.hide-debugger", "HideDebugger")


@os.command("privilege-state")
@click.pass_context
def os_privilege_state(ctx: click.Context) -> None:
    _run_single(ctx, "os.privilege-state", "GetPrivilegeState")


@os.command("enable-privilege")
@click.argument("name")
@click.pass_context
def os_enable_privilege(ctx: click.Context, name: str) -> None:
    _run_single(ctx, "os.enable-privilege", build_native_command("EnablePrivilege", name))


@os.command("disable-privilege")
@click.argument("name")
@click.pass_context
def os_disable_privilege(ctx: click.Context, name: str) -> None:
    _run_single(ctx, "os.disable-privilege", build_native_command("DisablePrivilege", name))


@os.command("loadlib")
@click.argument("path")
@click.pass_context
def os_loadlib(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "os.loadlib", build_native_command("loadlib", quote_argument(path)))


@os.command("freelib")
@click.argument("module")
@click.pass_context
def os_freelib(ctx: click.Context, module: str) -> None:
    _run_single(ctx, "os.freelib", build_native_command("freelib", module))


@os.command("close-handle")
@click.argument("handle")
@click.pass_context
def os_close_handle(ctx: click.Context, handle: str) -> None:
    _run_single(ctx, "os.close-handle", build_native_command("handleclose", handle))


@os.command("enable-window")
@click.argument("handle")
@click.pass_context
def os_enable_window(ctx: click.Context, handle: str) -> None:
    _run_single(ctx, "os.enable-window", build_native_command("EnableWindow", handle))


@os.command("disable-window")
@click.argument("handle")
@click.pass_context
def os_disable_window(ctx: click.Context, handle: str) -> None:
    _run_single(ctx, "os.disable-window", build_native_command("DisableWindow", handle))


@os.command("jit-get")
@click.pass_context
def os_jit_get(ctx: click.Context) -> None:
    _run_single(ctx, "os.jit-get", "getjit")


@os.command("jit-set")
@click.argument("path")
@click.pass_context
def os_jit_set(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "os.jit-set", build_native_command("setjit", quote_argument(path)))


@os.command("jit-get-auto")
@click.pass_context
def os_jit_get_auto(ctx: click.Context) -> None:
    _run_single(ctx, "os.jit-get-auto", "getjitauto")


@os.command("jit-set-auto")
@click.argument("value")
@click.pass_context
def os_jit_set_auto(ctx: click.Context, value: str) -> None:
    _run_single(ctx, "os.jit-set-auto", build_native_command("setjitauto", value))


@main.group()
def database() -> None:
    """Program database load/save helpers."""


@database.command("save")
@click.argument("path", required=False, default="")
@click.pass_context
def database_save(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "database.save", build_native_command("dbsave", quote_argument(path) if path else ""))


@database.command("load")
@click.argument("path", required=False, default="")
@click.pass_context
def database_load(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "database.load", build_native_command("dbload", quote_argument(path) if path else ""))


@database.command("clear")
@click.pass_context
def database_clear(ctx: click.Context) -> None:
    _run_single(ctx, "database.clear", "dbclear")


@main.group()
def search() -> None:
    """Search and reference-finding helpers."""


@search.command("set-max-results")
@click.argument("count")
@click.pass_context
def search_set_max_results(ctx: click.Context, count: str) -> None:
    _run_single(ctx, "search.set-max-results", build_native_command("setmaxfindresult", count))


@search.command("bytes")
@click.argument("address")
@click.argument("pattern")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_bytes(ctx: click.Context, address: str, pattern: str, size: str) -> None:
    _run_single(ctx, "search.bytes", build_native_command("find", address, quote_argument(pattern), size))


@search.command("bytes-all")
@click.argument("address")
@click.argument("pattern")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_bytes_all(ctx: click.Context, address: str, pattern: str, size: str) -> None:
    _run_single(ctx, "search.bytes-all", build_native_command("findall", address, quote_argument(pattern), size))


@search.command("memory-all")
@click.argument("address")
@click.argument("pattern")
@click.option("--size", default="", help="Optional search size.")
@click.option("--scope", default="", help="Optional scope: user/system/module.")
@click.pass_context
def search_memory_all(ctx: click.Context, address: str, pattern: str, size: str, scope: str) -> None:
    _run_single(
        ctx,
        "search.memory-all",
        build_native_command("findallmem", address, quote_argument(pattern), size, scope),
    )


@search.command("asm")
@click.argument("instruction")
@click.option("--address", default="", help="Optional base address.")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_asm(ctx: click.Context, instruction: str, address: str, size: str) -> None:
    _run_single(
        ctx,
        "search.asm",
        build_native_command("findasm", quote_argument(instruction), address, size),
    )


@search.command("refs")
@click.argument("value")
@click.option("--address", default="", help="Optional base address.")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_refs(ctx: click.Context, value: str, address: str, size: str) -> None:
    _run_single(ctx, "search.refs", build_native_command("reffind", value, address, size))


@search.command("refs-range")
@click.argument("start")
@click.argument("end")
@click.pass_context
def search_refs_range(ctx: click.Context, start: str, end: str) -> None:
    _run_single(ctx, "search.refs-range", build_native_command("reffindrange", start, end))


@search.command("strings")
@click.option("--address", default="", help="Optional base address.")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_strings(ctx: click.Context, address: str, size: str) -> None:
    _run_single(ctx, "search.strings", build_native_command("refstr", address, size))


@search.command("function-pointers")
@click.argument("address", required=False, default="")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_function_pointers(ctx: click.Context, address: str, size: str) -> None:
    _run_single(ctx, "search.function-pointers", build_native_command("reffunctionpointer", address, size))


@search.command("module-calls")
@click.argument("address", required=False, default="")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_module_calls(ctx: click.Context, address: str, size: str) -> None:
    _run_single(ctx, "search.module-calls", build_native_command("modcallfind", address, size))


@search.command("guids")
@click.argument("address", required=False, default="")
@click.option("--size", default="", help="Optional search size.")
@click.pass_context
def search_guids(ctx: click.Context, address: str, size: str) -> None:
    _run_single(ctx, "search.guids", build_native_command("guidfind", address, size))


@main.group()
def userdb() -> None:
    """User database comments and labels."""


@userdb.command("comment-set")
@click.argument("address")
@click.argument("text")
@click.pass_context
def userdb_comment_set(ctx: click.Context, address: str, text: str) -> None:
    _run_single(ctx, "userdb.comment-set", build_native_command("commentset", address, quote_argument(text)))


@userdb.command("comment-delete")
@click.argument("address")
@click.pass_context
def userdb_comment_delete(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "userdb.comment-delete", build_native_command("commentdel", address))


@userdb.command("comment-list")
@click.pass_context
def userdb_comment_list(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.comment-list", "commentlist")


@userdb.command("comment-clear")
@click.pass_context
def userdb_comment_clear(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.comment-clear", "commentclear")


@userdb.command("label-set")
@click.argument("address")
@click.argument("text")
@click.pass_context
def userdb_label_set(ctx: click.Context, address: str, text: str) -> None:
    _run_single(ctx, "userdb.label-set", build_native_command("labelset", address, quote_argument(text)))


@userdb.command("label-delete")
@click.argument("address")
@click.pass_context
def userdb_label_delete(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "userdb.label-delete", build_native_command("labeldel", address))


@userdb.command("label-list")
@click.pass_context
def userdb_label_list(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.label-list", "labellist")


@userdb.command("label-clear")
@click.pass_context
def userdb_label_clear(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.label-clear", "labelclear")


@userdb.command("bookmark-set")
@click.argument("address")
@click.pass_context
def userdb_bookmark_set(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "userdb.bookmark-set", build_native_command("bookmarkset", address))


@userdb.command("bookmark-delete")
@click.argument("address")
@click.pass_context
def userdb_bookmark_delete(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "userdb.bookmark-delete", build_native_command("bookmarkdel", address))


@userdb.command("bookmark-list")
@click.pass_context
def userdb_bookmark_list(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.bookmark-list", "bookmarklist")


@userdb.command("bookmark-clear")
@click.pass_context
def userdb_bookmark_clear(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.bookmark-clear", "bookmarkclear")


@userdb.command("function-add")
@click.argument("start")
@click.argument("end")
@click.pass_context
def userdb_function_add(ctx: click.Context, start: str, end: str) -> None:
    _run_single(ctx, "userdb.function-add", build_native_command("functionadd", start, end))


@userdb.command("function-delete")
@click.argument("address")
@click.pass_context
def userdb_function_delete(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "userdb.function-delete", build_native_command("functiondel", address))


@userdb.command("function-list")
@click.pass_context
def userdb_function_list(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.function-list", "functionlist")


@userdb.command("function-clear")
@click.pass_context
def userdb_function_clear(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.function-clear", "functionclear")


@userdb.command("argument-add")
@click.argument("start")
@click.argument("end")
@click.pass_context
def userdb_argument_add(ctx: click.Context, start: str, end: str) -> None:
    _run_single(ctx, "userdb.argument-add", build_native_command("argumentadd", start, end))


@userdb.command("argument-delete")
@click.argument("address")
@click.pass_context
def userdb_argument_delete(ctx: click.Context, address: str) -> None:
    _run_single(ctx, "userdb.argument-delete", build_native_command("argumentdel", address))


@userdb.command("argument-list")
@click.pass_context
def userdb_argument_list(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.argument-list", "argumentlist")


@userdb.command("argument-clear")
@click.pass_context
def userdb_argument_clear(ctx: click.Context) -> None:
    _run_single(ctx, "userdb.argument-clear", "argumentclear")


@userdb.command("loop-add")
@click.argument("start")
@click.argument("end")
@click.pass_context
def userdb_loop_add(ctx: click.Context, start: str, end: str) -> None:
    """Add a loop entry to the database.

    START is the start address of the loop.
    END is the end address of the loop.
    """
    _run_single(ctx, "userdb.loop-add", build_native_command("loopadd", start, end))


@userdb.command("loop-delete")
@click.argument("address")
@click.option("--depth", default=0, help="Loop depth (0 = all depths).")
@click.pass_context
def userdb_loop_delete(ctx: click.Context, address: str, depth: int) -> None:
    """Delete a loop entry from the database.

    ADDRESS is the address of the loop to delete.
    """
    cmd = build_native_command("loopdel", address, str(depth)) if depth else build_native_command("loopdel", address)
    _run_single(ctx, "userdb.loop-delete", cmd)


@userdb.command("loop-list")
@click.pass_context
def userdb_loop_list(ctx: click.Context) -> None:
    """List all loop entries in the database."""
    _run_single(ctx, "userdb.loop-list", "looplist")


@userdb.command("loop-clear")
@click.pass_context
def userdb_loop_clear(ctx: click.Context) -> None:
    """Clear all loop entries from the database."""
    _run_single(ctx, "userdb.loop-clear", "loopclear")


@main.group()
def watch() -> None:
    """Watch expression and watchdog helpers."""


@watch.command("add")
@click.argument("expression")
@click.option("--type", "watch_type", default="", help="Watch type: uint, int, float, ascii, or unicode.")
@click.pass_context
def watch_add(ctx: click.Context, expression: str, watch_type: str) -> None:
    _run_single(ctx, "watch.add", build_native_command("AddWatch", quote_argument(expression), quote_argument(watch_type) if watch_type else ""))


@watch.command("delete")
@click.argument("watch_id")
@click.pass_context
def watch_delete(ctx: click.Context, watch_id: str) -> None:
    _run_single(ctx, "watch.delete", build_native_command("DelWatch", watch_id))


@watch.command("set-expression")
@click.argument("watch_id")
@click.argument("expression")
@click.option("--type", "watch_type", default="", help="Optional replacement watch type.")
@click.pass_context
def watch_set_expression(ctx: click.Context, watch_id: str, expression: str, watch_type: str) -> None:
    _run_single(
        ctx,
        "watch.set-expression",
        build_native_command("SetWatchExpression", watch_id, quote_argument(expression), quote_argument(watch_type) if watch_type else ""),
    )


@watch.command("set-name")
@click.argument("watch_id")
@click.argument("name")
@click.pass_context
def watch_set_name(ctx: click.Context, watch_id: str, name: str) -> None:
    _run_single(ctx, "watch.set-name", build_native_command("SetWatchName", watch_id, quote_argument(name)))


@watch.command("set-type")
@click.argument("watch_id")
@click.argument("watch_type")
@click.pass_context
def watch_set_type(ctx: click.Context, watch_id: str, watch_type: str) -> None:
    _run_single(ctx, "watch.set-type", build_native_command("SetWatchType", watch_id, quote_argument(watch_type)))


@watch.command("set-watchdog")
@click.argument("watch_id")
@click.argument("mode", required=False, default="")
@click.pass_context
def watch_set_watchdog(ctx: click.Context, watch_id: str, mode: str) -> None:
    _run_single(ctx, "watch.set-watchdog", build_native_command("SetWatchdog", watch_id, quote_argument(mode) if mode else ""))


@watch.command("check-watchdog")
@click.pass_context
def watch_check_watchdog(ctx: click.Context) -> None:
    _run_single(ctx, "watch.check-watchdog", "CheckWatchdog")


@main.group()
def trace() -> None:
    """Tracing and trace-recording wrappers."""


@trace.command("start-recording")
@click.argument("path")
@click.pass_context
def trace_start_recording(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "trace.start-recording", build_native_command("StartRunTrace", quote_argument(path)))


@trace.command("stop-recording")
@click.pass_context
def trace_stop_recording(ctx: click.Context) -> None:
    _run_single(ctx, "trace.stop-recording", "StopRunTrace")


@trace.command("set-step-filter")
@click.argument("mode")
@click.pass_context
def trace_set_step_filter(ctx: click.Context, mode: str) -> None:
    _run_single(ctx, "trace.set-step-filter", build_native_command("TraceSetStepFilter", mode))


@trace.command("into-until")
@click.argument("condition")
@click.option("--max-steps", default="", help="Optional maximum step count.")
@click.pass_context
def trace_into_until(ctx: click.Context, condition: str, max_steps: str) -> None:
    _run_single(ctx, "trace.into-until", build_native_command("ticnd", condition, max_steps))


@trace.command("into-beyond-record")
@click.argument("count", required=False, default="")
@click.pass_context
def trace_into_beyond_record(ctx: click.Context, count: str) -> None:
    _run_single(ctx, "trace.into-beyond-record", build_native_command("TraceIntoBeyondTraceRecord", count))


@trace.command("into-record")
@click.argument("count", required=False, default="")
@click.pass_context
def trace_into_record(ctx: click.Context, count: str) -> None:
    _run_single(ctx, "trace.into-record", build_native_command("TraceIntoIntoTraceRecord", count))


@trace.command("over-until")
@click.argument("condition")
@click.option("--max-steps", default="", help="Optional maximum step count.")
@click.pass_context
def trace_over_until(ctx: click.Context, condition: str, max_steps: str) -> None:
    _run_single(ctx, "trace.over-until", build_native_command("tocnd", condition, max_steps))


@trace.command("over-beyond-record")
@click.argument("count", required=False, default="")
@click.pass_context
def trace_over_beyond_record(ctx: click.Context, count: str) -> None:
    _run_single(ctx, "trace.over-beyond-record", build_native_command("TraceOverBeyondTraceRecord", count))


@trace.command("over-record")
@click.argument("count", required=False, default="")
@click.pass_context
def trace_over_record(ctx: click.Context, count: str) -> None:
    _run_single(ctx, "trace.over-record", build_native_command("TraceOverIntoTraceRecord", count))


@trace.command("set-log")
@click.argument("text", required=False, default="")
@click.option("--condition", "log_condition", default="", help="Optional trace log condition.")
@click.pass_context
def trace_set_log(ctx: click.Context, text: str, log_condition: str) -> None:
    _run_single(
        ctx,
        "trace.set-log",
        build_native_command("TraceSetLog", quote_argument(text) if text else "", log_condition),
    )


@trace.command("set-command")
@click.argument("command_text", required=False, default="")
@click.option("--condition", "command_condition", default="", help="Optional trace command condition.")
@click.pass_context
def trace_set_command(ctx: click.Context, command_text: str, command_condition: str) -> None:
    _run_single(
        ctx,
        "trace.set-command",
        build_native_command("TraceSetCommand", quote_argument(command_text) if command_text else "", command_condition),
    )


@trace.command("set-log-file")
@click.argument("path")
@click.pass_context
def trace_set_log_file(ctx: click.Context, path: str) -> None:
    _run_single(ctx, "trace.set-log-file", build_native_command("TraceSetLogFile", quote_argument(path)))


@trace.command("run-to-user")
@click.pass_context
def trace_run_to_user(ctx: click.Context) -> None:
    _run_single(ctx, "trace.run-to-user", "rtu")


@trace.command("run-to-party")
@click.argument("party")
@click.pass_context
def trace_run_to_party(ctx: click.Context, party: str) -> None:
    _run_single(ctx, "trace.run-to-party", build_native_command("RunToParty", party))


@main.group()
def patch() -> None:
    """Memory patching helpers."""


@patch.command("byte")
@click.argument("address")
@click.argument("value")
@click.pass_context
def patch_byte(ctx: click.Context, address: str, value: str) -> None:
    """Patch a single byte at the specified address."""
    _run_single(ctx, "patch.byte", build_native_command("Fill", address, value))


@patch.command("word")
@click.argument("address")
@click.argument("value")
@click.pass_context
def patch_word(ctx: click.Context, address: str, value: str) -> None:
    """Patch a 16-bit word at the specified address."""
    _run_single(ctx, "patch.word", build_native_command("Fill", address, value, "word"))


@patch.command("dword")
@click.argument("address")
@click.argument("value")
@click.pass_context
def patch_dword(ctx: click.Context, address: str, value: str) -> None:
    """Patch a 32-bit dword at the specified address."""
    _run_single(ctx, "patch.dword", build_native_command("Fill", address, value, "dword"))


@patch.command("qword")
@click.argument("address")
@click.argument("value")
@click.pass_context
def patch_qword(ctx: click.Context, address: str, value: str) -> None:
    """Patch a 64-bit qword at the specified address."""
    _run_single(ctx, "patch.qword", build_native_command("Fill", address, value, "qword"))


@main.group()
def plugin() -> None:
    """Plugin load/unload/reload operations."""


@plugin.command("load")
@click.argument("path")
@click.pass_context
def plugin_load(ctx: click.Context, path: str) -> None:
    """Load a plugin from the specified PATH."""
    _run_single(ctx, "plugin.load", build_native_command("pluginload", quote_argument(path)))


@plugin.command("unload")
@click.argument("path")
@click.pass_context
def plugin_unload(ctx: click.Context, path: str) -> None:
    """Unload a plugin at the specified PATH."""
    _run_single(ctx, "plugin.unload", build_native_command("pluginunload", quote_argument(path)))


@plugin.command("reload")
@click.argument("path")
@click.option("--no-prompt", is_flag=True, default=False, help="Skip confirmation prompt during reload.")
@click.pass_context
def plugin_reload(ctx: click.Context, path: str, no_prompt: bool) -> None:
    """Reload a plugin at the specified PATH.

    This unloads and reloads the plugin. By default, x64dbg may show a
    confirmation dialog; use --no-prompt to skip if supported.
    """
    # pluginreload takes path and optional second arg to skip prompt
    if no_prompt:
        _run_single(ctx, "plugin.reload", build_native_command("pluginreload", quote_argument(path), "1"))
    else:
        _run_single(ctx, "plugin.reload", build_native_command("pluginreload", quote_argument(path)))


@main.group()
def misc() -> None:
    """Miscellaneous utility commands."""


@misc.command("meminfo")
@click.argument("mode")
@click.argument("address")
@click.argument("size", required=False, default="")
@click.pass_context
def misc_meminfo(ctx: click.Context, mode: str, address: str, size: str) -> None:
    """Query memory information at an address.

    MODE is 'a' for allocation info or 'r' for region info.
    ADDRESS is the memory address to query.
    SIZE is optional and specifies the size to query.
    """
    if size:
        _run_single(ctx, "misc.meminfo", build_native_command("meminfo", mode, f"{address},{size}"))
    else:
        _run_single(ctx, "misc.meminfo", build_native_command("meminfo", mode, address))


@misc.command("flushlog")
@click.pass_context
def misc_flushlog(ctx: click.Context) -> None:
    """Flush the log buffer to the GUI."""
    _run_single(ctx, "misc.flushlog", "flushlog")


@main.group()
def math() -> None:
    """Arithmetic and bitwise operations for register/variable manipulation."""


@math.command("inc")
@click.argument("arg1")
@click.pass_context
def math_inc(ctx: click.Context, arg1: str) -> None:
    """Increment a register or variable by 1."""
    _run_single(ctx, "math.inc", f"{arg1}++")


@math.command("dec")
@click.argument("arg1")
@click.pass_context
def math_dec(ctx: click.Context, arg1: str) -> None:
    """Decrement a register or variable by 1."""
    _run_single(ctx, "math.dec", f"{arg1}--")


@math.command("add")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_add(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Add ARG2 to ARG1 (ARG1 += ARG2)."""
    _run_single(ctx, "math.add", f"{arg1}+={arg2}")


@math.command("sub")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_sub(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Subtract ARG2 from ARG1 (ARG1 -= ARG2)."""
    _run_single(ctx, "math.sub", f"{arg1}-={arg2}")


@math.command("mul")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_mul(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Multiply ARG1 by ARG2 (ARG1 *= ARG2)."""
    _run_single(ctx, "math.mul", f"{arg1}*={arg2}")


@math.command("div")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_div(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Divide ARG1 by ARG2 (ARG1 /= ARG2)."""
    _run_single(ctx, "math.div", f"{arg1}/={arg2}")


@math.command("and")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_and(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Bitwise AND ARG2 into ARG1 (ARG1 &= ARG2)."""
    _run_single(ctx, "math.and", f"{arg1}&={arg2}")


@math.command("or")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_or(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Bitwise OR ARG2 into ARG1 (ARG1 |= ARG2)."""
    _run_single(ctx, "math.or", f"{arg1}|={arg2}")


@math.command("xor")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_xor(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Bitwise XOR ARG2 into ARG1 (ARG1 ^= ARG2)."""
    _run_single(ctx, "math.xor", f"{arg1}^={arg2}")


@math.command("not")
@click.argument("arg1")
@click.pass_context
def math_not(ctx: click.Context, arg1: str) -> None:
    """Bitwise NOT (invert all bits in ARG1)."""
    _run_single(ctx, "math.not", f"{arg1}=~{arg1}")


@math.command("neg")
@click.argument("arg1")
@click.pass_context
def math_neg(ctx: click.Context, arg1: str) -> None:
    """Negate ARG1 (two's complement)."""
    _run_single(ctx, "math.neg", f"{arg1}=-{arg1}")


@math.command("shl")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_shl(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Shift ARG1 left by ARG2 bits (ARG1 <<= ARG2)."""
    _run_single(ctx, "math.shl", f"{arg1}<<={arg2}")


@math.command("shr")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_shr(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Shift ARG1 right by ARG2 bits (ARG1 >>= ARG2)."""
    _run_single(ctx, "math.shr", f"{arg1}>>={arg2}")


@math.command("sar")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_sar(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Arithmetic shift ARG1 right by ARG2 bits (preserves sign)."""
    _run_single(ctx, "math.sar", f"{arg1}<<={arg2}")  # SAL same as SHL in x64dbg


@math.command("rol")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_rol(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Rotate ARG1 left by ARG2 bits."""
    _run_single(ctx, "math.rol", build_native_command("rol", arg1, arg2))


@math.command("ror")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def math_ror(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Rotate ARG1 right by ARG2 bits."""
    _run_single(ctx, "math.ror", build_native_command("ror", arg1, arg2))


@math.command("bswap")
@click.argument("arg1")
@click.pass_context
def math_bswap(ctx: click.Context, arg1: str) -> None:
    """Byte-swap ARG1 (reverse byte order)."""
    _run_single(ctx, "math.bswap", build_native_command("bswap", arg1))


@main.group()
def stack() -> None:
    """Stack manipulation operations."""


@stack.command("push")
@click.argument("value")
@click.pass_context
def stack_push(ctx: click.Context, value: str) -> None:
    """Push VALUE onto the stack."""
    _run_single(ctx, "stack.push", build_native_command("push", value))


@stack.command("pop")
@click.argument("dest", required=False, default="")
@click.pass_context
def stack_pop(ctx: click.Context, dest: str) -> None:
    """Pop a value from the stack into DEST (optional)."""
    if dest:
        _run_single(ctx, "stack.pop", build_native_command("pop", dest))
    else:
        _run_single(ctx, "stack.pop", "pop")


@main.group()
def compare() -> None:
    """Comparison operations that set flags."""


@compare.command("test")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def compare_test(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Test ARG1 AND ARG2 (sets $_EZ_FLAG, $_BS_FLAG)."""
    _run_single(ctx, "compare.test", build_native_command("test", arg1, arg2))


@compare.command("cmp")
@click.argument("arg1")
@click.argument("arg2")
@click.pass_context
def compare_cmp(ctx: click.Context, arg1: str, arg2: str) -> None:
    """Compare ARG1 with ARG2 (sets $_EZ_FLAG, $_BS_FLAG)."""
    _run_single(ctx, "compare.cmp", build_native_command("cmp", arg1, arg2))


@main.group()
def mov() -> None:
    """Move/copy value to destination."""


@mov.command("set")
@click.argument("dest")
@click.argument("src")
@click.pass_context
def mov_set(ctx: click.Context, dest: str, src: str) -> None:
    """Set DEST = SRC (register, memory, or variable)."""
    _run_single(ctx, "mov.set", build_native_command("mov", dest, src))


@main.group()
def raw() -> None:
    """Escape hatch for arbitrary native commands."""


@raw.command("exec")
@click.argument("command")
@click.pass_context
def raw_exec(ctx: click.Context, command: str) -> None:
    _run_single(ctx, "raw.exec", command)


@main.group()
def workflow() -> None:
    """Workflow-oriented helpers for fast-exit and artifact capture."""


@workflow.command("capture-init")
@click.argument("executable")
@click.argument("arguments", required=False, default="")
@click.option("--cwd", default="", help="Debuggee working directory.")
@click.option("--output-dir", required=True, help="Directory for the session log and manifest.")
@click.option("--save-db/--no-save-db", default=True, show_default=True, help="Persist a debugger database copy.")
@click.option("--minidump/--no-minidump", default=False, show_default=True, help="Capture a minidump into the output directory.")
@click.option("--timeout", default=30.0, show_default=True, type=float)
@click.pass_context
def workflow_capture_init(
    ctx: click.Context,
    executable: str,
    arguments: str,
    cwd: str,
    output_dir: str,
    save_db: bool,
    minidump: bool,
    timeout: float,
) -> None:
    state, headless = _resolve_settings(ctx)
    target = DebugTarget(executable=executable, arguments=arguments, cwd=cwd).normalized()
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "session.log"
    manifest_path = out_dir / "manifest.json"
    database_path = out_dir / "capture.dd64"
    minidump_path = out_dir / "capture.dmp"
    commands = [
        build_native_command(
            "init",
            quote_argument(target.executable),
            quote_argument(target.arguments) if target.arguments else "",
            quote_argument(target.cwd) if target.cwd else "",
        ),
        "state",
        "disasm cip",
        "bplist",
    ]
    if save_db:
        commands.append(build_native_command("dbsave", quote_argument(str(database_path))))
    if minidump:
        commands.append(build_native_command("minidump", quote_argument(str(minidump_path))))
    result = run_command_block(headless, commands, timeout=timeout)
    log_path.write_text(result.output, encoding="utf-8")
    markers = _capture_output_markers(result.output)
    manifest = {
        "target": target.to_dict(),
        "commands": commands,
        "log_path": str(log_path),
        "manifest_path": str(manifest_path),
        "database_copy": str(database_path) if save_db else "",
        "minidump_copy": str(minidump_path) if minidump else "",
        **markers,
    }
    manifest_payload = build_result(result.ok, "workflow.capture-init", command=result.command, output=result.output, **manifest)
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    state.apply(last_target=target.to_dict())
    state.save(ctx.obj["state_file"])
    emit(ctx, manifest_payload)


@workflow.command("capture-trace")
@click.argument("executable")
@click.argument("arguments", required=False, default="")
@click.option("--cwd", default="", help="Debuggee working directory.")
@click.option("--output-dir", required=True, help="Directory for the trace session outputs.")
@click.option("--trace-file", default="", help="Optional explicit trace output path.")
@click.option("--run-to-user", is_flag=True, help="Execute rtu before trace stepping.")
@click.option("--step-filter", default="", help="Optional trace step filter: none, user, or system.")
@click.option("--max-steps", default="", help="Optional count passed to trace record stepping.")
@click.option("--timeout", default=30.0, show_default=True, type=float)
@click.pass_context
def workflow_capture_trace(
    ctx: click.Context,
    executable: str,
    arguments: str,
    cwd: str,
    output_dir: str,
    trace_file: str,
    run_to_user: bool,
    step_filter: str,
    max_steps: str,
    timeout: float,
) -> None:
    state, headless = _resolve_settings(ctx)
    target = DebugTarget(executable=executable, arguments=arguments, cwd=cwd).normalized()
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "trace-session.log"
    manifest_path = out_dir / "trace-manifest.json"
    final_trace_path = Path(trace_file).expanduser() if trace_file else out_dir / "capture.trace64"
    commands = [
        build_native_command(
            "init",
            quote_argument(target.executable),
            quote_argument(target.arguments) if target.arguments else "",
            quote_argument(target.cwd) if target.cwd else "",
        ),
        build_native_command("StartRunTrace", quote_argument(str(final_trace_path))),
    ]
    if step_filter:
        commands.append(build_native_command("TraceSetStepFilter", step_filter))
    if run_to_user:
        commands.append("rtu")
    commands.extend(
        [
            build_native_command("TraceIntoIntoTraceRecord", max_steps),
            "state",
            "StopRunTrace",
        ]
    )
    result = run_command_block(headless, commands, timeout=timeout)
    log_path.write_text(result.output, encoding="utf-8")
    markers = _capture_output_markers(result.output)
    manifest = {
        "target": target.to_dict(),
        "commands": commands,
        "log_path": str(log_path),
        "manifest_path": str(manifest_path),
        "trace_file": str(final_trace_path),
        "run_to_user": run_to_user,
        "step_filter": step_filter,
        "max_steps": max_steps,
        **markers,
    }
    manifest_payload = build_result(result.ok, "workflow.capture-trace", command=result.command, output=result.output, **manifest)
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    state.apply(last_target=target.to_dict())
    state.save(ctx.obj["state_file"])
    emit(ctx, manifest_payload)


@main.command()
@click.option("--command", "commands", multiple=True, required=True, help="Native x64dbg command to execute.")
@click.option("--timeout", default=30.0, show_default=True, type=float)
@click.pass_context
def batch(ctx: click.Context, commands: tuple[str, ...], timeout: float) -> None:
    """Execute multiple commands inside one headless session."""
    _, headless = _resolve_settings(ctx)
    result = run_command_block(headless, list(commands), timeout=timeout)
    payload = build_result(result.ok, "batch", command=result.command, output=result.output, commands=list(commands))
    emit(ctx, payload)


@main.command()
@click.argument("project_path", required=False)
@click.pass_context
def repl(ctx: click.Context, project_path: str | None = None) -> None:
    """Interactive REPL wrapping the native headless backend."""
    _, headless = _resolve_settings(ctx)
    skin = ReplSkin("x64dbg", version=__version__)
    pt_session = skin.create_prompt_session()
    skin.print_banner()
    with HeadlessSession(headless) as backend:
        while True:
            try:
                line = skin.get_input(
                    pt_session,
                    project_name=Path(project_path).name if project_path else "",
                    modified=False,
                )
            except (EOFError, KeyboardInterrupt):
                click.echo()
                break
            line = line.strip()
            if not line:
                continue
            if line in {"quit", "exit"}:
                break
            if line == "help":
                click.echo("Commands: session, process, breakpoint, hwbp, membp, condbp, thread, memory, register, variable, analyze, script, symbols, os, database, search, userdb, watch, trace, workflow, raw, batch, quit")
                continue
            try:
                parts = shlex.split(line)
            except ValueError as exc:
                skin.error(str(exc))
                continue
            if parts[0] == "native":
                native = line.partition(" ")[2]
                click.echo(backend.execute(native).output)
                continue
            try:
                main.main(args=parts, prog_name="cli-anything-x64dbg", standalone_mode=False, obj=ctx.obj)
            except click.ClickException as exc:
                skin.error(exc.format_message())
            except SystemExit:
                pass
    skin.print_goodbye()


def _apply_error_handler(command: click.Command) -> None:
    if command.callback is not None:
        command.callback = handle_error(command.callback)
    if isinstance(command, click.Group):
        for child in command.commands.values():
            _apply_error_handler(child)


_apply_error_handler(main)


if __name__ == "__main__":
    main()
