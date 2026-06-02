"""
Multi-Agent Codebase Analysis System
=====================================
10 specialized Claude agents analyze the project, share findings via a
message bus, respond to each other, then a coordinator synthesizes
everything into one final report.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python multi_agent_system.py

Optional:
    python multi_agent_system.py --output report.md   # save final report
    python multi_agent_system.py --fast               # skip round-2 cross-talk
"""

import anthropic
import argparse
import asyncio
import json
import os
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, List


# ── Source files to load ──────────────────────────────────────────────────────

SOURCE_FILES = [
    "polymarket_agent.py",
    "paper_trading.py",
    "execution_realism.py",
    "requirements.txt",
]


def load_codebase() -> str:
    base = Path(__file__).parent
    chunks = []
    for fname in SOURCE_FILES:
        path = base / fname
        if path.exists():
            code = path.read_text()
            chunks.append(f"\n\n{'='*60}\n# FILE: {fname}\n{'='*60}\n{code}")
        else:
            chunks.append(f"\n\n# FILE: {fname}  (not found)")
    return "\n".join(chunks)


# ── Agent definitions ─────────────────────────────────────────────────────────

AGENTS: List[Dict] = [
    {
        "id":   "architect",
        "name": "Full-Stack Architect",
        "icon": "🏗️",
        "system": textwrap.dedent("""
            Act like a senior full-stack engineer who has just been handed this codebase
            and must design the ideal production-ready architecture for it.
            Analyze the existing structure, then provide:
            - Ideal system architecture (components, data flow)
            - Recommended file/folder structure
            - Database/storage schema if applicable
            - API endpoint design
            - What's missing to make this production-ready
            - Minimal but scalable next steps
            Be specific to THIS codebase, not generic. Output as structured markdown.
        """).strip(),
    },
    {
        "id":   "code_reviewer",
        "name": "Codebase Reviewer",
        "icon": "🔍",
        "system": textwrap.dedent("""
            Act like a senior engineer who just joined this unfamiliar codebase.
            Reverse-engineer the architecture and data flow, then identify:
            - Bad architecture decisions (with specific line references)
            - Duplicate or redundant logic
            - Performance bottlenecks
            - Scalability risks
            - Maintainability issues
            Then provide a clean architecture breakdown and prioritized refactoring list.
            Do NOT suggest changing functionality — only code quality and structure.
            Be specific, cite file names and patterns, not generic advice.
        """).strip(),
    },
    {
        "id":   "debugger",
        "name": "Debugging Engineer",
        "icon": "🐛",
        "system": textwrap.dedent("""
            Act like a senior debugging engineer investigating this codebase as if it were
            a live production system with reported issues.
            Step by step:
            - Trace every data flow and identify where it can break
            - Find real bugs, not theoretical ones
            - Identify hidden edge cases (what input/state will crash this?)
            - Find race conditions, null dereferences, unhandled exceptions
            - Identify silent failures (errors that get swallowed)
            For each bug: explain WHY it happens and provide the exact fix.
            Do not guess. Only report issues you can trace in the code.
        """).strip(),
    },
    {
        "id":   "perf_engineer",
        "name": "Performance Engineer",
        "icon": "⚡",
        "system": textwrap.dedent("""
            Act like a senior performance engineer optimizing this codebase for
            maximum throughput, minimum latency, and low memory usage.
            Identify:
            - CPU hotspots and tight loops
            - Unnecessary memory allocations
            - Inefficient data structures
            - Blocking I/O where async would help
            - Redundant computations that could be cached
            - Python-specific anti-patterns (e.g. list comprehension vs generator)
            Provide: ranked bottleneck list, optimization strategy, concrete code changes.
            Focus on the most impactful wins first.
        """).strip(),
    },
    {
        "id":   "clean_arch",
        "name": "Clean Architecture Engineer",
        "icon": "🧹",
        "system": textwrap.dedent("""
            Act like a senior software architect tasked with rebuilding this codebase
            using clean architecture principles (SOLID, separation of concerns, DI).
            Identify:
            - Tight coupling between modules
            - Mixed concerns (business logic in I/O layers, etc.)
            - Missing abstractions that would improve testability
            - Classes/functions doing too many things
            Provide:
            - Proposed new folder structure
            - Which classes/modules need splitting
            - Interface/protocol definitions that should exist
            - Concrete refactored code examples
            Do NOT change product behavior. Improve architecture only.
        """).strip(),
    },
    {
        "id":   "systems_architect",
        "name": "Systems Architect",
        "icon": "⚙️",
        "system": textwrap.dedent("""
            Act like a senior systems architect designing the infrastructure for this
            application to handle real production traffic.
            Design:
            - Deployment topology (processes, services, queues)
            - Data flow between components
            - Caching strategy (what to cache, where, TTL)
            - Rate limiting and backpressure design
            - Failure modes and circuit breakers
            - Horizontal scaling approach
            - What would break first under load and how to fix it
            Be specific to this codebase — don't give generic cloud architecture advice.
        """).strip(),
    },
    {
        "id":   "frontend_engineer",
        "name": "Frontend Engineer",
        "icon": "🖥️",
        "system": textwrap.dedent("""
            Act like a senior frontend engineer reviewing this project from a
            user-facing and developer-experience perspective.
            This project is a trading/research tool. Assess:
            - What monitoring/dashboard UI would be most valuable
            - What CLI output improvements would help operators
            - What logging format would be most useful in production
            - Component design if a web UI were added
            - Developer experience: how easy is it to run, configure, debug?
            - What documentation is missing that would hurt new contributors
            Provide concrete recommendations with examples.
        """).strip(),
    },
    {
        "id":   "tech_lead",
        "name": "Technical Lead",
        "icon": "👨‍💼",
        "system": textwrap.dedent("""
            Act like a senior technical lead responsible for this codebase for the
            next 5 years. Think long-term.
            Before anything else, challenge the design decisions:
            - What assumptions does this code make that could be wrong?
            - What will be painful to change in 6 months?
            - Where is complexity being added without clear justification?
            - What is the single biggest technical risk in this project?
            Then provide:
            - Top 3 decisions you'd make differently and why
            - Tradeoff analysis for each
            - A prioritized 30/60/90 day improvement roadmap
            Be opinionated. Good tech leads are not neutral.
        """).strip(),
    },
    {
        "id":   "security_auditor",
        "name": "Security Auditor",
        "icon": "🔒",
        "system": textwrap.dedent("""
            Act like a senior security engineer auditing this codebase before
            production deployment.
            Inspect for:
            - Hardcoded secrets or credentials
            - API key exposure risks
            - Input validation gaps
            - Injection vulnerabilities (prompt injection if LLM calls exist)
            - Insecure deserialization
            - Insufficient logging of security events
            - Dependency vulnerabilities (check requirements.txt)
            - Private key / wallet handling risks (this is a trading bot)
            For each finding: severity (CRITICAL/HIGH/MEDIUM/LOW), attack scenario,
            and exact fix. This is a financial application — treat it accordingly.
        """).strip(),
    },
    {
        "id":   "devops_engineer",
        "name": "DevOps Engineer",
        "icon": "🚀",
        "system": textwrap.dedent("""
            Act like a senior DevOps engineer preparing this application for production.
            Design:
            - Dockerfile and docker-compose setup
            - CI/CD pipeline (GitHub Actions recommended)
            - Environment variable management
            - Health checks and readiness probes
            - Logging pipeline (structured logs → aggregator)
            - Alerting strategy (what metrics to alert on)
            - Graceful shutdown handling
            - Secrets management approach
            - Deployment checklist before going live
            Provide concrete config files and scripts, not just advice.
        """).strip(),
    },
]

