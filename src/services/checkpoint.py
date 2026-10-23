"""Git Checkpoint service for Foam-Agent.

Auto-commits on every file write, supports rollback on repeated failures.
Ported from NullFlux CFDriver's Qd() + _s() pattern (server.deobfuscated.js:46623).
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional


# Files/patterns to exclude from CFD case git tracking
GITIGNORE_TEMPLATE = """\
# cfdriver auto-generated (V8)
processor*/
*.foam
postProcessing/
VTK/
*.vtk
*.vtu
*.pvd
*.log
"""


async def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command asynchronously."""
    return await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _run_git(*args: str, cwd: Path) -> str:
    """Run git command and return stdout, raise on failure."""
    proc = await _git(*args, cwd=cwd)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode(errors='replace')}")
    return stdout.decode(errors='replace').strip()


async def init_repo(case_dir: Path) -> dict:
    """Initialize git repo for case directory (idempotent).

    Creates .gitignore for CFD artifacts, makes initial baseline commit.
    Returns {ok: bool, init: bool} where init=True means newly created.
    """
    case_dir = Path(case_dir)
    git_dir = case_dir / ".git"

    if git_dir.exists():
        return {"ok": True, "init": False}

    await _run_git("init", "-q", cwd=case_dir)
    await _run_git("config", "user.email", "foam-agent@local", cwd=case_dir)
    await _run_git("config", "user.name", "Foam-Agent", cwd=case_dir)

    gitignore = case_dir / ".gitignore"
    existing = ""
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
    if "# foam-agent auto-generated" not in existing:
        gitignore.write_text(
            existing + "\n# foam-agent auto-generated\n" + GITIGNORE_TEMPLATE,
            encoding="utf-8",
        )

    await _run_git("add", "-A", cwd=case_dir)
    await _run_git("commit", "-q", "-m", "[foam-agent init] baseline", "--allow-empty", cwd=case_dir)
    return {"ok": True, "init": True}


async def auto_commit(case_dir: Path, message: str) -> dict:
    """Stage all changes and create a checkpoint commit.

    Returns {sha: str, changed: bool}.
    """
    case_dir = Path(case_dir)
    await init_repo(case_dir)

    await _run_git("add", "-A", cwd=case_dir)
    # --allow-empty so we always get a commit even if nothing changed
    await _run_git("commit", "-q", "-m", message, "--allow-empty", cwd=case_dir)
    sha = await _run_git("rev-parse", "--short", "HEAD", cwd=case_dir)

    diff = await _run_git("diff", "--stat", "HEAD~1", "HEAD", cwd=case_dir)
    changed = bool(diff)

    return {"sha": sha, "changed": changed}


async def log_recent(case_dir: Path, n: int = 10) -> list:
    """List recent N commits as [{sha, message, files_changed}]."""
    case_dir = Path(case_dir)
    try:
        log = await _run_git(
            "log", f"-{n}", "--pretty=format:%h|%s", "--shortstat",
            cwd=case_dir,
        )
    except RuntimeError:
        return []

    commits = []
    lines = log.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "|" in line:
            sha, msg = line.split("|", 1)
            files_changed = ""
            if i + 1 < len(lines) and "file" in lines[i + 1]:
                i += 1
                files_changed = lines[i].strip()
            commits.append({
                "sha": sha,
                "message": msg,
                "files_changed": files_changed,
            })
        i += 1

    return commits


async def revert_to(case_dir: Path, sha: str, note: str = "") -> dict:
    """Revert working directory to a previous commit.

    Creates a new commit on top (does not lose history).
    Returns {sha: str, message: str}.
    """
    case_dir = Path(case_dir)
    msg = f"[revert] to {sha}" + (f": {note}" if note else "")

    # Checkout the old tree, then commit it as a new snapshot
    await _run_git("add", "-A", cwd=case_dir)
    tree = await _run_git("rev-parse", f"{sha}:", cwd=case_dir)

    # Read current HEAD commit to get parent
    await _run_git("read-tree", "--reset", tree, cwd=case_dir)
    await _run_git("add", "-A", cwd=case_dir)
    await _run_git("commit", "-q", "-m", msg, "--allow-empty", cwd=case_dir)

    new_sha = await _run_git("rev-parse", "--short", "HEAD", cwd=case_dir)
    return {"sha": new_sha, "message": msg}


async def get_diff(case_dir: Path, sha: str) -> str:
    """Get diff for a specific commit."""
    case_dir = Path(case_dir)
    try:
        return await _run_git("diff", f"{sha}~1", sha, cwd=case_dir)
    except RuntimeError:
        return await _run_git("show", sha, "--format=", cwd=case_dir)
