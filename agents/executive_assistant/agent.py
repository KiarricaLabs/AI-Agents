from agents.base import BaseAgent


class ExecutiveAssistantAgent(BaseAgent):
    name = "executive_assistant"

    def run(self, task, context=None, stream=False, on_chunk=None):
        return self._ground(task, context, stream=stream, on_chunk=on_chunk)
