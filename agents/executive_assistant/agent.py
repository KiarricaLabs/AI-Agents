from agents.base import BaseAgent


class ExecutiveAssistantAgent(BaseAgent):
    name = "executive_assistant"

    def run(self, task, context=None):
        return {"agent": self.name, "reply": f"ExecAssistant: {task}"}