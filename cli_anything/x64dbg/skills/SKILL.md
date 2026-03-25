---
name: >-
  cli-anything-x64dbg
description: >-
  Stateful x64dbg headless CLI for debugger control, breakpointing, memory and
  state inspection, workflow capture, and reverse-engineering automation.
---

# cli-anything-x64dbg

Use this CLI when you need to drive `x64dbg` without the GUI. It wraps the real
`headless.exe` backend and is designed for agent workflows that need
machine-readable output, single-session command blocks, and artifact capture for
fast-exit targets.

## Installation

This CLI is installed from the packaged harness:

```powershell
python -m pip install -e C:\Users\Administrator\x64dbg\agent-harness
```

**Prerequisites:**
- Python 3.10+
- A built x64dbg checkout with `bin/x64/headless.exe` or `bin/x32/headless.exe`
- Windows target binaries to debug

## First-Time Setup

Configure the saved backend state before using one-shot commands:

```powershell
cli-anything-x64dbg session configure `
  --headless C:\Users\Administrator\x64dbg\bin\x64\headless.exe `
  --arch x64 `
  --source-root C:\Users\Administrator\x64dbg
```

Verify the saved session:

```powershell
cli-anything-x64dbg session show
```

## Command Groups

### `session`

Manage saved CLI state.

- `show`
- `configure`
- `reset`
- `undo`
- `redo`

### `process`

Control the target lifecycle and stepping.

- `init`
- `attach`
- `detach`
- `run`
- `run-skip-exceptions`
- `run-swallow-exception`
- `pause`
- `continue`
- `stop`
- `step-into`
- `step-into-skip-exceptions`
- `step-into-swallow-exception`
- `step-over`
- `step-over-skip-exceptions`
- `step-over-swallow-exception`
- `step-out`
- `step-out-skip-exceptions`
- `skip`
- `step-user`
- `step-system`
- `cmdline-get`
- `cmdline-set`

### `breakpoint`, `hwbp`, `membp`, `condbp`, `libbp`, `exbp`

Set and manage software, hardware, memory, librarian, exception, and conditional breakpoints.

- `breakpoint`: `set`, `list`, `delete`, `enable`, `disable`
- `hwbp`: `set`, `delete`, `enable`, `disable`, `condition`
- `membp`: `set`, `delete`, `enable`, `disable`, `condition`
- `condbp`: `condition`, `log`, `command`, `hit-count`, `reset-hit-count`
- `libbp`: `set`, `delete`, `enable`, `disable`, `condition` — DLL load/unload breakpoints
- `exbp`: `set`, `delete`, `enable`, `disable` — exception breakpoints (access violation, etc.)

### `thread`

Thread selection and control.

- `switch`
- `suspend`
- `resume`
- `kill`
- `suspend-all`
- `resume-all`
- `set-priority`
- `set-name`

### `memory`

Memory allocation, export, and protection changes.

- `alloc`
- `free`
- `save`
- `minidump`
- `fill`
- `copy`
- `rights-get`
- `rights-set`

### `register`

Read and mutate register state with thin wrappers over native expressions and
`mov`, plus a one-session dump helper for the core/debug register profiles.

- `get`
- `set`
- `copy`
- `dump`

### `variable`

Create debugger variables and string variables.

- `new`
- `delete`
- `list`
- `set-string`
- `get-string`
- `copy-string`

### `analyze`

State and memory/stack probes.

- `state`
- `disasm`
- `dump`
- `stack-dump`
- `memmap-dump`
- `print-stack`
- `image-info`
- `reloc-size`
- `exception-info`
- `exception-handlers`
- `virtual-module`
- `xrefs`
- `analyse`
- `exception-analyse`
- `cf-analyse`
- `recursive-analyse`
- `advanced-analyse`
- `asm` — assemble an instruction at an address
- `gpa` — get procedure address (resolve exported function)

### `os`

OS, loader, anti-debug, and JIT helpers.

- `hide-debugger`
- `privilege-state`
- `enable-privilege`
- `disable-privilege`
- `loadlib`
- `freelib`
- `close-handle`
- `enable-window`
- `disable-window`
- `jit-get`
- `jit-set`
- `jit-get-auto`
- `jit-set-auto`

### `symbols`

Module symbol management.

- `load`
- `unload`

### `database`

Persist and restore debugger database state.

- `save`
- `load`
- `clear`

### `search`

Reference and pattern search helpers.

- `set-max-results`
- `bytes`
- `bytes-all`
- `memory-all`
- `asm`
- `refs`
- `refs-range`
- `strings`
- `function-pointers`
- `module-calls`
- `guids`

### `userdb`

User database annotations and structure metadata.

- comments: `comment-set`, `comment-delete`, `comment-list`, `comment-clear`
- labels: `label-set`, `label-delete`, `label-list`, `label-clear`
- bookmarks: `bookmark-set`, `bookmark-delete`, `bookmark-list`, `bookmark-clear`
- functions: `function-add`, `function-delete`, `function-list`, `function-clear`
- arguments: `argument-add`, `argument-delete`, `argument-list`, `argument-clear`
- loops: `loop-add`, `loop-delete`, `loop-list`, `loop-clear`

### `watch`

Watch expressions and watchdog controls.

- `add`
- `delete`
- `set-expression`
- `set-name`
- `set-type`
- `set-watchdog`
- `check-watchdog`

### `trace`

Trace recording and trace control.

- `start-recording`
- `stop-recording`
- `into-until`
- `over-until`
- `set-log`
- `set-command`
- `set-log-file`
- `run-to-user`
- `run-to-party`

### `workflow`

Higher-level single-session helpers for fast-exit targets.

- `capture-init`
- `capture-trace`

### `plugin`

Plugin load/unload/reload operations.

- `load`: load a plugin from path
- `unload`: unload a plugin
- `reload`: reload a plugin (optionally skip prompt with `--no-prompt`)

### `misc`

Miscellaneous utility commands.

- `meminfo`: query memory information (mode, address, optional size)
- `flushlog`: flush the log buffer

### `math`

Arithmetic and bitwise operations for register/variable manipulation.

- `inc`, `dec`: increment/decrement by 1
- `add`, `sub`, `mul`, `div`: arithmetic operations
- `and`, `or`, `xor`, `not`, `neg`: bitwise/logical operations
- `shl`, `shr`, `sar`: shift operations
- `rol`, `ror`: rotate operations
- `bswap`: byte-swap (reverse byte order)

### `stack`

Stack manipulation operations.

- `push`: push a value onto the stack
- `pop`: pop a value from the stack (optional destination)

### `compare`

Comparison operations that set flags.

- `test`: bitwise AND test (sets `$_EZ_FLAG`, `$_BS_FLAG`)
- `cmp`: compare values (sets `$_EZ_FLAG`, `$_BS_FLAG`)

### `mov`

Move/copy value to destination.

- `set`: move value to register/memory/variable

### `raw`, `batch`, `repl`

Escape hatches and orchestration modes.

- `raw exec`: send a native x64dbg command directly
- `batch`: run several native commands in one headless session
- `repl`: interactive shell; also the default behavior

## Examples

### Human-readable probing

```powershell
cli-anything-x64dbg process init C:\Windows\System32\notepad.exe
cli-anything-x64dbg analyze state
cli-anything-x64dbg analyze disasm
cli-anything-x64dbg breakpoint list
```

### JSON automation

```powershell
cli-anything-x64dbg --json process init C:\Windows\System32\notepad.exe
cli-anything-x64dbg --json script langs
cli-anything-x64dbg --json search asm "mov eax, ebx"
cli-anything-x64dbg --json workflow capture-init C:\Windows\System32\notepad.exe --output-dir C:\temp\capture
```

### Register probing

```powershell
cli-anything-x64dbg register get cip
cli-anything-x64dbg register dump --profile core
cli-anything-x64dbg register set cax 401000
```

### Single-session batch workflow

```powershell
cli-anything-x64dbg --json batch `
  --command 'init "C:\Windows\System32\notepad.exe"' `
  --command 'bp cip, "entry"' `
  --command run `
  --command state `
  --command bplist
```

