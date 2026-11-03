from typing import Dict, Any, Optional
from agents.registry import AgentRegistry
from core.model_router import ModelRouter


# Central, stable mapping from agent slug to its concrete class. Shared by the
# conversational dispatch and the unified plan orchestration so the two only ever
# construct the exact same agent implementations (no divergent code paths).
_AGENT_CLASSES = None


def _agent_classes():
    global _AGENT_CLASSES
    if _AGENT_CLASSES is None:
        from agents.tutor.agent import TutorAgent
        from agents.soundboard.agent import SoundboardAgent
        from agents.communications.agent import CommunicationsAgent
        from agents.executive_assistant.agent import ExecutiveAssistantAgent
        from agents.workspace_architect.agent import WorkspaceArchitectAgent
        from agents.strategist.agent import StrategistAgent
        _AGENT_CLASSES = {"tutor": TutorAgent, "soundboard": SoundboardAgent,
                          "communications": CommunicationsAgent,
                          "executive_assistant": ExecutiveAssistantAgent,
                          "workspace_architect": WorkspaceArchitectAgent,
                          "strategist": StrategistAgent}
    return _AGENT_CLASSES


class Orchestrator:
    def __init__(self, registry: AgentRegistry, policy=None, router=None, memory=None,
                 user_id=None, tools=None, brand=None):
        self.policy = policy
        self.registry = registry
        self.router = router if router is not None else ModelRouter()
        self.memory = memory
        self.user_id = user_id
        self.tools = tools
        self.brand = brand

    def _build_agent(self, agent_name: str):
        manifest = self.registry.get(agent_name)
        if not manifest:
            raise ValueError(f"Unknown agent: {agent_name}")
        cls = _agent_classes().get(agent_name)
        if not cls:
            raise ValueError(f"No implementation for {agent_name}")
        return cls(memory=self.memory, router=self.router, manifest=manifest,
                   user_id=self.user_id, tools=self.tools, policy=self.policy,
                   brand=self.brand)

    def dispatch(self, agent_name: str, task: str, context: Optional[Dict[str, Any]] = None):
        from core.tracing import start_span, end_span
        span = start_span("orchestrator.dispatch", {"agent": agent_name})
        if self.policy is None:
            end_span(span)
            raise PermissionError("policy denied")
        if not self.policy.allow("system", "dispatch", agent_name):
            end_span(span)
            raise PermissionError("policy denied")
        agent = self._build_agent(agent_name)
        result = agent.run(task, context)
        from core.validation import validate_output
        ok, err = validate_output(agent_name, result)
        if not ok:
            end_span(span)
            raise ValueError(f"invalid agent output: {err}")
        end_span(span)
        return result

    def plan(self, agent_name: str, task: str, context: Optional[Dict[str, Any]] = None):
        """Preview-only coordinated plan generation.

        Builds the (coordinating) agent exactly like ``dispatch`` and asks it to
        return a structured, reviewable plan of steps. It deliberately does NOT
        invoke proposal/execution tools and never persists anything.
        """
        if self.policy is None or not self.policy.allow("system", "dispatch", agent_name):
            raise PermissionError("policy denied")
        agent = self._build_agent(agent_name)
        return agent.plan_steps(task, context)