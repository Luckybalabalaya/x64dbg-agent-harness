# X64DBG Harness

## Target

- Software: x64dbg
- Source path: `C:\Users\Administrator\x64dbg`
- Harness path: `C:\Users\Administrator\x64dbg\agent-harness`
- Native backend: `C:\Users\Administrator\x64dbg\bin\x64\headless.exe`

## Phase 1 Inventory

- Existing harness commands: none
- Existing harness tests: none
- Native CLI/backend surface:
  - `headless.exe` provides a persistent stdin command loop
  - Built-in probe commands: `state`, `langs`, `exit`
  - All other operations reuse x64dbg's documented command system
- Useful x64dbg domains:
  - debug control: `init`, `attach`, `run`, `pause`, `stop`, `StepInto`, `StepOver`
  - breakpoint control: `bp`, `bplist`, `bpc`, `bpe`, `bpd`
  - GUI/probe helpers: `disasm`
  - misc: `getcommandline`, `setcommandline`
  - script: `scriptload`, `scriptrun`

## Gap Analysis

This clean rebuild starts from an empty harness, so every harness capability is a gap. The high-impact gaps are:

1. No installable CLI entry point for `headless.exe`
2. No stateful REPL wrapping the native debugger command loop
3. No JSON-capable output for agent consumption
4. No persistent session configuration for backend path and architecture
5. No curated command groups for common x64dbg workflows
6. No documented test plan, subprocess tests, or HARNESS validation record

## Command Design

- `session`: configure/show/reset/undo/redo
- `process`: init/attach/detach/run/run-skip-exceptions/run-swallow-exception/pause/continue/stop/step-into/step-into-skip-exceptions/step-into-swallow-exception/step-over/step-over-skip-exceptions/step-over-swallow-exception/step-out/step-out-skip-exceptions/skip/step-user/step-system/cmdline-get/cmdline-set
- `breakpoint`: set/list/delete/enable/disable
- `hwbp`: set/delete/enable/disable/condition
- `membp`: set/delete/enable/disable/condition
- `condbp`: software breakpoint conditions, logs, commands, hit counters
- `thread`: switch/suspend/resume/kill/suspend-all/resume-all/set-priority/set-name
- `memory`: alloc/free/save/minidump/fill/copy/rights-get/rights-set
- `register`: get/set/copy/dump
- `variable`: new/delete/list/set-string/get-string/copy-string
- `analyze`: state/disasm/dump/stack-dump/memmap-dump/print-stack/image-info/reloc-size/exception-info/exception-handlers/virtual-module/xrefs/analyse/exception-analyse/cf-analyse/recursive-analyse/advanced-analyse
- `os`: hide-debugger/privilege-state/enable-privilege/disable-privilege/loadlib/freelib/close-handle/enable-window/disable-window/jit-get/jit-set/jit-get-auto/jit-set-auto
- `symbols`: load/unload
- `database`: save/load/clear
- `search`: set-max-results/bytes/bytes-all/memory-all/asm/refs/refs-range/strings/function-pointers/module-calls/guids
- `userdb`: comment-set/comment-delete/comment-list/comment-clear/label-set/label-delete/label-list/label-clear/bookmark-set/bookmark-delete/bookmark-list/bookmark-clear/function-add/function-delete/function-list/function-clear/argument-add/argument-delete/argument-list/argument-clear
- `watch`: add/delete/set-expression/set-name/set-type/set-watchdog/check-watchdog
- `workflow`: capture-init and capture-trace for fast-exit session logging, manifest generation, optional database copy, optional minidump, and trace artifacts
- `script`: langs/load/run
- `trace`: start-recording/stop-recording/set-step-filter/into-until/into-beyond-record/into-record/over-until/over-beyond-record/over-record/set-log/set-command/set-log-file/run-to-user/run-to-party
- `raw`: execute an arbitrary native x64dbg command
- `batch`: execute multiple debugger commands in a single headless session
- `repl`: default interactive mode using `ReplSkin`

