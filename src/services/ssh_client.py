"""SSH transport layer for remote HPC execution.

Uses paramiko for SSH connections and SFTP file transfers.
Reads connection config from environment variables or ~/.ssh/config.
"""

import os
import re
import stat
from pathlib import Path
from typing import Optional

try:
    import paramiko
except ImportError:
    paramiko = None


# Files/dirs to exclude when uploading case to HPC
UPLOAD_EXCLUDE = {
    ".git",
    "postProcessing",
    "*.foam",
    "processor*",
}

# File patterns to download from HPC after job completion
DOWNLOAD_INCLUDE = [
    "log.*",
    "Allrun.*",
    "postProcessing/",
    "stdout.log",
    "stderr.log",
]


def _parse_ssh_config(host_alias: str) -> dict:
    """Parse ~/.ssh/config for a given Host alias. Returns dict with HostName, User, IdentityFile, Port."""
    ssh_config_path = Path.home() / ".ssh" / "config"
    if not ssh_config_path.exists():
        return {}

    result = {}
    in_host = False
    with open(ssh_config_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("host "):
                hosts = line.split()[1:]
                in_host = host_alias in hosts
                continue
            if in_host and " " in line:
                key, _, val = line.partition(" ")
                key = key.strip().lower()
                val = val.strip()
                if key == "hostname":
                    result["hostname"] = val
                elif key == "user":
                    result["user"] = val
                elif key == "identityfile":
                    result["identityfile"] = os.path.expanduser(val)
                elif key == "port":
                    result["port"] = int(val)
    return result


class SSHClient:
    """Paramiko-based SSH client for HPC remote execution."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        user: str = "",
        key_path: str = "",
    ):
        if paramiko is None:
            raise ImportError("paramiko is required. Install with: pip install paramiko")
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    @classmethod
    def from_config(cls, config=None) -> "SSHClient":
        """Build SSHClient from Config object, falling back to ~/.ssh/config."""
        cfg = config
        host = getattr(cfg, "ssh_host", "") if cfg else ""
        port = getattr(cfg, "ssh_port", 22) if cfg else 22
        user = getattr(cfg, "ssh_user", "") if cfg else ""
        key_path = getattr(cfg, "ssh_key_path", "") if cfg else ""

        # Fallback to env vars
        host = host or os.getenv("FOAMAGENT_SSH_HOST", "")
        user = user or os.getenv("FOAMAGENT_SSH_USER", "")
        key_path = key_path or os.getenv("FOAMAGENT_SSH_KEY_PATH", "")

        # Fallback to ~/.ssh/config
        if host:
            ssh_cfg = _parse_ssh_config(host)
            if not user:
                user = ssh_cfg.get("user", "")
            if not key_path:
                key_path = ssh_cfg.get("identityfile", "")
            if port == 22 and "port" in ssh_cfg:
                port = ssh_cfg["port"]
            # If host is an alias, resolve to real hostname
            real_host = ssh_cfg.get("hostname", host)
        else:
            real_host = host

        if not real_host:
            raise ValueError("No SSH host configured. Set FOAMAGENT_SSH_HOST or ssh_host in config.")

        return cls(host=real_host, port=port, user=user, key_path=key_path)

    def connect(self) -> None:
        """Establish SSH connection."""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {"hostname": self.host, "port": self.port}
        if self.user:
            connect_kwargs["username"] = self.user
        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path

        self._client.connect(**connect_kwargs)
        self._sftp = self._client.open_sftp()

    def run_command(self, cmd: str) -> str:
        """Execute a command on the remote host. Returns combined stdout+stderr."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        stdin, stdout, stderr = self._client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return (out + err).strip()

    def upload_dir(self, local_dir: str, remote_dir: str, exclude: Optional[set] = None) -> int:
        """Recursively upload local_dir to remote_dir via SFTP. Returns number of files uploaded."""
        if not self._sftp:
            raise RuntimeError("Not connected. Call connect() first.")
        exclude = exclude or UPLOAD_EXCLUDE
        count = 0
        local_path = Path(local_dir)

        # Ensure remote base dir exists
        self._mkdir_p(remote_dir)

        for item in local_path.rglob("*"):
            if self._should_exclude(item, local_path, exclude):
                continue
            rel = item.relative_to(local_path)
            remote_path = f"{remote_dir}/{rel.as_posix()}"
            if item.is_dir():
                self._mkdir_p(remote_path)
            else:
                remote_parent = f"{remote_dir}/{rel.parent.as_posix()}"
                self._mkdir_p(remote_parent)
                self._sftp.put(str(item), remote_path)
                count += 1
        return count

    def download_dir(self, remote_dir: str, local_dir: str, include: Optional[list] = None) -> int:
        """Download files from remote matching include patterns. Returns count."""
        if not self._sftp:
            raise RuntimeError("Not connected. Call connect() first.")
        include = include or DOWNLOAD_INCLUDE
        count = 0
        local_path = Path(local_dir)
        local_path.mkdir(parents=True, exist_ok=True)

        # List remote files and filter
        files_to_download = []
        for pattern in include:
            if pattern.endswith("/"):
                # Directory: download recursively
                try:
                    for f in self._list_remote_recursive(f"{remote_dir}/{pattern.rstrip('/')}"):
                        files_to_download.append(f)
                except FileNotFoundError:
                    pass
            else:
                # File pattern: use find
                result = self.run_command(f"find {remote_dir} -name '{pattern}' -type f 2>/dev/null")
                for f in result.strip().split("\n"):
                    if f.strip():
                        files_to_download.append(f.strip())

        # Also download the last numeric timestep directory
        result = self.run_command(
            f"ls -d {remote_dir}/[0-9]* 2>/dev/null | sort -n | tail -1"
        )
        if result.strip():
            last_ts = result.strip()
            try:
                for f in self._list_remote_recursive(last_ts):
                    files_to_download.append(f)
            except FileNotFoundError:
                pass

        for remote_file in files_to_download:
            rel = remote_file[len(remote_dir):].lstrip("/")
            local_file = local_path / rel
            local_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._sftp.get(remote_file, str(local_file))
                count += 1
            except FileNotFoundError:
                pass
        return count

    def close(self) -> None:
        """Close SSH connection."""
        if self._sftp:
            self._sftp.close()
            self._sftp = None
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def _mkdir_p(self, remote_path: str) -> None:
        """Create remote directory recursively (like mkdir -p)."""
        try:
            self._sftp.stat(remote_path)
        except FileNotFoundError:
            parent = str(Path(remote_path).parent)
            if parent and parent != remote_path:
                self._mkdir_p(parent)
            try:
                self._sftp.mkdir(remote_path)
            except OSError:
                pass  # may already exist due to race

    def _list_remote_recursive(self, remote_dir: str) -> list:
        """List all files under remote_dir recursively."""
        result = []
        try:
            entries = self._sftp.listdir_attr(remote_dir)
        except FileNotFoundError:
            return result
        for entry in entries:
            full = f"{remote_dir}/{entry.filename}"
            if stat.S_ISDIR(entry.st_mode):
                result.extend(self._list_remote_recursive(full))
            else:
                result.append(full)
        return result

    @staticmethod
    def _should_exclude(item: Path, base: Path, exclude: set) -> bool:
        """Check if a path component matches any exclude pattern."""
        rel = item.relative_to(base)
        for part in rel.parts:
            if part in exclude:
                return True
            # Glob-style patterns
            if part.startswith("processor"):
                return True
        name = item.name
        if name.endswith(".foam"):
            return True
        return False