COORDINATOR_SYSTEM = textwrap.dedent("""
    You are the engineering team coordinator. You have received analysis reports from
    10 specialized engineers who each reviewed the same codebase from their own angle.

    Your job:
    1. Synthesize all findings — find patterns, where multiple agents agree (high confidence),
       and where they disagree (needs discussion)
    2. Produce a MASTER REPORT with these sections:
       - Executive Summary (3-5 bullets: the most critical findings)
       - Cross-Cutting Issues (problems identified by 2+ agents)
       - Priority Fix List (ranked P0/P1/P2 with owner agent and effort estimate)
       - Conflict Resolution (where agents disagreed and your recommendation)
       - 30-day Action Plan (concrete ordered steps)
    3. Be decisive. Pick the best recommendation when agents conflict.
    4. Flag anything that is a BLOCKING issue before production.

    Format as clean markdown. This is the final report the team will act on.
""").strip()


# ── Core runner ───────────────────────────────────────────────────────────────

class MessageBus:
    """Shared memory for agent findings"""

    def __init__(self):
        self._messages: Dict[str, str] = {}

    def post(self, agent_id: str, content: str):
        self._messages[agent_id] = content

    def get_all(self, exclude: str = None) -> str:
        parts = []
        for aid, content in self._messages.items():
            if aid == exclude:
                continue
            agent = next((a for a in AGENTS if a["id"] == aid), None)
            name = agent["name"] if agent else aid
            icon = agent["icon"] if agent else "🤖"
            parts.append(f"\n\n{'─'*60}\n{icon} {name} says:\n{'─'*60}\n{content}")
        return "\n".join(parts)

    def summary_for(self, agent_id: str) -> str:
        others = self.get_all(exclude=agent_id)
        if not others:
            return ""
        return (
            f"\n\nThe following findings have been shared by your fellow engineers "
            f"on the same codebase. React to anything relevant — agree, disagree, "
            f"or add detail:\n{others}"
        )


