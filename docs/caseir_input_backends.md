# Versioned OpenFOAM CaseIR Input Backends

Status: M0 design contract.

## Current truth

Foam-Agent currently declares Foundation OpenFOAM v10 and generates native
files through an LLM/RAG input writer. The current behavior remains available
as a legacy path while the deterministic CaseIR boundary is introduced.

The production research target also requires Foundation OpenFOAM v13. v10 and
v13 are separate runtime/input-backend profiles and must not be treated as
implicitly compatible.

## Boundary

Foam-Agent compiles accepted simulation **content** into OpenFOAM-native input
files. It does not compile, patch, or rebuild OpenFOAM source code and does not
invoke `wmake`.

```text
SimulationSpec -> canonical CaseIR -> versioned OpenFOAM Input Backend
-> Native Input Bundle -> existing Foundation OpenFOAM runtime
```

## Planned package boundary

```text
src/input_backend/
  capability.py
  case_ir.py
  semantic_mapping.py
  foundation_v10/
  foundation_v13/
  manifest.py
  diagnostics.py
```

The LLM planner may propose semantic content. It must not be the final
authoritative emitter. Native dictionaries are emitted from validated CaseIR by
versioned deterministic code.

## Version policy

- `openfoam-foundation-v10`: compatibility backend for the repository's
  current runtime.
- `openfoam-foundation-v13`: target backend for new production/research cases.
- ESI OpenFOAM remains unsupported unless a separate explicit backend is added.

## Required gates

1. CaseIR schema and capability validation.
2. Mesh-region and patch-name validation.
3. Cross-file field/boundary-condition validation.
4. Deterministic emission of `0/`, `constant/`, `system/`, and `Allrun`.
5. `foamDictionary` syntax checks.
6. `checkMesh` validation where a mesh is available.
7. Per-file checksum and immutable bundle manifest.
8. Explicit failure for unsupported runtime/capability combinations.

Generated native files are artifacts and must not become a second source of
truth.
