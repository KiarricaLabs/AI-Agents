from agents.base import BaseAgent


class StrategistAgent(BaseAgent):
    name = "strategist"

    def run(self, task, context=None):
        return self._ground(task, context)
