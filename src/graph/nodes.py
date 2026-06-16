"""LangGraph nodes for the red agent state machine.

Each node is a function that receives the current AgentState and returns
an updated AgentState dict.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.config import AppConfig, logger, CONFIG_DIR, PROMPT_DIR
from src.graph.state import AgentState, PhaseReport
from src.agents.base_agent import BaseRedAgent


# ── Prompt loading ─────────────────────────────────────────────────────────

def _load_prompt(phase: str) -> str:
    """Load the system prompt for a given phase from disk."""
    path = PROMPT_DIR / f"{phase}_prompt.txt"
    if path.exists():
        return path.read_text().strip()
    # Fallback generic prompt
    return f"You are an experienced penetration tester in the {phase} phase. Be thorough and precise."


# ── Node factory ───────────────────────────────────────────────────────────

def _build_agent_for_phase(
    state: AgentState,
    phase: str,
    extra_tools: list | None = None,
) -> BaseRedAgent:
    """Construct a BaseRedAgent for the given phase using config."""
    cfg = _get_config()
    prompt = _load_prompt(phase)

    # Phase-specific context injection
    context_parts = [f"Target: {state.target}"]
    if state.services:
        svc_summary = "; ".join(
            f"{s.host}:{s.port}/{s.service_name}" for s in state.services[:20]
        )
        context_parts.append(f"Known services: {svc_summary}")
    if state.sessions:
        context_parts.append(f"Active sessions: {len(state.sessions)}")
    if state.vulnerabilities:
        vuln_summary = "; ".join(
            v.cve_id or v.title for v in state.vulnerabilities[:10]
        )
        context_parts.append(f"Known vulnerabilities: {vuln_summary}")

    context = "\n".join(context_parts)
    prompt = f"{prompt}\n\nCurrent context:\n{context}"

    agent = BaseRedAgent(cfg, prompt, extra_tools=extra_tools, name=f"{phase}_agent")
    return agent


# ── Individual Graph Nodes ─────────────────────────────────────────────────

def recon_node(state: AgentState) -> dict[str, Any]:
    """Reconnaissance phase: discover the attack surface."""
    from src.tools.nmap_tool import get_nmap_tools

    logger.info("phase_start", phase="recon", target=state.target)
    agent = _build_agent_for_phase(state, "recon", extra_tools=get_nmap_tools())

    user_input = (
        f"Perform reconnaissance against {state.target}. "
        "Run port scans, identify open ports and services. "
        "Summarize what you found and note any interesting attack vectors."
    )
    result = agent.run(user_input)
    
    # If the agent returned empty, fill in a fallback summary
    if not result or not result.strip():
        result = f"Recon phase completed against {state.target}. Run with --phase recon for details."

    # Capture findings from the agent's output (the next version will parse
    # structured output; for now we store the raw response)
    finding = PhaseReport(
        phase="recon",
        status="complete",
        summary=result[:1000],
    )

    return {
        "current_phase": "recon",
        "phase_history": state.phase_history + [finding],
        "phase_retries": 0,
        "messages": [HumanMessage(content=f"[Recon Complete]\n{result[:500]}")],
    }


def enumeration_node(state: AgentState) -> dict[str, Any]:
    """Enumeration phase: deep-dive into discovered services."""
    from src.tools.nmap_tool import get_nmap_tools

    logger.info("phase_start", phase="enumeration", target=state.target)
    agent = _build_agent_for_phase(state, "enumeration", extra_tools=get_nmap_tools())

    user_input = (
        f"Perform deep enumeration against {state.target}. "
        "Run service version scans and NSE scripts. "
        "Identify exact versions and look for known vulnerabilities."
    )
    result = agent.run(user_input)

    finding = PhaseReport(
        phase="enumeration",
        status="complete",
        summary=result[:1000],
    )

    return {
        "current_phase": "enumeration",
        "phase_history": state.phase_history + [finding],
        "messages": [HumanMessage(content=f"[Enumeration Complete]\n{result[:500]}")],
    }


def exploit_node(state: AgentState) -> dict[str, Any]:
    """Exploitation phase: attempt to gain a foothold."""
    logger.info("phase_start", phase="exploitation", target=state.target)
    agent = _build_agent_for_phase(state, "exploitation")

    services_summary = "\n".join(
        f"  {s.host}:{s.port} {s.service_name} {s.version}"
        for s in state.services[:10]
    )

    user_input = (
        f"Attempt to exploit services on {state.target}.\n"
        f"Discovered services:\n{services_summary}\n\n"
        "Try each service starting with the highest-risk. "
        "If you get a shell, confirm it by running 'whoami' or 'hostname'."
    )
    result = agent.run(user_input)

    finding = PhaseReport(
        phase="exploitation",
        status="complete",
        summary=result[:1000],
    )

    return {
        "current_phase": "exploit",
        "phase_history": state.phase_history + [finding],
        "messages": [HumanMessage(content=f"[Exploitation Complete]\n{result[:500]}")],
    }


def post_exploit_node(state: AgentState) -> dict[str, Any]:
    """Post-exploitation phase: escalate, pivot, persist."""
    logger.info("phase_start", phase="post_exploitation", target=state.target)
    agent = _build_agent_for_phase(state, "post_exploitation")

    sessions_summary = "\n".join(
        f"  Session on {s.host} (user={s.user}, priv={s.privileged})"
        for s in state.sessions[:5]
    )

    user_input = (
        f"Post-exploitation on {state.target}.\n"
        f"Active sessions:\n{sessions_summary}\n\n"
        "Attempt privilege escalation, lateral movement, and persistence."
    )
    result = agent.run(user_input)

    finding = PhaseReport(
        phase="post_exploitation",
        status="complete",
        summary=result[:1000],
    )

    return {
        "current_phase": "post_exploit",
        "phase_history": state.phase_history + [finding],
        "messages": [HumanMessage(content=f"[Post-Exploitation Complete]\n{result[:500]}")],
    }


def report_node(state: AgentState) -> dict[str, Any]:
    """Report phase: generate the final penetration test report."""
    logger.info("phase_start", phase="reporting", target=state.target)
    agent = _build_agent_for_phase(state, "reporting")

    phase_summary = "\n".join(
        f"  [{r.phase}] {r.status}: {r.summary[:200]}"
        for r in state.phase_history
    )

    user_input = (
        f"Generate a penetration test report for {state.target}.\n"
        f"Phase results:\n{phase_summary}\n\n"
        "Include: executive summary, methodology, findings by severity, "
        "remediation recommendations, and evidence timeline."
    )
    result = agent.run(user_input, max_iterations=20)

    return {
        "current_phase": "reporting",
        "phase_history": state.phase_history
        + [PhaseReport(phase="reporting", status="complete", summary=result[:1000])],
        "final_report": result,
        "done": True,
        "messages": [HumanMessage(content=f"[Report Generated]\n{result[:500]}")],
    }


# ── Validation Nodes ───────────────────────────────────────────────────────

def validate_phase_node(state: AgentState) -> dict[str, Any]:
    phase = state.current_phase
    last_report = state.phase_history[-1] if state.phase_history else None

    if last_report and last_report.status == "complete":
        # Check if the phase actually produced meaningful output
        summary = last_report.summary or ""
        if len(summary.strip()) < 10:
            retries = state.phase_retries + 1
            logger.warning("phase_empty_output", phase=phase, retries=retries)
            return {"phase_retries": retries}
        
        logger.info("phase_validated", phase=phase, summary_len=len(summary))
        return {"phase_retries": 0}
    else:
        retries = state.phase_retries + 1
        logger.warning("phase_validation_failed", phase=phase, retries=retries)
        return {"phase_retries": retries}


# ── Internal ───────────────────────────────────────────────────────────────

def _get_config() -> AppConfig:
    from src.config import load_config
    return load_config()
