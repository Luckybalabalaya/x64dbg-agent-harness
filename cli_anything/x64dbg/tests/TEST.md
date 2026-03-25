# TEST.md

## Part 1: Test Inventory Plan

- `test_core.py`: 100 unit tests planned
- `test_full_e2e.py`: 6 E2E tests planned

## Unit Test Plan

### `core/session.py`

- Functions/classes to test:
  - `SessionState.load`
  - `SessionState.save`
  - `SessionState.apply`
  - `SessionState.reset`
  - `SessionState.undo`
  - `SessionState.redo`
- Edge cases:
  - missing state file
  - undo/redo with empty stacks
  - persisted `last_target` structure
- Expected tests: 4

### `utils/x64dbg_backend.py`

- Functions/classes to test:
  - `quote_argument`
  - `build_native_command`
  - `find_headless`
  - `HeadlessSession.execute` with a fake backend
- Edge cases:
  - quoted paths
  - empty argument filtering
  - missing executable
  - command failure marker parsing
- Expected tests: 4

### `x64dbg_cli.py`

- Functions to test:
  - `_resolve_settings`
  - CLI JSON output paths
  - batch command composition
  - thread command composition
  - process control command composition
  - memory command composition
  - register command composition
  - variable command composition
  - conditional breakpoint command composition
  - trace command composition
  - analyze probe command composition
  - OS/misc command composition
  - symbols command composition
  - database command composition
  - hardware breakpoint command composition
  - memory breakpoint command composition
  - memory export command composition
  - search command composition
  - user database command composition, including bookmarks/functions/arguments
  - watch command composition
  - workflow helper manifest generation
  - workflow trace helper manifest generation
  - packaged SKILL.md coverage for current command groups
  - packaged SKILL.md YAML frontmatter validation
  - packaged SKILL.md install/discovery validation
- Edge cases:
  - configured session fallback
  - command sequencing
- Expected tests: 54

## E2E Test Plan

- Real workflows will invoke the actual `headless.exe` backend through the CLI.
- Output verification will check:
  - subprocess return codes
  - JSON payload structure
  - debugger output contains expected markers
  - generated debugger state lines are non-empty when applicable

## Realistic Workflow Scenarios

### Workflow: Session Configuration

- Simulates: first-time agent setup of the native backend
- Operations chained:
  - configure `headless.exe`
  - query session state
- Verified:
  - config persisted
  - reported backend path and architecture are correct

### Workflow: Debuggee Initialization

- Simulates: opening a real Windows target under the debugger
- Operations chained:
  - configure backend
  - `process init` on `notepad.exe`
  - `analyze state`
- Verified:
  - command succeeds
  - state output includes debugger addresses

### Workflow: Single-Session Batch Run

- Simulates: an agent executing a short reverse-engineering sequence in one debugger session
- Operations chained:
  - `init`
  - `breakpoint set`
  - `run`
  - `analyze state`
  - `breakpoint list`
- Verified:
  - entry breakpoint is visible
  - run output contains breakpoint hit markers or paused-state markers

### Workflow: Script Enumeration

- Simulates: an agent probing available script engines before automation
- Operations chained:
  - `script langs`
- Verified:
  - backend initializes
  - response is non-empty or returns successfully

### Workflow: Capture Helper

- Simulates: an agent collecting a fast-exit session artifact bundle in one command
- Operations chained:
  - configure backend
  - `workflow capture-init`
- Verified:
  - manifest path exists
  - session log path exists
  - JSON payload includes artifact locations

## Part 2: Test Results

### `pytest cli_anything/x64dbg/tests -q`

```text
........................................................................ [ 67%]
..................................                                       [100%]
106 passed in 7.21s
```

### `pytest cli_anything/x64dbg/tests/test_core.py -q`

```text
........................................................................ [ 67%]
..................................                                       [100%]
100 passed in 0.11s
```

### `pytest cli_anything/x64dbg/tests/test_full_e2e.py -q`

```text
......                                                                   [100%]
6 passed in 7.10s
```

### Installed CLI Smoke Tests

```text
cli-anything-x64dbg session show
headless=C:\Users\Administrator\x64dbg\bin\x64\headless.exe
arch=x64
source_root=C:\Users\Administrator\x64dbg
last_target=no target
undo=0 redo=0

cli-anything-x64dbg script langs
0:Default
1:Script DLL

cli-anything-x64dbg --json batch --command 'init "C:\Users\Administrator\Downloads\9\CrackMe_packed.exe"' --command state
ok=true
target=C:\Users\Administrator\Downloads\9\CrackMe_packed.exe
entry_breakpoint=0x00007FF69D5B7C70
process_exit=0x0
database=C:\Users\Administrator\x64dbg\bin\x64\headless\db\CrackMe_packed.exe.dd64
```

## Summary Statistics

- Total tests: 106
- Passed: 106
- Pass rate: 100%
- Full suite time: 7.21s
- Core suite time: 0.11s
- E2E suite time: 7.10s

## Coverage Notes

- One-shot command coverage is strong for configuration, expanded process control, thread wrappers, memory wrappers, register probes, variable helpers, hardware and memory breakpoints, conditional breakpoints, librarian breakpoints (`libbp`), exception breakpoints (`exbp`), search, user database wrappers (including loop annotations), watch wrappers, trace wrappers, workflow helpers, and batch workflows.
- Analyze group includes `asm` (assemble instruction at address) and `gpa` (get procedure address) for reverse-engineering automation.
- REPL behavior is validated structurally through the shared command implementation and `ReplSkin` integration, but not through an interactive PTY test.
- Batch mode returns the combined session log rather than perfectly segmented per-command results because x64dbg emits asynchronous debugger events that are not safely delimiter-aware in headless mode.
- Real installed-command smoke tests confirm that the packaged entry point, not just in-tree module execution, works against `headless.exe` and a fast-exit sample.
- Workflow helper coverage now verifies command composition, manifest generation, target-state persistence, marker extraction from a representative fast-exit log, and a real installed-command `capture-init` subprocess workflow.
