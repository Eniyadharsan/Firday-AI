"""
Multi-Agent System — Specialized AI agents for different domains.

Routes queries to the best agent, or orchestrates multiple agents for complex tasks.
"""

import re
from loguru import logger
from jarvis.modules import llm


# --- Agent Definitions ---

AGENTS: dict[str, dict] = {
    "research": {
        "name": "Research Agent",
        "triggers": ["research", "find out", "investigate", "look into", "study", "analyze", "compare"],
        "prompt": "You are a deep research specialist. Provide thorough, well-structured analysis with multiple perspectives. Use bullet points for clarity. Cite reasoning.",
    },
    "coding": {
        "name": "Coding Agent",
        "triggers": ["code", "program", "function", "script", "debug", "fix bug", "implement", "python", "javascript", "api", "database", "sql", "html", "css", "react", "algorithm"],
        "prompt": "You are an expert software engineer. Write clean, production-ready code with comments. Always provide complete implementations, never stubs. Include error handling.",
    },
    "travel": {
        "name": "Travel Agent",
        "triggers": ["travel", "vacation", "trip", "flight", "hotel", "itinerary", "visit", "tourism", "destination"],
        "prompt": "You are a travel planning expert. Create detailed itineraries with budgets, timing, tips, and alternatives. Consider weather, local events, and practical logistics.",
    },
    "finance": {
        "name": "Finance Agent",
        "triggers": ["budget", "invest", "savings", "money", "finance", "tax", "expense", "portfolio", "stock", "mutual fund", "crypto", "salary", "income"],
        "prompt": "You are a financial advisor. Provide clear, actionable financial guidance with calculations. Break down numbers, show ROI, compare options with tables.",
    },
    "health": {
        "name": "Health Agent",
        "triggers": ["health", "fitness", "diet", "exercise", "workout", "nutrition", "calories", "sleep", "mental health", "stress", "yoga", "meditation"],
        "prompt": "You are a health and wellness advisor. Provide evidence-based advice on fitness, nutrition, and mental health. Include specific plans, schedules, and targets.",
    },
    "career": {
        "name": "Career Agent",
        "triggers": ["resume", "job", "career", "interview", "linkedin", "portfolio", "hire", "promotion", "skills", "learning path", "certification"],
        "prompt": "You are a career strategist. Help with resumes, interview prep, skill development, and career planning. Be specific with timelines and actionable steps.",
    },
    "devops": {
        "name": "DevOps Agent",
        "triggers": ["deploy", "docker", "kubernetes", "ci/cd", "aws", "cloud", "server", "pipeline", "terraform", "nginx", "linux"],
        "prompt": "You are a DevOps engineer. Provide infrastructure solutions with exact commands, configurations, and architecture diagrams. Focus on reliability and automation.",
    },
    "planner": {
        "name": "Planning Agent",
        "triggers": ["plan", "schedule", "roadmap", "timeline", "strategy", "goal", "milestone", "deadline", "organize", "prioritize"],
        "prompt": "You are a strategic planner. Break complex goals into actionable tasks with timelines, milestones, and progress metrics. Use tables and checkboxes for clarity.",
    },
}


def detect_agent(message: str) -> str | None:
    """Detect which specialized agent should handle this query."""
    lower = message.lower()
    scores: dict[str, int] = {}

    for agent_id, agent in AGENTS.items():
        score = sum(1 for trigger in agent["triggers"] if trigger in lower)
        if score > 0:
            scores[agent_id] = score

    if not scores:
        return None

    # Return agent with highest score
    return max(scores, key=scores.get)


def get_agent_prompt(agent_id: str) -> str:
    """Get the system prompt enhancement for an agent."""
    agent = AGENTS.get(agent_id)
    if not agent:
        return ""
    return f"\n\n[SPECIALIZED MODE: {agent['name']}]\n{agent['prompt']}"


def orchestrate(message: str, base_messages: list[dict[str, str]]) -> str:
    """
    Orchestrate multi-agent response for complex queries.
    Detects if multiple agents are needed and chains them.
    """
    lower = message.lower()
    agents_needed: list[str] = []

    for agent_id, agent in AGENTS.items():
        if any(trigger in lower for trigger in agent["triggers"]):
            agents_needed.append(agent_id)

    if len(agents_needed) <= 1:
        # Single agent — just enhance the prompt
        agent_id = agents_needed[0] if agents_needed else None
        if agent_id:
            enhanced = base_messages.copy()
            enhanced[0] = {"role": "system", "content": enhanced[0]["content"] + get_agent_prompt(agent_id)}
            return llm.generate(enhanced)
        return llm.generate(base_messages)

    # Multi-agent orchestration
    logger.info(f"Multi-agent orchestration: {agents_needed}")
    results: list[str] = []

    for agent_id in agents_needed[:3]:  # Max 3 agents
        agent = AGENTS[agent_id]
        agent_messages = [
            {"role": "system", "content": f"You are the {agent['name']}. {agent['prompt']} Provide your specialized input concisely (max 3 paragraphs)."},
            {"role": "user", "content": message},
        ]
        result = llm.generate(agent_messages)
        results.append(f"**{agent['name']}:**\n{result}")

    # Final synthesis
    synthesis_messages = [
        {"role": "system", "content": "You are the lead orchestrator. Synthesize the following specialist inputs into a coherent, actionable response. Keep it concise and well-structured."},
        {"role": "user", "content": f"Original request: {message}\n\nSpecialist inputs:\n\n" + "\n\n---\n\n".join(results)},
    ]
    return llm.generate(synthesis_messages)


def list_agents() -> list[dict]:
    """List all available agents."""
    return [{"id": k, "name": v["name"], "triggers": v["triggers"]} for k, v in AGENTS.items()]