async def run_agent(
    client: anthropic.Anthropic,
    agent: Dict,
    codebase: str,
    bus: MessageBus,
    round2: bool = False,
) -> str:
    icon = agent["icon"]
    name = agent["name"]

    if round2:
        user_msg = (
            f"You have already reviewed the codebase. Now read what your fellow "
            f"engineers found and add any cross-cutting observations, corrections, "
            f"or additional depth to your earlier findings."
            f"{bus.summary_for(agent['id'])}"
        )
        print(f"  {icon} {name} — reacting to peers...")
    else:
        user_msg = (
            f"Here is the complete codebase to analyze:\n{codebase}\n\n"
            f"Provide your full analysis according to your role."
        )
        print(f"  {icon} {name} — analyzing...")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",   # fast + cheap for 10 agents
        max_tokens=2048,
        system=agent["system"],
        messages=[{"role": "user", "content": user_msg}],
    )
    result = response.content[0].text

    if round2:
        existing = bus._messages.get(agent["id"], "")
        bus.post(agent["id"], existing + "\n\n### Cross-Agent Observations\n" + result)
    else:
        bus.post(agent["id"], result)

    print(f"  {icon} {name} — done ✓")
    return result


async def run_coordinator(client: anthropic.Anthropic, bus: MessageBus) -> str:
    print("\n  🧠 Coordinator — synthesizing all findings...")

    all_findings = bus.get_all()
    user_msg = (
        f"Here are the findings from all 10 specialized engineers:\n{all_findings}\n\n"
        f"Produce the master report."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",   # best model for synthesis
        max_tokens=4096,
        system=COORDINATOR_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


async def run_all(fast: bool = False) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "\n❌ ANTHROPIC_API_KEY not set.\n"
            "   export ANTHROPIC_API_KEY='sk-ant-...'\n"
        )

    client = anthropic.Anthropic(api_key=api_key)
    bus    = MessageBus()

    print("\n" + "="*70)
    print("  🤖 MULTI-AGENT CODEBASE ANALYSIS SYSTEM")
    print("="*70)
    print(f"  Project:  {Path(__file__).parent.name}")
    print(f"  Agents:   {len(AGENTS)}")
    print(f"  Mode:     {'fast (no cross-talk)' if fast else 'full (2 rounds + synthesis)'}")
    print("="*70)

    codebase = load_codebase()

    # ── Round 1: independent analysis ────────────────────────────────────────
    print("\n📋 Round 1 — Independent Analysis\n")
    tasks = [run_agent(client, agent, codebase, bus, round2=False) for agent in AGENTS]
    await asyncio.gather(*tasks)

    # ── Round 2: cross-agent reaction (skip in fast mode) ────────────────────
    if not fast:
        print("\n💬 Round 2 — Cross-Agent Discussion\n")
        tasks = [run_agent(client, agent, codebase, bus, round2=True) for agent in AGENTS]
        await asyncio.gather(*tasks)

    # ── Coordinator synthesis ─────────────────────────────────────────────────
    print("\n🧠 Synthesis\n")
    report = await run_coordinator(client, bus)

    return report, bus


async def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Codebase Analysis")
    parser.add_argument("--fast",   action="store_true", help="Skip round-2 cross-talk")
    parser.add_argument("--output", type=str, default=None, help="Save report to file")
    args = parser.parse_args()

    report, bus = await run_all(fast=args.fast)

    print("\n" + "="*70)
    print("  📄 MASTER REPORT")
    print("="*70)
    print(report)

    # Individual agent reports
    print("\n" + "="*70)
    print("  📁 INDIVIDUAL AGENT REPORTS")
    print("="*70)
    for agent in AGENTS:
        finding = bus._messages.get(agent["id"], "")
        print(f"\n{agent['icon']} {agent['name']}")
        print("─" * 60)
        print(finding[:1500] + ("..." if len(finding) > 1500 else ""))

    # Save if requested
    output_path = args.output or f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(output_path, "w") as f:
        f.write(f"# Multi-Agent Codebase Analysis\n")
        f.write(f"*Generated: {datetime.now().isoformat()}*\n\n")
        f.write("---\n\n## Master Report\n\n")
        f.write(report)
        f.write("\n\n---\n\n## Individual Agent Reports\n\n")
        for agent in AGENTS:
            finding = bus._messages.get(agent["id"], "")
            f.write(f"\n### {agent['icon']} {agent['name']}\n\n{finding}\n\n")

    print(f"\n\n💾 Full report saved to: {output_path}")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
