"""Central configuration for ollama-red-agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
import yaml

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPT_DIR = CONFIG_DIR / "prompts"
OUTPUT_DIR = ROOT / "output"


# ── Logging ────────────────────────────────────────────────────────────────
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("ollama-red-agent")


# ── Model Configuration ────────────────────────────────────────────────────

class OllamaConfig(BaseModel):
    """Configuration for the local Ollama instance."""

    base_url: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    primary_model: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_PRIMARY_MODEL", "qwen2.5-coder:14b")
    )
    triage_model: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_TRIAGE_MODEL", "qwen2.5-coder:14b")
    )
    temperature: float = 0.1
    timeout: int = 120

    @property
    def primary_kwargs(self) -> dict:
        return {
            "model": self.primary_model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "num_predict": 2048,
        }

    @property
    def triage_kwargs(self) -> dict:
        return {
            "model": self.triage_model,
            "base_url": self.base_url,
            "temperature": 0.0,
            "num_predict": 1024,
        }


# ── Application Configuration ──────────────────────────────────────────────

Phase = Literal["recon", "enumeration", "exploitation", "post_exploitation", "reporting"]


class AppConfig(BaseModel):
    """Top-level application configuration."""

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    initial_phase: Phase = "recon"
    max_phase_retries: int = 3
    auto_proceed: bool = False  # If False, ask user before phase transition
    sandbox_enabled: bool = True  # If False, skip sandboxed validation

    # Tool paths
    nmap_bin: str = Field(default_factory=lambda: os.getenv("NMAP_BIN", "nmap"))
    nuclei_bin: str = Field(default_factory=lambda: os.getenv("NUCLEI_BIN", "nuclei"))

    # Output
    report_dir: Path = OUTPUT_DIR / "reports"
    scan_dir: Path = OUTPUT_DIR / "scans"
    session_dir: Path = OUTPUT_DIR / "sessions"


# ── Global singleton ───────────────────────────────────────────────────────

_config: AppConfig | None = None


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration, optionally from a YAML file overlaying env defaults."""
    global _config
    if _config is not None:
        return _config

    base = AppConfig()

    if path and path.exists():
        with open(path) as f:
            overrides = yaml.safe_load(f)
        _config = AppConfig.model_validate({**base.model_dump(), **(overrides or {})})
    else:
        _config = base

    # Ensure output directories exist
    _config.report_dir.mkdir(parents=True, exist_ok=True)
    _config.scan_dir.mkdir(parents=True, exist_ok=True)
    _config.session_dir.mkdir(parents=True, exist_ok=True)

    logger.info("configuration loaded", primary_model=_config.ollama.primary_model)
    return _config
