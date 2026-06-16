"""LangGraph orchestrator — compiles the phase state machine into a runnable graph."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import StateGraph, END

from src.config import AppConfig, logger
from src.graph.state import AgentState
from src.graph.nodes import (
    recon_node,
    enumeration_node,
    exploit_node,
    post_exploit_node,
    report_node,
    validate_phase_node,
)
from src.graph.edges import route_next_phase


# ── Phase-to-node mapping ──────────────────────────────────────────────────

NODE_MAP: dict[str, Any] = {
    "recon_node": recon_node,
    "enumeration_node": enumeration_node,
    "exploit_node": exploit_node,
    "post_exploit_node": post_exploit_node,
    "report_node": report_node,
    "reporting_node": report_node,  # <-- add this alias
    "validate_phase": validate_phase_node,
}


# ── Orchestrator ───────────────────────────────────────────────────────────

class RedAgentOrchestrator:
    """Builds and runs the LangGraph state machine for the red agent.

    Usage:
        config = load_config()
        orch = RedAgentOrchestrator(config)
        result = orch.run(target="10.0.0.5")
        print(result["final_report"])
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logger.bind(component="orchestrator")
        self.graph = self._build_graph()

    # ── Public API ─────────────────────────────────────────────────────────

    def run(
        self,
        target: str,
        target_type: str = "ip",
        initial_phase: str | None = None,
    ) -> dict[str, Any]:
        """Execute the full red agent assessment pipeline.

        Args:
            target: Target IP, domain, URL, or CIDR range.
            target_type: Type of target ('ip', 'domain', 'url', 'cidr').
            initial_phase: Override the starting phase (default: from config).

        Returns:
            Final AgentState as a dict (includes final_report, findings, etc.)
        """
        phase = initial_phase or self.config.initial_phase

        initial_state = AgentState(
            target=target,
            target_type=target_type,
            current_phase=phase,
        )

        self.logger.info(
            "assessment_starting",
            target=target,
            starting_phase=phase,
        )

        # Compile and invoke the graph
        app = self.graph.compile()
        result = app.invoke(
            initial_state.model_dump(),
            {"recursion_limit": 100},
        )

        # Log summary
        final_phase = result.get("current_phase", "unknown")
        finding_count = len(result.get("findings", []))
        self.logger.info(
            "assessment_complete",
            final_phase=final_phase,
            findings=finding_count,
            report_len=len(result.get("final_report", "")),
        )

        return result

    def get_graph_diagram(self) -> str:
        """Return a Mermaid-compatible diagram of the state machine."""
        return """```mermaid
flowchart TD
    START([Start]) --> recon_node
    recon_node --> validate_phase
    validate_phase -->|retry| recon_node
    validate_phase --> enumeration_node
    enumeration_node --> validate_phase
    validate_phase -->|retry| enumeration_node
    validate_phase --> exploit_node
    exploit_node --> validate_phase
    validate_phase -->|retry| exploit_node
    validate_phase --> post_exploit_node
    post_exploit_node --> validate_phase
    validate_phase -->|retry| post_exploit_node
    validate_phase --> report_node
    report_node --> END([End])
```"""

    # ── Internal: Graph Construction ───────────────────────────────────────

    def _build_graph(self) -> StateGraph:
        """Construct the LangGraph StateGraph with all nodes and edges."""
        workflow = StateGraph(AgentState)

        # ── Add all nodes ────────────────────────────────────────────────
        for node_name, node_fn in NODE_MAP.items():
            workflow.add_node(node_name, node_fn)

        # ── Set entry point ──────────────────────────────────────────────
        initial_phase = self.config.initial_phase
        workflow.set_entry_point(f"{initial_phase}_node")

        # ── Add edges ────────────────────────────────────────────────────
        # Each phase node routes to validation
        for phase in ["recon", "enumeration", "exploit", "post_exploit", "report"]:
            workflow.add_edge(f"{phase}_node", "validate_phase")

        # Validation routes conditionally based on state
        workflow.add_conditional_edges(
            "validate_phase",
            route_next_phase,
            {
                "recon_node": "recon_node",
                "enumeration_node": "enumeration_node",
                "exploit_node": "exploit_node",
                "post_exploit_node": "post_exploit_node",
                "report_node": "report_node",
                END: END,
            },
        )

        self.logger.info("graph_built", nodes=list(NODE_MAP.keys()))
        return workflow