## Architecture

### CLI Entry Point

- `cli_anything.x64dbg.x64dbg_cli:main` is the Click root command exposed by `cli-anything-x64dbg`.
- Global options populate `ctx.obj` with JSON mode, session state path, headless path override, architecture, and source-root override.
- When no subcommand is provided, `main` falls through to `repl`, making the interactive shell the default execution path.
- Command callbacks are wrapped centrally with `handle_error`, which converts `RuntimeError` and unexpected exceptions into consistent `click.ClickException` failures.

### Core State Management

- `core/session.py` owns persistent CLI state through `SessionConfig` and `SessionState`.
- `SessionState.load()` and `save()` persist the active debugger configuration, the last target, and undo/redo history in the session JSON file.
- `core/project.py` models debugger targets with `DebugTarget` and now provides project helpers for create/open/save/info/list-profile operations around that same target shape.
- `core/export.py` standardizes result payloads through `build_result()`, `emit()`, and `render()`, so commands can produce both human-readable output and stable JSON responses.

### Backend Wrapper

- `utils/x64dbg_backend.py` is the boundary to the real debugger backend.
- `find_headless()` resolves the correct `headless.exe` path from explicit CLI input or the configured source tree.
- `HeadlessSession` maintains a persistent stdin/stdout session for multi-command flows such as `batch`, `register dump`, and workflow capture helpers.
- One-shot commands use `run_one_shot()` while workflow helpers and other grouped operations use `run_command_block()` to keep related commands inside a single debugger session.

### REPL Flow

- `repl` resolves backend settings once, creates a `ReplSkin`, and opens a single `HeadlessSession`.
- User input is tokenized with `shlex.split()` and dispatched back into the Click command tree via `main.main(..., standalone_mode=False, obj=ctx.obj)`.
- `native ...` lines bypass the Click wrappers and execute directly against the live backend session.
- `help`, `quit`, parse failures, and `click.ClickException` cases are handled in the loop so the REPL stays alive while surfacing errors clearly.

## Validation Checklist

- Namespace package layout: complete
- `setup.py` installable entry point: complete
- `--json` output mode: complete
- REPL default path with `ReplSkin`: complete
- `TEST.md` plan/results: complete
- `skills/SKILL.md`: complete

## Validation Results

### HARNESS-aligned items

- `cli_anything.x64dbg` namespace package layout is present
- `setup.py` exposes `cli-anything-x64dbg`
- `core/project.py`, `core/session.py`, and `core/export.py` exist
- Native backend wrapper lives in `utils/x64dbg_backend.py`
- `utils/repl_skin.py` is copied from the plugin and used by the default REPL
- `tests/TEST.md` contains both Part 1 planning and Part 2 executed results
- `skills/SKILL.md` exists inside the installed package path
- `skills/SKILL.md` has been regenerated to reflect the current command surface instead of the early minimal harness
- Real backend tests run against `C:\Users\Administrator\x64dbg\bin\x64\headless.exe`

### Verification Commands Run

- `python -m compileall C:\Users\Administrator\x64dbg\agent-harness`
- `pytest ...\test_core.py -q`
- `pytest ...\test_full_e2e.py -q`
- `python -m pip install --user -e C:\Users\Administrator\x64dbg\agent-harness`
- `cli-anything-x64dbg session configure --headless C:\Users\Administrator\x64dbg\bin\x64\headless.exe --arch x64 --source-root C:\Users\Administrator\x64dbg`
- `cli-anything-x64dbg session show`
- `cli-anything-x64dbg script langs`
- `cli-anything-x64dbg --json batch --command 'init "C:\Users\Administrator\Downloads\9\CrackMe_packed.exe"' --command state`
- `python C:\Users\Administrator\CLI-Anything\cli-anything-plugin\skill_generator.py C:\Users\Administrator\x64dbg\agent-harness -o C:\Users\Administrator\codex_tmp\generated-SKILL.md`

### Residual Limitations