### Fast-exit target capture

```powershell
cli-anything-x64dbg --json workflow capture-init `
  C:\Users\Administrator\Downloads\9\CrackMe_packed.exe `
  --output-dir C:\Users\Administrator\codex_tmp\workflow-capture
```

### Fast-exit trace capture

```powershell
cli-anything-x64dbg --json workflow capture-trace `
  C:\Users\Administrator\Downloads\9\CrackMe_packed.exe `
  --output-dir C:\Users\Administrator\codex_tmp\trace-capture `
  --run-to-user `
  --step-filter user `
  --max-steps 5
```

### Variable and user database automation

```powershell
cli-anything-x64dbg variable set-string msg "hello world"
cli-anything-x64dbg userdb comment-set 401000 "interesting branch"
cli-anything-x64dbg userdb bookmark-set 401000
```

## REPL Guidance

Start the CLI without a subcommand:

```powershell
cli-anything-x64dbg
```

In the REPL:

- Type `help` for top-level groups
- Type `native <x64dbg command>` to send a raw backend command directly
- Type `quit` or `exit` to leave

## For AI Agents

1. Prefer `--json` for programmatic use.
2. Use `batch` or `workflow capture-init` for multi-step flows; one-shot invocations do not share runtime debug state.
3. Use absolute Windows paths for debuggees, scripts, dumps, and exported artifacts.
4. Treat symbol-loading noise as informational unless `ok=false` or `[FAIL]` appears.
5. For fast-exit samples, prefer `workflow capture-init` or `workflow capture-trace` over separate `init/state/disasm` calls.
6. Validate success with `ok`, expected markers like `cip:`, `cip=...`, or breakpoint lines, and existence of exported files such as `manifest.json`, `.dd64`, `.dmp`, or `.trace64`.

## Limitations

- One-shot commands start a fresh `headless.exe`, so runtime debugger state does not persist across separate CLI invocations.
- `batch` returns the combined session log for the full command block because x64dbg emits asynchronous events after command dispatch.
- `workflow capture-init` improves artifact capture and manifest generation, but it still relies on the combined session log model.
