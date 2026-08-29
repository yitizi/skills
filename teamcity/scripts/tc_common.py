#!/usr/bin/env python
"""Shared UTF-8-safe process helpers for the TeamCity skill scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


def configure_utf8_stdio() -> None:
    """Make redirected Python output deterministic on Windows code pages."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_tc_query() -> Optional[str]:
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "tc-query.ps1",
        Path(".agents/skills/teamcity/scripts/tc-query.ps1"),
        Path(".claude/skills/teamcity/scripts/tc-query.ps1"),
        Path("teamcity/scripts/tc-query.ps1"),
        Path("skills/teamcity/scripts/tc-query.ps1"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def find_powershell() -> str:
    names = ("powershell.exe", "pwsh.exe", "pwsh") if sys.platform == "win32" else ("pwsh",)
    for name in names:
        executable = shutil.which(name)
        if executable:
            return executable
    raise RuntimeError("PowerShell was not found (expected powershell.exe or pwsh).")


def run_tc_query_to_file(
    tc_query: str,
    path: str,
    output_file: str,
    *,
    method: str = "GET",
    body_file: Optional[str] = None,
    raw_path: bool = False,
    content_type: Optional[str] = None,
    accept: Optional[str] = None,
) -> None:
    """Run tc-query.ps1 without a command string or text pipeline."""
    cmd = [
        find_powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(Path(tc_query).resolve()),
        "-Path",
        path,
        "-Method",
        method.upper(),
        "-OutFile",
        str(Path(output_file).resolve()),
    ]
    if raw_path:
        cmd.append("-RawPath")
    if body_file:
        cmd.extend(("-BodyFile", str(Path(body_file).resolve())))
    if content_type:
        cmd.extend(("-ContentType", content_type))
    if accept:
        cmd.extend(("-Accept", accept))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"tc-query.ps1 failed with exit code {result.returncode}")


def tc_query_text(
    tc_query: str,
    path: str,
    *,
    raw_path: bool = False,
    accept: Optional[str] = None,
) -> str:
    """Return a TeamCity response decoded as UTF-8 (BOM tolerated)."""
    fd, tmp_name = tempfile.mkstemp(suffix=".tc-response")
    os.close(fd)
    try:
        run_tc_query_to_file(tc_query, path, tmp_name, raw_path=raw_path, accept=accept)
        return Path(tmp_name).read_text(encoding="utf-8-sig")
    finally:
        Path(tmp_name).unlink(missing_ok=True)
