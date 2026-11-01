from agents.base import BaseAgent


class SoundboardAgent(BaseAgent):
    name = "soundboard"

    def run(self, task, context=None):
        return self._ground(task, context)
