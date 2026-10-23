---
name: foam-review
description: Diagnose and fix OpenFOAM simulation errors with iterative correction loop
globs:
alwaysApply: false
---

# Foam-Agent: Error Diagnosis and Fix

Use this skill when the user needs to fix simulation errors. Triggers: fix, error, review, diagnose, debug, convergence issue, divergence, crash.

## Input

The user provides: `$ARGUMENTS`

Expected: a case directory path and (optionally) error output. If not provided, ask for the case directory.

## Workflow

### Step 1: Pattern-Match Error
Call `diagnose_error` for rule-based error pattern matching:
```
diagnose_error({ case_dir: "<case_dir>" })
```
This provides a quick diagnosis based on known error patterns.

### Step 2: LLM Analysis
Call `review` for deeper LLM-powered analysis:
```
review({ case_dir: "<case_dir>", user_requirement: "<original requirement>" })
```
Show the user the error analysis.

### Step 3: Apply Fixes
Call `apply_fixes` with the review analysis:
```
apply_fixes({ case_dir: "<case_dir>", review_analysis: "<from review>" })
```

### Step 4: Verify Fix
Call `run` to test the fix:
```
run({ case_dir: "<case_dir>", timeout: 3600 })
```

### Iteration Rules
- Max 5 iterations of the full review-fix-rerun loop
- If 3 consecutive iterations produce the same error, call `foam_snapshot` to rollback to last known good state, then report to user
- After 5 failed iterations, stop and report with a summary of all attempted fixes

## Verification

- Run completes successfully after fix
- Residuals show improvement compared to pre-fix state
- If unable to fix, provide clear summary of what was tried and suggest manual intervention
