from agents.base import BaseAgent


class TutorAgent(BaseAgent):
    name = "tutor"

    def run(self, task, context=None):
        return {"agent": self.name, "reply": f"Tutor: {task}"}