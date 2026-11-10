from agents.base import BaseAgent


class CommunicationsAgent(BaseAgent):
    name = "communications"

    def run(self, task, context=None, stream=False, on_chunk=None):
        return self._ground(task, context, stream=stream, on_chunk=on_chunk)
