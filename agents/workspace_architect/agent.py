from agents.base import BaseAgent


class WorkspaceArchitectAgent(BaseAgent):
    name = "workspace_architect"

    def run(self, task, context=None, stream=False, on_chunk=None):
        return self._ground(task, context, stream=stream, on_chunk=on_chunk)
