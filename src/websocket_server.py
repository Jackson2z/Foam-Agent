"""WebSocket server for Foam-Agent.

Implements the NullFlux frontend protocol, bridging to Foam-Agent's
LangGraph workflow and MCP tools.

Usage:
    python -m src.websocket_server --port 5174
    # Then open http://localhost:5174/app.html in browser
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

# Ensure src/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from session import Session, SessionManager
from services.checkpoint import auto_commit, init_repo, log_recent, revert_to


# ── Globals ──────────────────────────────────────────────────────────────

app = FastAPI(title="Foam-Agent", version="2.0.0")
manager = SessionManager()
global_config = Config()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


# ── Static files ─────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "welcome.html")


@app.get("/app.html")
@app.get("/app")
async def app_page():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/welcome.html")
async def welcome_page():
    return FileResponse(FRONTEND_DIR / "welcome.html")


# ── API endpoints ────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config():
    return JSONResponse({
        "workspace": str(RUNS_DIR),
        "model": global_config.model_version,
        "name": "Foam-Agent",
        "author": "csml-rpi + WorkSpace",
        "platform": sys.platform,
        "hasApiKey": bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
        "provider": global_config.model_provider,
        "baseUrl": "",
    })


@app.get("/api/file")
async def api_file(path: str = "", raw: int = 0):
    """Serve a file from the workspace."""
    if not path:
        return JSONResponse({"error": "no path"}, status_code=400)
    target = Path(path)
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    if raw:
        return FileResponse(target)
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({"path": str(target), "content": content})
    except Exception:
        return FileResponse(target)


# ── WebSocket handler ────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = manager.create(ws, global_config)
    await session.send_term("[Foam-Agent] WebSocket 连接成功")
    await _send_tree(session)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_message(session, msg)
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(ws)


async def _handle_message(session: Session, msg: dict) -> None:
    """Route frontend messages to Foam-Agent services."""
    msg_type = msg.get("type", "")

    if msg_type == "user":
        await _handle_user_message(session, msg)

    elif msg_type == "stop":
        session.aborted = True
        await session.send_term("[已停止]")

    elif msg_type == "reset":
        session.aborted = False
        session.running = False
        session.case_dir = None
        await session.send({"type": "reset_done"})

    elif msg_type == "set_auto":
        session.auto_mode = msg.get("value", True)
        await session.send_term(f"[Auto Mode] {'开启' if session.auto_mode else '关闭'}")

    elif msg_type == "set_tools":
        await session.send_term("[工具集] 已更新")

    elif msg_type == "approval":
        # TODO: implement approval gate
        pass

    elif msg_type == "restore_checkpoint":
        cp_id = msg.get("id", "")
        if session.case_dir:
            result = await revert_to(Path(session.case_dir), cp_id, note="用户恢复")
            await session.send_term(f"[Checkpoint] 已恢复到 {result['sha']}")
            await session.send_checkpoints()

    elif msg_type == "compact":
        await session.send_term("[上下文压缩] 当前版本暂不支持")

    elif msg_type == "kill_all":
        session.aborted = True
        await session.send_term("[已终止所有进程]")

    elif msg_type == "set_foam":
        await session.send({"type": "foam_state", "enabled": msg.get("value", False), "root": str(RUNS_DIR)})

    else:
        # Forward unhandled messages as terminal info
        await session.send_term(f"[未处理消息] {msg_type}")


async def _handle_user_message(session: Session, msg: dict) -> None:
    """Process a user chat message through Foam-Agent's workflow."""
    text = msg.get("text", "").strip()
    if not text:
        return

    if session.running:
        await session.send_term("[Busy] 上一轮任务仍在运行")
        return

    session.aborted = False
    session.running = True
    await session.send({"type": "agent_start"})

    try:
        # Import services here to avoid circular imports at module level
        from services.plan import generate_simulation_plan
        from services.input_writer import initial_write
        from services.run_local import run_allrun_and_collect_errors
        from services.review import review_error_logs
        from services.visualization import ensure_foam_file, generate_pyvista_script

        # Load case statistics
        case_stats_path = os.path.join(global_config.database_path, "raw", "openfoam_case_stats.json")
        with open(case_stats_path, "r", encoding="utf-8") as f:
            case_stats = json.load(f)

        # ── Step 1: Plan ──
        await session.send_phase("planning", "分析需求，规划仿真方案")
        await session.send_tool_call("plan-1", "plan", {"user_requirement": text})

        plan_data = generate_simulation_plan(
            user_requirement=text,
            case_stats=case_stats,
            case_dir="",
            searchdocs=global_config.searchdocs,
        )

        case_name = plan_data["case_name"]
        case_solver = plan_data["case_solver"]
        subtasks = plan_data["subtasks"]

        await session.send_tool_result("plan-1", "plan", json.dumps({
            "case_name": case_name,
            "solver": case_solver,
            "subtasks": subtasks,
        }, ensure_ascii=False, indent=2))
        await session.send_phase("planning", f"规划完成: {case_name} ({case_solver})")

        if session.aborted:
            return

        # ── Step 2: Write files ──
        from services.plan import resolve_case_dir, retrieve_references

        case_dir = resolve_case_dir(case_name, "", global_config.run_times)
        session.case_dir = case_dir

        await session.send_phase("writing", f"生成 OpenFOAM 文件: {case_name}")
        await session.send_tool_call("write-1", "input_writer", {"case_name": case_name})

        tutorial_ref, dir_structure, _, allrun_ref, similar_advice = retrieve_references(
            case_name=case_name,
            case_solver=case_solver,
            case_domain=plan_data.get("case_domain", "fluid"),
            case_category=plan_data.get("case_category", "tutorial"),
            searchdocs=global_config.searchdocs,
        )

        write_result = await asyncio.to_thread(
            initial_write,
            case_dir=case_dir,
            subtasks=subtasks,
            user_requirement=text,
            tutorial_reference=tutorial_ref,
            case_solver=case_solver,
            case_info=str(plan_data),
            allrun_reference=allrun_ref,
            database_path=str(global_config.database_path),
            searchdocs=global_config.searchdocs,
            similar_case_advice=similar_advice,
        )

        n_files = len(write_result.get("foamfiles", {}).list_foamfile) if write_result.get("foamfiles") else 0
        await session.send_tool_result("write-1", "input_writer", f"已生成 {n_files} 个文件到 {case_dir}")

        # Git checkpoint
        cp = await auto_commit(Path(case_dir), "[input_writer] generated files")
        await session.send_term(f"[V8 git] pre=<init> post={cp['sha']}")
        await session.send_checkpoints()

        if session.aborted:
            return

        # ── Step 3: Run ──
        await session.send_phase("running", f"执行求解: {case_solver}")
        await session.send_tool_call("run-1", "run", {"case_dir": case_dir})

        error_logs = await asyncio.to_thread(
            run_allrun_and_collect_errors,
            case_dir=case_dir,
            timeout=global_config.max_time_limit,
            max_retries=3,
        )

        # Git checkpoint after run
        cp2 = await auto_commit(Path(case_dir), "[post-run] simulation completed")
        await session.send_term(f"[V8 git] post={cp2['sha']}")

        errors_str = [str(e) for e in error_logs]
        if errors_str:
            await session.send_tool_result("run-1", "run", f"发现 {len(errors_str)} 个错误:\n" + "\n".join(errors_str[:5]))
            await session.send_phase("reviewing", "分析错误，尝试修复")
            await session.send_term("[求解失败] 需要人工介入或自动修复")
        else:
            await session.send_tool_result("run-1", "run", "求解成功完成")
            await session.send_term("[求解完成] ✓")

        if session.aborted:
            return

        # ── Step 4: Visualization ──
        foam_file = ensure_foam_file(case_dir)
        if foam_file:
            await session.send_phase("visualizing", "生成可视化")
            await session.send_tool_call("viz-1", "visualization", {"case_dir": case_dir})

            from services.visualization import run_pyvista_script
            script = generate_pyvista_script(case_dir, foam_file, "velocity", [])
            ok, img, errs = run_pyvista_script(case_dir, script)
            if ok and img:
                await session.send_tool_result("viz-1", "visualization", f"可视化已生成: {img}")
            else:
                await session.send_tool_result("viz-1", "visualization", "可视化生成失败")

        await session.send_phase("done", "工作流完成")

    except Exception as e:
        await session.send({"type": "error", "message": str(e)})
        await session.send_term(f"[错误] {e}")
    finally:
        session.running = False
        await session.send({"type": "agent_end"})


async def _send_tree(session: Session) -> None:
    """Send file tree to frontend."""
    if RUNS_DIR.exists():
        tree = _build_tree(RUNS_DIR, depth=2)
        await session.send({"type": "tree", "tree": tree})


def _build_tree(path: Path, depth: int = 2) -> dict:
    """Build a simple file tree dict."""
    result = {"name": path.name, "path": str(path), "children": []}
    if depth <= 0:
        return result
    try:
        for child in sorted(path.iterdir()):
            if child.name.startswith(".") or child.name == "node_modules":
                continue
            if child.is_dir():
                result["children"].append(_build_tree(child, depth - 1))
            else:
                result["children"].append({"name": child.name, "path": str(child)})
    except PermissionError:
        pass
    return result


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Foam-Agent WebSocket Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5174)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
