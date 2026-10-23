---
name: foam-mesh
description: Generate OpenFOAM case files and verify mesh quality
globs:
alwaysApply: false
---

# Foam-Agent: Mesh Generation and Verification

Use this skill when the user wants to generate or verify an OpenFOAM mesh. Triggers: mesh, checkMesh, generate mesh, create mesh, mesh quality.

## Input

The user provides: `$ARGUMENTS`

This can be a new case description (will plan + generate) or a path to an existing case (will verify only).

## Workflow

### Step 1: Generate Case Files
If no case directory exists yet:
1. Call `plan` with the user requirement
2. Call `input_writer` with the plan fields to generate all case files
3. Report the case directory path

If a case directory already exists, skip to Step 2.

### Step 2: Check Mesh Quality
Call `foam_check_mesh` to verify mesh quality:
```
foam_check_mesh({ case_dir: "<case_dir>" })
```

### Step 3: Iterate if Needed
If mesh check fails (errors > 0 or quality thresholds not met):
1. Analyze the checkMesh output for specific issues (non-orthogonality, skewness, aspect ratio)
2. Adjust mesh parameters accordingly
3. Regenerate mesh via `input_writer` with updated parameters
4. Re-run `foam_check_mesh`
5. Repeat up to 3 iterations

### Hard Gate
**checkMesh must pass (0 errors, nonOrthogonality < 75, skewness < 20) before proceeding to solving.**

## Verification

- `foam_check_mesh` reports 0 errors
- Mesh quality metrics within acceptable ranges
- Case directory contains complete set of OpenFOAM files (0/, constant/, system/)
