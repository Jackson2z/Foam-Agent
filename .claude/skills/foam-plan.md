---
name: foam-plan
description: Plan an OpenFOAM CFD case from a natural language requirement
globs:
alwaysApply: false
---

# Foam-Agent: Case Planning

Use this skill when the user wants to plan or create a new CFD case. Triggers: plan, create case, set up simulation, new case.

## Input

The user provides: `$ARGUMENTS`

If no arguments are provided, ask the user to describe their CFD simulation requirements (e.g., "Simulate lid-driven cavity flow at Re=1000").

## Workflow

### Step 1: Generate Plan
Call the `plan` MCP tool with the user's requirement:
```
plan({ user_requirement: "<user's description>" })
```

### Step 2: Review and Confirm
Show the user the planned case name, solver, domain, category, and subtask list. Ask for confirmation before proceeding.

### Step 3: Branch
- If confirmed: inform the user the plan is ready. The user may proceed with `foam-mesh` to generate case files and mesh.
- If rejected: ask for modifications and re-run `plan` with updated requirements.

## Verification

- Plan output contains: case_name, case_solver, case_domain, case_category, subtasks
- User has explicitly confirmed the plan before any file generation

## Notes

- This targets Foundation OpenFOAM v10 exclusively
- Always show the full plan to the user before proceeding
