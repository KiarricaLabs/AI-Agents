from agents.base import BaseAgent


class StrategistAgent(BaseAgent):
    name = "strategist"

    def run(self, task, context=None):
        return {"agent": self.name, "reply": f"Strategist: {task}"}