from agents.base import BaseAgent


class WorkspaceArchitectAgent(BaseAgent):
    name = "workspace_architect"

    def run(self, task, context=None):
        return {"agent": self.name, "reply": f"WorkspaceArchitect: {task}"}