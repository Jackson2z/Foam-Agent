---
name: foam-rules
description: CFD simulation hard rules — checkMesh gate, 3-strike rollback, error diagnosis, convergence criteria, approval gate
globs:
alwaysApply: false
---

# Foam-Agent CFD Hard Rules

These rules are **mandatory** when working with OpenFOAM cases. Violation = stop and report.

## 1. checkMesh Gate

`foam_check_mesh` must return **0 errors** before entering the solve phase.

- checkMesh errors > 0 → **FORBIDDEN** to call `run`
- Must fix mesh first: adjust mesh parameters → regenerate → re-verify
- Non-orthogonality > 75° or skewness > 20 → flag as mesh quality warning

## 2. Three-Strike Rollback

When the **same error** (same category, same file) occurs **3 consecutive times** after `apply_fixes`:

1. **STOP** attempting more fixes on the current state
2. Call `foam_snapshot` to list recent checkpoints
3. Restore to the last known-good checkpoint
4. **Re-plan** the approach — do NOT repeat the same fix strategy

This mirrors the NullFlux V8 "招1" rule: 3 consecutive same-errors → mandatory rollback + re-plan.

## 3. Mandatory Error Diagnosis

Any `run` result containing `error`, `FOAM FATAL`, `Floating point`, `segfault`, `nan`, or non-zero exit code:

1. **FIRST action**: call `diagnose_error` with the error text
2. Follow the returned `next_steps` **in order** before making any new edits
3. `diagnose_error` returns `{category, causes, next_steps}` — execute sequentially
4. Only if `matched: false` → read the full log file manually

## 4. Convergence Criteria

Before declaring a simulation "complete", verify **all three**:

| Check | Criterion | How |
|-------|-----------|-----|
| Residuals | Continuity < 1e-3, momentum/energy < 1e-4 | `foam_residual_series` |
| Monitor points | Last 100 steps fluctuation < 1% | Read postProcessing data |
| Mass conservation | Inlet/outlet flow rate diff < 0.1% | Compute from results |

All three must pass. If any fails → the simulation is not converged.

## 5. Approval Gate

These operations require **explicit user confirmation** before execution:

- `run` (solver execution — consumes compute resources)
- `apply_fixes` (modifies case files)
- Any `foam_snapshot` restore (reverts file changes)

In auto-mode (`--auto` flag), these are auto-approved with logging.

## 6. Target: Foundation OpenFOAM v10

All tools target **Foundation OpenFOAM v10** (openfoam.org). File names, dictionary names, and solver binaries follow v10 conventions.

NOT compatible with ESI OpenFOAM (openfoam.com, e.g., v2312, v2406):
- v10: `constant/momentumTransport` → ESI: `constant/turbulenceProperties`
- v10: `constant/physicalProperties` → ESI: `constant/thermophysicalProperties`
- v10: `buoyantFoam` → ESI: `buoyantBoussinesqPimpleFoam`
