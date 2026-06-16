"""Nmap scanning tool wrappers for the Recon and Enumeration phases."""

from __future__ import annotations

import json
import re
import subprocess as sp
from typing import Annotated

from langchain_core.tools import tool

from src.config import AppConfig, logger


def _run_nmap(args: list[str], config: AppConfig, timeout: int = 300) -> str:
    """Execute nmap with the given arguments and return raw output."""
    cmd = [config.nmap_bin, *args]
    logger.info("nmap_exec", cmd=" ".join(cmd))

    try:
        result = sp.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout or result.stderr or "No output"

        # Truncate very long outputs for LLM consumption
        if len(output) > 8000:
            output = output[:8000] + "\n... [truncated]"
        return output
    except sp.TimeoutExpired:
        return "Error: nmap scan timed out"
    except FileNotFoundError:
        return "Error: nmap binary not found — check config or PATH"
    except Exception as exc:
        return f"Error: {exc}"


@tool
def quick_port_scan(
    target: Annotated[str, "Target IP or hostname"],
    ports: Annotated[str, "Port range, e.g. '22,80,443' or '1-1000'"] = "1-1000",
) -> str:
    """Run a fast TCP port scan against a target using nmap.

    Use this for initial recon to discover open ports quickly.
    """
    cfg = _get_config()
    return _run_nmap(
        ["-sS", "-T4", "--max-retries", "2", "-p", ports, target],
        cfg,
    )


@tool
def service_version_scan(
    target: Annotated[str, "Target IP or hostname"],
    ports: Annotated[str, "Ports to probe, e.g. '22,80,443'"] = "",
) -> str:
    """Run a service/version detection scan against a target.

    Use this after discovering open ports to identify exact service versions.
    """
    cfg = _get_config()
    args = ["-sV", "-T4", "--version-intensity", "7"]
    if ports:
        args.extend(["-p", ports])
    args.append(target)
    return _run_nmap(args, cfg, timeout=600)


@tool
def full_scan_with_scripts(
    target: Annotated[str, "Target IP or hostname"],
) -> str:
    """Run a comprehensive scan with service detection and default NSE scripts.

    Use this for deep enumeration after initial service discovery.
    """
    cfg = _get_config()
    return _run_nmap(
        ["-sS", "-sV", "-sC", "-T4", "--max-retries", "2", target],
        cfg,
        timeout=900,
    )


# ── Tool registration helper ───────────────────────────────────────────────

def get_nmap_tools() -> list:
    """Return all nmap tools for registration with an agent."""
    return [quick_port_scan, service_version_scan, full_scan_with_scripts]


# ── Internal ───────────────────────────────────────────────────────────────

def _get_config() -> AppConfig:
    """Lazy-import config to avoid circular imports at module level."""
    from src.config import load_config
    return load_config()
