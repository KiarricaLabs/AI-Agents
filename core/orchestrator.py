from typing import Dict, Any, Optional
from agents.registry import AgentRegistry


class Orchestrator:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def dispatch(self, agent_name: str, task: str, context: Optional[Dict[str, Any]] = None):
        manifest = self.registry.get(agent_name)
        if not manifest:
            raise ValueError(f"Unknown agent: {agent_name}")
        # Agent classes resolved by name (simple mapping)
        from agents.tutor.agent import TutorAgent
        from agents.soundboard.agent import SoundboardAgent
        from agents.communications.agent import CommunicationsAgent
        from agents.executive_assistant.agent import ExecutiveAssistantAgent
        from agents.workspace_architect.agent import WorkspaceArchitectAgent
        from agents.strategist.agent import StrategistAgent
        cls_map = {"tutor": TutorAgent, "soundboard": SoundboardAgent,
                   "communications": CommunicationsAgent, "executive_assistant": ExecutiveAssistantAgent,
                   "workspace_architect": WorkspaceArchitectAgent, "strategist": StrategistAgent}
        cls = cls_map.get(agent_name)
        if not cls:
            raise ValueError(f"No implementation for {agent_name}")
        agent = cls(memory=None)
        return agent.run(task, context)