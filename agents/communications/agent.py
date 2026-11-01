from agents.base import BaseAgent


class CommunicationsAgent(BaseAgent):
    name = "communications"

    def run(self, task, context=None):
        return self._ground(task, context)
