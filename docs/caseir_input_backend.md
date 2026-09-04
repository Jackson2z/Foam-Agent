# CaseIR input backend boundary

Tracked in Jackson2z/urban-uif-workspace#5 because Issues are disabled here.
Governed by urban-uif-workspace ADR-0001.

## Decision

Foam-Agent owns OpenFOAM-native input emission:

```text
accepted CaseIR -> version capability validation
-> deterministic OpenFOAM input bundle
```

It compiles simulation input **content**. It does not invoke `wmake`, modify
OpenFOAM C++ source, or manage OpenFOAM's internal build system.

## Current and target runtimes

- Foundation OpenFOAM v10 is the repository's current declared runtime.
- Foundation OpenFOAM v13 is the target runtime for new research cases.
- v10 and v13 require separate backend profiles and golden tests.
- Neither profile becomes selectable until its deterministic emitter passes its
  capability and golden-case gates.

## Migration from the current input writer

The existing LLM/RAG input writer may remain as a semantic planning assistant.
It must not remain the authoritative native-file generator.

The production path is:

1. LLM or user proposes SimulationSpec content.
2. Shared frontend validates and normalizes it to CaseIR.
3. A versioned backend emits `0/`, `constant/`, `system/`, and `Allrun`.
4. Deterministic validators check patch names, fields, dictionaries, mesh, and
   runtime compatibility.
5. The backend writes bundle and per-file hashes.
6. ExperimentOS dispatches the immutable bundle to an existing runtime.

## Target package shape

```text
src/input_backend/
  contract.py
  capabilities.py
  common/
  foundation_v10/
  foundation_v13/
```

Unsupported CaseIR content must fail before dispatch. A backend may never
silently approximate physics or rebuild the solver.
