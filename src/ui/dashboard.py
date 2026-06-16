"""Streamlit real-time dashboard for ollama-red-agent.

Displays the agent's Thought/Action/Observation loop, phase transitions,
discovered services, vulnerabilities, and active sessions in real-time.
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from src.config import load_config, logger
from src.graph.orchestrator import RedAgentOrchestrator


# ── Page Config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ollama-red-agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Session State ──────────────────────────────────────────────────────────

if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = None
if "result" not in st.session_state:
    st.session_state.result = None
if "running" not in st.session_state:
    st.session_state.running = False
if "log" not in st.session_state:
    st.session_state.log = []


# ── Sidebar ────────────────────────────────────────────────────────────────

st.sidebar.title("🛡️ ollama-red-agent")
st.sidebar.caption("Autonomous Red Team Agent")

target = st.sidebar.text_input("Target", placeholder="10.0.0.5 or example.com")
target_type = st.sidebar.selectbox("Target Type", ["ip", "domain", "url", "cidr"])

phase_options = ["recon", "enumeration", "exploitation", "post_exploitation", "reporting"]
start_phase = st.sidebar.selectbox("Start Phase", phase_options, index=0)

col1, col2 = st.sidebar.columns(2)

with col1:
    run_btn = st.button("▶️ Run", type="primary", use_container_width=True)

with col2:
    clear_btn = st.button("🗑️ Clear", use_container_width=True)

st.sidebar.divider()
st.sidebar.markdown("### Phase Legend")
st.sidebar.markdown("🟢 Complete 🟡 In Progress 🔴 Failed ⚪ Waiting")


# ── Main Layout ────────────────────────────────────────────────────────────

st.title("ollama-red-agent")
st.markdown("Real-time autonomous penetration testing agent powered by Ollama + LangGraph")

# Phase progress bar
phase_display = {
    "recon": "Reconnaissance",
    "enumeration": "Enumeration",
    "exploitation": "Exploitation",
    "post_exploitation": "Post-Exploitation",
    "reporting": "Report",
}

# ── Tabs ───────────────────────────────────────────────────────────────────

tab_overview, tab_log, tab_report = st.tabs([
    "📊 Overview", "📜 Agent Log", "📄 Report",
])

# ── Tab 1: Overview ────────────────────────────────────────────────────────

with tab_overview:
    st.subheader("Assessment Status")

    if st.session_state.result:
        result = st.session_state.result
        current_phase = result.get("current_phase", "unknown")
        findings = result.get("findings", [])
        services = result.get("services", [])
        sessions = result.get("sessions", [])
        vulns = result.get("vulnerabilities", [])

        # Phase progress
        cols = st.columns(len(phase_options))
        for i, phase in enumerate(phase_options):
            with cols[i]:
                if phase == current_phase:
                    st.markdown(f"🟡 **{phase_display[phase]}**")
                elif phase in [r.phase for r in result.get("phase_history", [])]:
                    st.markdown(f"🟢 {phase_display[phase]}")
                else:
                    st.markdown(f"⚪ {phase_display[phase]}")

        st.divider()

        # Metrics row
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Services Found", len(services))
        m2.metric("Vulnerabilities", len(vulns))
        m3.metric("Findings", len(findings))
        m4.metric("Sessions", len(sessions))

        # Services table
        if services:
            st.subheader("Discovered Services")
            st.dataframe(
                [
                    {
                        "Host": s.get("host", ""),
                        "Port": s.get("port", ""),
                        "Service": s.get("service_name", ""),
                        "Version": s.get("version", ""),
                    }
                    for s in services
                ],
                use_container_width=True,
            )

        # Vulnerabilities
        if vulns:
            st.subheader("Vulnerabilities")
            for v in vulns:
                severity = v.get("severity", "Unknown")
                color = {
                    "Critical": "🔴",
                    "High": "🟠",
                    "Medium": "🟡",
                    "Low": "🟢",
                }.get(severity, "⚪")
                st.markdown(f"{color} **{v.get('cve_id', 'N/A')}** — {v.get('title', 'No title')} (CVSS: {v.get('cvss_score', 'N/A')})")

        # Sessions
        if sessions:
            st.subheader("Active Sessions")
            for s in sessions:
                priv = "👑" if s.get("privileged") else "👤"
                st.markdown(f"{priv} **{s.get('host', '')}** — method: {s.get('method', 'unknown')}")

    else:
        st.info("No assessment run yet. Enter a target in the sidebar and click **Run**.")

# ── Tab 2: Agent Log ───────────────────────────────────────────────────────

with tab_log:
    st.subheader("Thought/Action/Observation Log")

    if st.session_state.log:
        for entry in st.session_state.log:
            st.text(entry)
    else:
        st.info("Agent log will appear here during execution.")

    if st.session_state.running:
        st.markdown("🟡 **Agent is running...**")
        st.progress(0.5, text="Processing")

# ── Tab 3: Report ──────────────────────────────────────────────────────────

with tab_report:
    st.subheader("Final Report")

    if st.session_state.result and st.session_state.result.get("final_report"):
        st.markdown(st.session_state.result["final_report"])
    else:
        st.info("Report will appear here after the assessment completes.")


# ── Run Logic ──────────────────────────────────────────────────────────────

if run_btn and target and not st.session_state.running:
    st.session_state.running = True
    st.session_state.log = []

    config = load_config()
    orchestrator = RedAgentOrchestrator(config)
    st.session_state.orchestrator = orchestrator

    log_placeholder = st.empty()

    try:
        with st.spinner(f"Running assessment against {target}..."):
            result = orchestrator.run(
                target=target,
                target_type=target_type,
                initial_phase=start_phase,
            )
            st.session_state.result = result
            st.session_state.log.append(f"✅ Assessment complete: {result.get('current_phase', 'done')}")
            st.rerun()
    except Exception as e:
        st.error(f"Assessment failed: {e}")
        st.session_state.log.append(f"❌ Error: {e}")
    finally:
        st.session_state.running = False

if clear_btn:
    st.session_state.result = None
    st.session_state.log = []
    st.session_state.running = False
    st.rerun()
