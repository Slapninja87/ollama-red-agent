"""Conditional edge logic for the LangGraph state machine.

Determines which node to route to next based on the current AgentState.
"""

from __future__ import annotations

from src.config import logger, AppConfig
from src.graph.state import AgentState

# ── Phase ordering ─────────────────────────────────────────────────────────

PHASE_ORDER = [
    "recon",
    "enumeration",
    "exploit",
    "post_exploit",
    "report",
]

# ── Conditional router ─────────────────────────────────────────────────────

def route_next_phase(state: AgentState) -> str:
    """Determine the next node name based on current state.

    Returns the name of the next LangGraph node to route to.
    """
    current = state.current_phase
    retries = state.phase_retries

    # Safety: if we've retried too many times, skip forward
    max_retries = _get_max_retries()

    # ── Error / Done checks ──────────────────────────────────────────────
    if state.error:
        logger.error("state_error", error=state.error, phase=current)
        return "__end__"

    if state.done:
        return "__end__"

    # ── Retry logic: stay in current phase if validation failed ──────────
    if retries > 0 and retries <= max_retries:
        logger.info("route_retry", phase=current, attempt=retries)
        # Map phase name to its node name
        return f"{current}_node"

    # If we've exhausted retries, force advance
    if retries > max_retries:
        logger.warning("retries_exhausted", phase=current, advancing=True)

    # ── Advance to next phase ────────────────────────────────────────────
    try:
        idx = PHASE_ORDER.index(current)
    except ValueError:
        logger.error("unknown_phase", phase=current)
        return "__end__"

    if idx >= len(PHASE_ORDER) - 1:
        # Last phase — route to report or end
        return "report_node"

    next_phase = PHASE_ORDER[idx + 1]
    next_node = f"{next_phase}_node"

    logger.info(
        "phase_transition",
        from_phase=current,
        to_phase=next_phase,
    )
    return next_node


def should_continue(state: AgentState) -> str:
    """Post-agent-iteration router for the ReAct loop within a phase.

    Called after the agent node finishes a Thought/Action iteration.
    Returns either "tools" (to execute a tool call) or "continue" (to advance).
    
    In our architecture, this is used by the per-phase sub-graphs.
    For the top-level phase state machine, use route_next_phase instead.
    """
    # If the agent's last message had tool calls, route to tool execution
    if state.agent_outcome and hasattr(state.agent_outcome, "tool_calls"):
        if state.agent_outcome.tool_calls:
            return "tools"

    # Otherwise, we're done with this phase — route to validation
    return "validate_phase"


# ── Internal ───────────────────────────────────────────────────────────────

def _get_max_retries() -> int:
    from src.config import load_config
    return load_config().max_phase_retries
