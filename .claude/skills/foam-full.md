---
name: foam-full
description: Complete end-to-end OpenFOAM CFD simulation from requirement to results
globs:
alwaysApply: false
---

# Foam-Agent: Full Simulation Pipeline

Use this skill when the user wants a complete CFD simulation from start to finish. Triggers: full simulation, end-to-end, complete run, from scratch, CFD simulation.

This skill orchestrates the entire pipeline: plan, mesh, solve, error correction, and post-processing.

## Input

The user provides: `$ARGUMENTS`

If no arguments are provided, ask the user to describe their CFD simulation requirements (e.g., "Simulate lid-driven cavity flow at Re=1000").

## Workflow

### Phase 1: Plan
1. Call `plan` with the user requirement
2. Show the plan and get user confirmation
3. If not confirmed, iterate until approved

### Phase 2: Mesh
1. Call `input_writer` with confirmed plan fields to generate case files
2. Call `foam_check_mesh` to verify mesh quality
3. **Hard gate**: mesh must pass checkMesh (0 errors) before proceeding
4. If mesh fails, adjust and regenerate (up to 3 iterations)

### Phase 3: Solve
1. Call `foam_snapshot` with label "pre-solve" for checkpoint
2. Call `run` to execute the solver
3. If run fails, enter the review loop (Phase 4)

### Phase 4: Review Loop (only if errors)
1. Call `diagnose_error` for pattern matching
2. Call `review` for LLM analysis
3. Call `apply_fixes` with review results
4. Call `run` to verify
5. Max 5 iterations; if 3 consecutive same errors, rollback via `foam_snapshot`

### Phase 5: Post-process
1. Call `foam_residual_series` to verify convergence
2. Call `visualization` for requested quantities
3. Report all generated artifacts

## Verification

- Plan confirmed by user
- Mesh passes checkMesh with 0 errors
- Solver completes successfully
- Residuals meet convergence criteria (continuity < 1e-3)
- Visualization artifacts generated

## Notes

- Targets Foundation OpenFOAM v10 exclusively
- Report progress at each phase
- If any phase fails after retries, explain clearly and suggest manual intervention
