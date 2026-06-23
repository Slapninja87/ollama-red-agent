# ollama-red-agent

An autonomous, multi-phase red team penetration testing agent built on **LangGraph** and **LangChain**, powered by locally-hosted LLMs via **Ollama**. Runs a full assessment pipeline — recon → enumeration → exploitation → post-exploitation → reporting — with no human in the loop.

> ⚠️ **For authorized penetration testing and security research only.** Only run against systems you own or have explicit written permission to test.

---

## How It Works

The agent operates as a **LangGraph state machine**: each phase of a penetration test is a node in a directed graph. A central validation node sits between every phase, checks output quality, and either advances the pipeline or retries the current phase.

Each phase spins up a **BaseRedAgent** — a ReAct-pattern (Thought → Action → Observation) agent that binds tools to the LLM, runs an iterative reasoning loop, and returns a structured result. All agents share common infrastructure: tool dispatch, conversation management, context injection, and structured logging.

The LLM backend is fully **model-agnostic**: swap any Ollama-hosted model via environment variable without touching the orchestration layer.

```
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
```

---

## Architecture

```
ollama-red-agent/
├── src/
│   ├── main.py                  # CLI entry point (Click)
│   ├── config.py                # AppConfig, OllamaConfig, paths, logging
│   ├── agents/
│   │   └── base_agent.py        # ReAct agent: tool binding, loop, JSON fallback
│   ├── graph/
│   │   ├── state.py             # Pydantic AgentState + sub-models
│   │   ├── orchestrator.py      # LangGraph StateGraph construction + runner
│   │   ├── nodes.py             # One node function per phase
│   │   └── edges.py             # Conditional routing logic
│   ├── tools/
│   │   └── nmap_tool.py         # Nmap tool bindings for recon + enumeration
│   └── ui/
│       └── dashboard.py         # Streamlit real-time dashboard
├── config/
│   └── prompts/                 # Phase-specific system prompts (loaded at runtime)
│       ├── recon_prompt.txt
│       ├── enum_prompt.txt
│       ├── exploit_prompt.txt
│       ├── postexploit_prompt.txt
│       └── report_prompt.txt
└── output/
    ├── reports/                 # Generated markdown reports
    ├── scans/                   # Raw scan output
    └── sessions/                # Session artifacts
```

### Key Design Decisions

**LangGraph for orchestration** — Rather than a simple sequential script, the pipeline is a proper state graph. This means phases can retry independently, the state is typed and validated at every transition, and adding new phases requires only a new node + edge — the rest of the graph stays unchanged.

**ReAct pattern in BaseRedAgent** — The agent doesn't just prompt the LLM once. It runs a Thought → Action → Observation loop: the LLM reasons about what to do, calls a tool, receives the result, and reasons again. This loop continues until the LLM produces a final answer or the iteration limit is hit.

**JSON fallback parser** — Some smaller models (including quantized local models) don't reliably emit native tool calls. `base_agent.py` includes a fallback that parses JSON tool requests from the model's text output, stripping markdown fences and leading garbage before parsing. This makes the agent compatible with models that don't support structured tool calling natively.

**Model-agnostic via environment config** — The LLM is configured entirely through `OllamaConfig`, which reads from environment variables. Swapping from `qwen2.5-coder:14b` to any other Ollama model requires zero code changes.

**Shared infrastructure** — `BaseRedAgent` is the common layer all phase agents inherit. Tool registration, LLM binding, conversation history, and context injection all live here. Phase nodes only define what tools they need and what goal to pass to the agent.

**Typed state with Pydantic** — `AgentState` carries the full assessment context between phases: discovered services, vulnerabilities, shell sessions, findings, phase history, and messages. Sub-models (`Service`, `Vulnerability`, `ShellSession`, `Finding`) enforce structure throughout the pipeline.

---

## Phases

| Phase | Node | What It Does |
|---|---|---|
| Recon | `recon_node` | Port scanning, service discovery, attack surface mapping |
| Enumeration | `enumeration_node` | Deep service version detection, NSE scripts, CVE identification |
| Exploitation | `exploit_node` | Attempts to gain initial foothold against discovered services |
| Post-Exploitation | `post_exploit_node` | Privilege escalation, lateral movement, persistence |
| Reporting | `report_node` | Generates structured markdown report with findings by severity |

Each phase loads its system prompt from `config/prompts/` at runtime, so prompt engineering is decoupled from code.

---

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally with at least one model pulled
- `nmap` installed and on your PATH (for recon/enumeration tools)

**Default model:** `qwen2.5-coder:14b`

```bash
ollama pull qwen2.5-coder:14b
```

---

## Installation

```bash
git clone https://github.com/Slapninja87/ollama-red-agent.git
cd ollama-red-agent

# Install dependencies
pip install -e .

# Or with dev tools
pip install -e ".[dev]"
```

---

## Usage

### Run a full assessment

```bash
python -m src.main run --target 10.0.0.5
python -m src.main run --target example.com --target-type domain
python -m src.main run --target 192.168.1.0/24 --target-type cidr
```

### Start at a specific phase

```bash
python -m src.main run --target 10.0.0.5 --phase enumeration
```

### Launch the Streamlit dashboard

```bash
python -m src.main dashboard
```

### Print the state machine diagram

```bash
python -m src.main diagram
```

---

## Configuration

Set via environment variables or a YAML config file:

```bash
# Swap the model
export OLLAMA_PRIMARY_MODEL=llama3.1:8b

# Point to a remote Ollama instance
export OLLAMA_BASE_URL=http://192.168.1.100:11434

# Use a custom nmap binary path
export NMAP_BIN=/usr/local/bin/nmap
```

Pass a YAML config file to override any `AppConfig` field:

```bash
python -m src.main run --target 10.0.0.5 --config myconfig.yaml
```

---

## Swapping the Agent Framework

The orchestration layer is intentionally decoupled from the LLM and agent framework. `BaseRedAgent` currently wraps LangChain + Ollama, but the interface it exposes to the graph nodes (`run(user_input)` → `str`) is simple enough to swap for any other framework — Hermes Agent, OpenClaw, or a direct API call — without changing the LangGraph state machine or phase logic.

---

## Extending the Agent

**Add a new phase:**
1. Write a prompt in `config/prompts/yourphase_prompt.txt`
2. Add a node function in `src/graph/nodes.py`
3. Register it in `NODE_MAP` in `orchestrator.py`
4. Add it to `PHASE_ORDER` in `edges.py`

**Add a new tool:**
1. Define it with `@langchain_tool` decorator
2. Pass it in the `extra_tools` list when constructing `BaseRedAgent` in your node

**Add a new model:**

```bash
ollama pull mistral:7b
export OLLAMA_PRIMARY_MODEL=mistral:7b
```

---

## Output

Reports are saved to `output/reports/report_<target>.md` after the reporting phase completes. The report includes executive summary, methodology, findings by severity, remediation recommendations, and an evidence timeline.

---

## Stack

| Component | Library |
|---|---|
| Orchestration | LangGraph |
| Agent framework | LangChain (ReAct pattern) |
| LLM backend | Ollama via `langchain-ollama` |
| Default model | qwen2.5-coder:14b |
| State management | Pydantic v2 |
| CLI | Click |
| Dashboard | Streamlit |
| Logging | structlog |
| Network scanning | python-nmap |

---

## License

MIT
