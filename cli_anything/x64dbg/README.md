# cli-anything-x64dbg

`cli-anything-x64dbg` is a stateful CLI harness for x64dbg that wraps the native `headless.exe` backend instead of reimplementing debugger behavior.

## Prerequisites

- Python 3.10+
- A built x64dbg tree with `bin/<arch>/headless.exe`

## Installation

```powershell
cd C:\Users\Administrator\x64dbg\agent-harness
python -m pip install -e .
```

## Usage

### Configure the backend

```powershell
cli-anything-x64dbg session configure --headless C:\Users\Administrator\x64dbg\bin\x64\headless.exe --arch x64 --source-root C:\Users\Administrator\x64dbg
```

### Start the REPL

```powershell
cli-anything-x64dbg
```

### Run one-shot commands

```powershell
cli-anything-x64dbg --json process init C:\Windows\System32\notepad.exe
cli-anything-x64dbg process detach
cli-anything-x64dbg process run-skip-exceptions
cli-anything-x64dbg analyze state
cli-anything-x64dbg breakpoint list
cli-anything-x64dbg condbp condition 401000 "eax==1"
cli-anything-x64dbg thread suspend-all
cli-anything-x64dbg thread set-priority 1234 Normal
cli-anything-x64dbg memory alloc --size 1000
cli-anything-x64dbg memory minidump C:\temp\sample.dmp
cli-anything-x64dbg memory copy 402000 401000 40
cli-anything-x64dbg register get cip
cli-anything-x64dbg register dump --profile core
cli-anything-x64dbg register set cax 401000
cli-anything-x64dbg variable set-string msg "hello world"
cli-anything-x64dbg analyze image-info
cli-anything-x64dbg analyze dump 401000
cli-anything-x64dbg analyze recursive-analyse 401000
cli-anything-x64dbg analyze xrefs
cli-anything-x64dbg os hide-debugger
cli-anything-x64dbg os jit-set C:\jit\dbg.exe
cli-anything-x64dbg os enable-privilege SeDebugPrivilege
cli-anything-x64dbg hwbp set 401000 --type x --size 1
cli-anything-x64dbg membp set 401000 --type x
cli-anything-x64dbg search asm "mov eax, ebx"
cli-anything-x64dbg search refs-range 401000 402000
cli-anything-x64dbg search function-pointers 401000 --size 200
cli-anything-x64dbg search guids 401000 --size 200
cli-anything-x64dbg userdb comment-set 401000 "interesting branch"
cli-anything-x64dbg userdb bookmark-set 401000
cli-anything-x64dbg watch add "[rax]" --type uint
cli-anything-x64dbg watch set-watchdog 1 changed
cli-anything-x64dbg workflow capture-init C:\sample.exe --output-dir C:\temp\capture --minidump
cli-anything-x64dbg workflow capture-trace C:\sample.exe --output-dir C:\temp\trace --run-to-user --step-filter user --max-steps 5
cli-anything-x64dbg symbols unload ntdll
cli-anything-x64dbg database save C:\temp\session.dd64
cli-anything-x64dbg trace run-to-user
```

### Run a single-session workflow

```powershell
cli-anything-x64dbg --json batch ^
  --command "init \"C:\Windows\System32\notepad.exe\"" ^
  --command "bp cip, \"entry\"" ^
  --command "run" ^
  --command "state"
```

## Command Groups

- `session`: configure and inspect CLI session state
- `process`: start, attach, detach, continue, run with exception policies, stop, and step the debuggee
- `breakpoint`: set, list, enable, disable, and delete INT3 breakpoints
- `hwbp`: set, delete, enable, disable, and condition hardware breakpoints
- `membp`: set, delete, enable, disable, and condition memory breakpoints
- `condbp`: configure software breakpoint conditions, logs, commands, and hit counters
- `thread`: switch, suspend, resume, kill, naming, priority, and bulk thread control
- `memory`: allocate, free, save, minidump, fill, copy, and inspect page rights
- `register`: read, mutate, copy, and single-session dump core/debug register sets
- `variable`: integer and string variable helpers
- `analyze`: inspect debugger state, memory/stack dumps, deeper analysis passes, disassembly position, and xref analysis
- `os`: privilege, loader, anti-debug, handle/window, and JIT helpers
- `symbols`: load and unload symbol files for modules
- `database`: save, load, and clear the program database
- `search`: byte/asm/reference/xref/string/GUID search helpers
- `userdb`: comments, labels, bookmarks, functions, and arguments in the user database
- `watch`: watch expressions and watchdog control
- `workflow`: single-session capture and trace helpers for fast-exit targets
- `script`: enumerate script engines, load scripts, and run them
- `trace`: trace recording, trace-record stepping, conditional tracing, trace logs, and run-to-user/party helpers
- `raw`: execute an arbitrary native x64dbg command
- `batch`: execute multiple native commands inside one headless session
- `repl`: interactive shell; also the default behavior

## Output Modes

- Human-readable output by default
- Machine-readable JSON with `--json`

## Limitations

- One-shot commands start a fresh `headless.exe` process, so debugger runtime state does not persist across separate CLI invocations
- Use `batch` or the REPL for multi-step debugging workflows; `batch` returns the combined session log for the full command block
- `workflow capture-init` and `workflow capture-trace` still rely on the combined session log model; they improve artifact capture and manifest generation, not x64dbg headless event ordering
- `session undo/redo` manages CLI configuration state, not the target program state
