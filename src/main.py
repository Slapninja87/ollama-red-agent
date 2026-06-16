"""Entry point for ollama-red-agent.

Run as:
    python -m src.main --target 10.0.0.5
    python -m src.main --target example.com --target-type domain
    python -m src.main --dashboard          # Launch Streamlit UI
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from src.config import load_config, logger, OUTPUT_DIR


@click.group()
def cli():
    """ollama-red-agent: Autonomous red team penetration testing agent."""
    pass


@cli.command()
@click.option("--target", required=True, help="Target IP, domain, or URL")
@click.option(
    "--target-type",
    default="ip",
    type=click.Choice(["ip", "domain", "url", "cidr"]),
    help="Type of target",
)
@click.option(
    "--phase",
    default=None,
    type=click.Choice(["recon", "enumeration", "exploitation", "post_exploitation", "reporting"]),
    help="Override starting phase",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=True),
    help="Path to YAML config file",
)
def run(target: str, target_type: str, phase: str | None, config_path: str | None):
    """Run a full assessment against TARGET."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)

    from src.graph.orchestrator import RedAgentOrchestrator

    orchestrator = RedAgentOrchestrator(config)
    result = orchestrator.run(
        target=target,
        target_type=target_type,
        initial_phase=phase,
    )

    # Print summary
    click.echo("\n" + "=" * 60)
    click.echo("ASSESSMENT COMPLETE")
    click.echo("=" * 60)
    click.echo(f"Target:       {target}")
    click.echo(f"Final Phase:  {result.get('current_phase', 'N/A')}")
    click.echo(f"Findings:     {len(result.get('findings', []))}")
    click.echo(f"Sessions:     {len(result.get('sessions', []))}")

    if result.get("final_report"):
        report_path = config.report_dir / f"report_{target}.md"
        report_path.write_text(result["final_report"])
        click.echo(f"\nReport saved: {report_path}")
    else:
        click.echo("\nNo report generated.")


@cli.command()
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=True),
    help="Path to YAML config file",
)
def dashboard(config_path: str | None):
    """Launch the Streamlit real-time dashboard."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)

    click.echo("Starting Streamlit dashboard...")
    import streamlit.web.bootstrap as st_bootstrap

    # Point Streamlit at the dashboard module
    dashboard_path = Path(__file__).resolve().parent / "ui" / "dashboard.py"
    sys.argv = ["streamlit", "run", str(dashboard_path)]
    st_bootstrap.run(str(dashboard_path), "streamlit run", [], [])


@cli.command()
def diagram():
    """Print the Mermaid state machine diagram."""
    config = load_config()
    from src.graph.orchestrator import RedAgentOrchestrator

    orch = RedAgentOrchestrator(config)
    click.echo(orch.get_graph_diagram())


if __name__ == "__main__":
    cli()
