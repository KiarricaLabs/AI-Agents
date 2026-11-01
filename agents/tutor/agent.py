from agents.base import BaseAgent


class TutorAgent(BaseAgent):
    name = "tutor"

    def run(self, task, context=None):
        return self._ground(task, context)
