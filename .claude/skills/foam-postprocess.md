---
name: foam-postprocess
description: Visualize and extract results from completed OpenFOAM simulations
globs:
alwaysApply: false
---

# Foam-Agent: Post-processing and Visualization

Use this skill when the user wants to visualize or post-process simulation results. Triggers: postprocess, visualize, plot, render, contour, results.

## Input

The user provides: `$ARGUMENTS`

Expected: a case directory path and the quantity to visualize (e.g., pressure, velocity, temperature). If no quantity is specified, ask the user.

## Workflow

### Step 1: Generate Visualization
Call the `visualization` MCP tool:
```
visualization({
  case_dir: "<case_dir>",
  quantity: "<e.g., pressure, velocity, temperature>"
})
```
Report the generated visualization files and their paths.

### Step 2: Handle Failure
If visualization fails:
1. Analyze the error output
2. Retry once with adjusted parameters (e.g., different quantity, time step, or format)
3. If still fails, report the error and suggest manual post-processing with ParaView

### Step 3: Report Artifacts
List all generated artifacts:
- Image files (PNG/SVG)
- Data files (CSV/VTK)
- Summary statistics if extracted

## Verification

- Visualization files are generated and non-empty
- Output paths are reported to the user
- File sizes are reasonable (not zero-length)
