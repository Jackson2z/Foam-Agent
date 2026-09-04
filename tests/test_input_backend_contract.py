import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "capabilities"


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_openfoam_versions_are_separate_nonselectable_backends():
    v10 = _load("openfoam-foundation-v10.json")
    v13 = _load("openfoam-foundation-v13.json")
    assert v10["backend_id"] != v13["backend_id"]
    assert v10["runtime"]["version"] == "10"
    assert v13["runtime"]["version"] == "13"
    assert v10["selectable"] is False
    assert v13["selectable"] is False


def test_input_backends_never_build_solver_source():
    for name in ("openfoam-foundation-v10.json", "openfoam-foundation-v13.json"):
        manifest = _load(name)
        assert manifest["accepted_ir_versions"] == ["uif.case-ir/v1"]
        assert "solver-source-build" in manifest["prohibited_actions"]
