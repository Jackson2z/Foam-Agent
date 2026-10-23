"""Remote HPC execution via SSH.

Orchestrates: upload case → generate PBS → submit → poll → download → error check.
Reuses SSHClient from ssh_client.py for transport.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from services.ssh_client import SSHClient
from config import Config
from utils import check_foam_errors


# OpenFOAM v13 environment on NUS Vanda HPC
_VANDA_OF_ENV = """
export GCC_DIR=/app1/ebapps/arches/flat-avx512/software/GCC/14.2.0
export MPI_DIR=/app1/ebapps/arches/flat-avx512/software/OpenMPI/5.0.7-GCC-14.2.0
export WM_PROJECT_DIR=/app1/ebapps/arches/flat-avx512/software/OpenFOAM/13-foss-2025a/OpenFOAM-13
export FOAM_ETC=$WM_PROJECT_DIR/etc
export WM_OPTIONS=linux64GccDPInt32Opt
export FOAM_LIBBIN=$WM_PROJECT_DIR/platforms/$WM_OPTIONS/lib
export FOAM_APPBIN=$WM_PROJECT_DIR/platforms/$WM_OPTIONS/bin
export PATH=$MPI_DIR/bin:$GCC_DIR/bin:$FOAM_APPBIN:$WM_PROJECT_DIR/bin:$PATH
export LD_LIBRARY_PATH=$MPI_DIR/lib:$GCC_DIR/lib64:$GCC_DIR/lib:$FOAM_LIBBIN:$LD_LIBRARY_PATH
export MPI_BUFFER_SIZE=20000000
"""

_PBS_TEMPLATE = """#!/bin/bash
#PBS -N foamagent_{case_name}
#PBS -l select=1:ncpus={ncpus}:mem={mem}gb:mpiprocs={ncpus}
#PBS -l walltime={walltime}
#PBS -q auto
#PBS -j oe

{of_env}

cd $PBS_O_WORKDIR
NPROC=$(cat "$PBS_NODEFILE" | wc -l)

echo "=== {case_name} on compute node, NPROC=$NPROC, $(date) ==="

# Fix permissions for uploaded case
chmod -R u+w . 2>/dev/null

# Mesh
blockMesh > log.blockMesh 2>&1
if [ $? -ne 0 ]; then echo "blockMesh FAIL"; exit 1; fi

checkMesh > log.checkMesh 2>&1
if grep -q "Mesh OK" log.checkMesh; then
    echo "checkMesh OK"
else
    echo "checkMesh FAIL"
    cat log.checkMesh | tail -20
    exit 1
fi

# Decompose for parallel
if [ "$NPROC" -gt 1 ]; then
    cat > system/decomposeParDict << DECOMP
FoamFile {{ version 2.0; format ascii; class dictionary; object decomposeParDict; }}
numberOfSubdomains $NPROC;
method scotch;
DECOMP
    decomposePar -force > log.decomposePar 2>&1
    echo "decomposePar done"
fi

# Solver
if [ "$NPROC" -gt 1 ]; then
    mpirun -np $NPROC -x PATH -x LD_LIBRARY_PATH -x WM_PROJECT_DIR \
        -x WM_OPTIONS -x FOAM_ETC -x FOAM_LIBBIN -x FOAM_APPBIN -x MPI_BUFFER_SIZE \
        foamRun -solver fluid -parallel > log.foamRun 2>&1
else
    foamRun -solver fluid > log.foamRun 2>&1
fi

EXIT_CODE=$?
echo "foamRun exit: $EXIT_CODE"

if grep -q 'residual = nan' log.foamRun 2>/dev/null; then
    ns=$(grep -B5 -m1 'residual = nan' log.foamRun | grep '^Time = ' | awk '{{print $NF}}')
    echo "*** NaN at Time=$ns ***"
else
    lt=$(grep '^Time = ' log.foamRun 2>/dev/null | tail -1 | awk '{{print $NF}}')
    echo "OK (step $lt)"
fi

