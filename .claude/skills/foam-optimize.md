---
name: foam-optimize
description: Parameter sweeps, sensitivity analysis, and boundary layer optimization for OpenFOAM
globs:
alwaysApply: false
---

# Foam-Agent: Optimization and Parameter Studies

Use this skill when the user wants to run parameter studies or optimize simulation settings. Triggers: optimize, parameter sweep, DOE, y+, sensitivity, parametric, mesh refinement.

## Input

The user provides: `$ARGUMENTS`

Expected: a base case description or path, and the parameters to vary. If not provided, ask for the parameter space definition.

## Workflow

### Step 1: Boundary Layer Sizing (if applicable)
If the study involves near-wall resolution or y+ requirements:
```
foam_yplus({ Re: <Reynolds_number>, L: <characteristic_length>, yplus_target: <target> })
```
Use the output to determine first cell height and growth ratio.

### Step 2: Define Parameter Space
Work with the user to define:
- Parameters to vary and their ranges
- Number of levels or specific values
- Key performance indicators (KPIs) to extract

### Step 3: Run Parameter Sweep
For each parameter combination:
1. Call `input_writer` with the modified parameters
2. Call `foam_snapshot` with label identifying the parameter set
3. Call `run` to execute the simulation
4. Extract KPIs from results

### Step 4: Compare Results
Present a comparison table or summary of KPIs across all parameter sets. Highlight optimal configurations.

## Verification

- All parameter combinations complete (or failures are documented)
- KPIs are extracted consistently across runs
- Results comparison is presented in a structured format
