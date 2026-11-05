"""Self-update: replace the running binary with the latest GitHub release."""

from __future__ import annotations

import hashlib
import os
import platform
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

REPO = "aliemrenebiler/docxer"
# Where release files live. Overridable (DOCXER_BASE_URL) for mirrors and tests.
BASE_URL = os.environ.get(
    "DOCXER_BASE_URL", f"https://github.com/{REPO}/releases/latest/download"
).rstrip("/")
INSTALL_CMD = (
    f"curl -fsSL https://raw.githubusercontent.com/{REPO}/main/install.sh | sh"
)


class UpdateError(Exception):
    pass


def asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {
        "arm64": "arm64",
        "aarch64": "aarch64" if system == "linux" else "arm64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(machine)
    if system not in ("darwin", "linux") or arch is None:
        raise UpdateError(f"unsupported platform: {system} {machine}")
    return f"docxer-{system}-{arch}"


def _ssl_context() -> ssl.SSLContext:
    """TLS context with a CA bundle that ships with docxer.

    The release binary bundles its own Python, whose default certificate path
    does not exist on most machines, so verification would always fail.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"docxer/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"could not download {url}: {e}") from e


def _version_key(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def latest_version() -> str:
    return _fetch(f"{BASE_URL}/VERSION").decode().strip().lstrip("v")


def run_update(check_only: bool = False) -> int:
    try:
        latest = latest_version()
        if _version_key(latest) <= _version_key(__version__):
            print(f"docxer is up to date ({__version__})")
            return 0
        print(f"New version available: {__version__} -> {latest}")
        if check_only:
            print("Run 'docxer update' to install it.")
            return 0
        if not getattr(sys, "frozen", False):
            raise UpdateError(
                "this docxer was not installed from a release binary, so it cannot "
                f"update itself. Install the release with:\n  {INSTALL_CMD}"
            )

        name = asset_name()
        sums = _fetch(f"{BASE_URL}/SHA256SUMS").decode().splitlines()
        expected = next(
            (ln.split()[0] for ln in sums if ln.split()[-1:] == [name]), None
        )
        if not expected:
            raise UpdateError(f"no checksum for {name} in the release")
        binary = _fetch(f"{BASE_URL}/{name}")
        if hashlib.sha256(binary).hexdigest() != expected:
            raise UpdateError("checksum mismatch; the download was not installed")

        target = Path(sys.executable).resolve()
        try:
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".docxer-update-")
        except PermissionError as e:
            raise UpdateError(f"no permission to write to {target.parent}") from e
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(binary)
            os.chmod(tmp, 0o755)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        print(f"Updated docxer to {latest}")
        return 0
    except UpdateError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