echo "=== {case_name} done at $(date) ==="
exit $EXIT_CODE
"""

# PBS terminal states
_PBS_TERMINAL = {"C", "F", "E"}  # Completed, Failed, Exiting
_PBS_ERROR = {"F", "Q"}  # Failed (Q here means held/error)


def estimate_resources(case_dir: str) -> dict:
    """Parse blockMeshDict to estimate ncpus and memory. Based on submit.sh logic."""
    bmd_path = Path(case_dir) / "system" / "blockMeshDict"
    cells = 0

    if bmd_path.exists():
        content = bmd_path.read_text(encoding="utf-8", errors="replace")
        # Parse hex block definitions: hex (a b c ...) (nx ny nz)
        for m in re.finditer(r'hex\s+\([^)]+\)\s+\(\s*(\d+)\s+(\d+)\s+(\d+)', content):
            nx, ny, nz = int(m.group(1)), int(m.group(2)), int(m.group(3))
            cells += nx * ny * nz

    if cells == 0:
        cells = 10000  # default small case

    # 50K cells/core sweet spot, min 8, max 72
    target_per_core = 50000
    ncpus = max(8, min(72, (cells + target_per_core - 1) // target_per_core))

    # Memory: mesh phase ~0.12 GB/10K cells + 20GB baseline; solver ~4GB/core + 40GB
    mesh_mem = cells // 10000 * 12 // 10 + 20
    solver_mem = ncpus * 4 + 40
    mem_gb = max(20, min(500, max(mesh_mem, solver_mem)))

    return {"ncpus": ncpus, "mem": mem_gb, "cells": cells}


def generate_pbs_script(case_dir: str, case_name: str, ncpus: int, mem_gb: int, walltime: str = "04:00:00") -> str:
    """Generate a PBS job script for the case."""
    script = _PBS_TEMPLATE.format(
        case_name=case_name,
        ncpus=ncpus,
        mem=mem_gb,
        walltime=walltime,
        of_env=_VANDA_OF_ENV,
    )
    script_path = Path(case_dir) / "job.pbs"
    script_path.write_text(script, encoding="utf-8")
    return str(script_path)


def run_case_remote(
    case_dir: str,
    config: Config,
    timeout: int = 3600,
) -> dict:
    """
    Remote execution orchestration.

    1. SSH connect
    2. Upload case_dir → remote_case_root/<case_name>/
    3. Fix permissions (chmod u+w)
    4. Generate PBS job script
    5. Upload PBS script
    6. Submit: qsub -l "select=1:ncpus=N:mem=Mgb:mpiprocs=N" job.pbs
    7. Poll qstat every 30s until terminal state
    8. Download results + logs
    9. Check for errors locally

    Returns dict with keys: success, job_id, status, errors, remote_dir
    """
    case_name = Path(case_dir).name
    remote_root = config.remote_case_root or "/scratch/serv390/OpenFOAM"
    remote_dir = f"{remote_root}/{case_name}"

    result = {
        "success": False,
        "job_id": None,
        "status": "pending",
        "errors": [],
        "remote_dir": remote_dir,
    }

    ssh = SSHClient.from_config(config)
    try:
        ssh.connect()
        print(f"[SSH] Connected to {ssh.host}")

        # Upload
        n_files = ssh.upload_dir(case_dir, remote_dir)
        print(f"[SSH] Uploaded {n_files} files to {remote_dir}")

        # Fix permissions
        ssh.run_command(f"chmod -R u+w {remote_dir}")
        print(f"[SSH] Fixed permissions")

        # Generate PBS script locally, then upload
        resources = estimate_resources(case_dir)
        print(f"[PBS] Cells={resources['cells']}, ncpus={resources['ncpus']}, mem={resources['mem']}GB")

        pbs_script = generate_pbs_script(
            case_dir, case_name, resources["ncpus"], resources["mem"]
        )
        ssh.run_command(f"mkdir -p {remote_dir}")
        ssh._sftp.put(pbs_script, f"{remote_dir}/job.pbs")
        print(f"[PBS] Uploaded job.pbs")

        # Submit
        lselect = f"select=1:ncpus={resources['ncpus']}:mem={resources['mem']}gb:mpiprocs={resources['ncpus']}"
        submit_output = ssh.run_command(f"cd {remote_dir} && qsub -l '{lselect}' job.pbs")
        print(f"[PBS] Submit: {submit_output}")

        job_id_match = re.search(r'(\d+)', submit_output)
        if not job_id_match:
            result["errors"].append(f"Failed to extract job ID from: {submit_output}")
            return result

        job_id = job_id_match.group(1)
        result["job_id"] = job_id
        print(f"[PBS] Job ID: {job_id}")

        # Poll
        elapsed = 0
        poll_interval = 30
        last_status = ""
        while elapsed < timeout:
            status_output = ssh.run_command(f"qstat {job_id} 2>/dev/null")
            # Parse PBS status: job_id.user.queue.jobname state ...
            # State is in column 5 (0-indexed) or after job name
            status = "unknown"
            for line in status_output.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 5 and job_id in parts[0]:
                    status = parts[4]  # state column
                    break

            if not status_output.strip() or status == "unknown":
                # Job not in queue = completed
                status = "C"

            if status != last_status:
                print(f"[PBS] Job {job_id} status: {status}")
                last_status = status

            if status in _PBS_TERMINAL:
                result["status"] = "completed" if status == "C" else "failed"
                break

            time.sleep(poll_interval)
            elapsed += poll_interval
        else:
            result["status"] = "timeout"
            result["errors"].append(f"Job {job_id} timed out after {timeout}s")
            return result

        # Download results
        n_downloaded = ssh.download_dir(remote_dir, case_dir)
        print(f"[SSH] Downloaded {n_downloaded} files")

        # Check for errors locally
        error_logs = check_foam_errors(case_dir)
        result["errors"] = [str(e) for e in error_logs]
        result["success"] = len(result["errors"]) == 0

        if result["success"]:
            print(f"[OK] Job {job_id} completed successfully")
        else:
            print(f"[WARN] Job {job_id} completed with {len(result['errors'])} errors")

    finally:
        ssh.close()

    return result