- One-shot subcommands intentionally do not preserve debugger runtime state across separate CLI invocations.
- `batch` returns the combined headless session log instead of perfectly sliced per-command logs because x64dbg emits asynchronous events after command dispatch.
- Real backend pytest coverage still centers on `notepad.exe`; attach flows, script execution from file, and x32-specific behavior are not yet in automated regression.
- Real installed-command smoke coverage now includes `CrackMe_packed.exe`, but it is a fast-exit sample and therefore validates initialization and log capture more than deep trace progression.

## Refine Gap Analysis

### Current Inventory

- Covered command groups:
  - `session`
  - `process`
  - `breakpoint`
  - `hwbp`
  - `membp`
  - `condbp`
  - `thread`
  - `memory`
  - `register`
  - `variable`
  - `analyze`
  - `os`
  - `symbols`
  - `database`
  - `search`
  - `userdb`
  - `watch`
  - `workflow`
  - `script`
  - `trace`
  - `raw`
  - `batch`
  - `repl`
- Covered test surface:
  - core/session persistence
- command composition for expanded process control, thread, memory, register, variable, conditional breakpoint, trace, analysis, symbols, os/misc, database, hardware breakpoints, memory breakpoints, search, expanded user database, watch wrappers, and workflow helpers
  - packaged `SKILL.md` coverage for current command groups and workflow guidance
  - real backend subprocess coverage for help, configuration, `script langs`, `process init`, one batch workflow, `workflow capture-init`, and installed-command smoke tests against a fast-exit sample

### Remaining Native Domains Not Yet Exposed

- Additional register-aware trace helpers and richer register export bundles beyond the current core/debug dump helper
- Additional analysis commands: module/register-focused probes beyond the current xref coverage
- Additional OS and misc commands beyond current privilege, loader, anti-debug, handle/window, and JIT wrappers
- Register-aware trace helpers and trace output collection beyond the current capture wrappers
- Multi-artifact export bundles beyond `capture-init` and `capture-trace`

### Gaps Observed From Real Workflows

1. Session log fidelity gap
   - `headless.exe` emits asynchronous debug events after command dispatch.
   - Result: `batch` is reliable as a combined session log, but not as a true per-command transcript.
   - Impact: high for reverse-engineering workflows that need stable checkpoints around breakpoint hits, trace stops, and rapid process exit.

2. Fast-exit sample workflow gap
   - In real `CrackMe_packed.exe` runs, the process reaches the configured entry breakpoint but exits quickly in headless mode.
   - Result: `workflow capture-init` and `workflow capture-trace` now collect single-session logs, manifests, optional artifacts, and can be paired with the new register probes, but richer trace-progression helpers are still missing.
   - Impact: high for malware/crackme analysis.

3. Probe coverage gap
   - The CLI now wraps image info, exception info, exception handlers, dump/stack helpers, first-class register probes, deeper analysis passes, virtual modules, xref analysis, richer search helpers, variable helpers, and watch/watchdog controls, but still lacks richer register-aware trace/state bundles.
   - Impact: high because agents need inspect-before-mutate probes to reason safely.

4. Artifact export gap
   - The CLI can save arbitrary memory ranges, produce minidumps, and write a `capture-init` manifest bundle, but it does not yet assemble richer multi-step export bundles.
   - Impact: medium-high for unpacking, crash triage, and offline comparison.

5. Test realism gap
   - Real E2E coverage still centers on `notepad.exe`.
   - There is installed-command smoke coverage for `CrackMe_packed.exe`, but no automated regression yet for attach flows, x32, script files, or fast-exit targets.
   - Impact: medium-high because current wrappers exceed current real-backend coverage.

### Priority Recommendation

1. Improve session/event capture for fast-exit and asynchronous workflows
2. Add richer workflow-oriented export helpers for fast-exit targets
3. Expand register-aware trace/state bundles
4. Expand real E2E coverage beyond `notepad.exe`, including automated fast-exit and trace-oriented workflows
