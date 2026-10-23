---
name: foam-solve
description: Run OpenFOAM solver with pre-run checkpoint and convergence monitoring
globs:
alwaysApply: false
---

# Foam-Agent: Solver Execution

Use this skill when the user wants to run an OpenFOAM simulation. Triggers: solve, run, start simulation, compute, calculate.

## Input

The user provides: `$ARGUMENTS`

Expected: a case directory path. If not provided, ask the user for the case directory.

## Workflow

### Step 1: Pre-run Checkpoint
Call `foam_snapshot` to create a checkpoint before running:
```
foam_snapshot({ case_dir: "<case_dir>", label: "pre-run" })
```
This allows rollback if the solve fails catastrophically.

### Step 2: Run Solver
Call the `run` MCP tool:
```
run({ case_dir: "<case_dir>", timeout: 3600 })
```
Report the status (success/failed) and any error output.

### Step 3: Error Handling
If the run fails:
- Auto-route to `foam-review` skill for diagnosis and fix
- Do not manually debug; delegate to the review workflow

### Step 4: Convergence Check
If the run succeeds, call `foam_residual_series` to verify convergence:
```
foam_residual_series({ case_dir: "<case_dir>" })
```
Report the final residual levels and convergence status.

## Verification

- Solver completes without errors
- Residuals meet convergence criteria: continuity < 1e-3, momentum/energy < 1e-4
- If convergence is insufficient, suggest extending iterations or adjusting controls
