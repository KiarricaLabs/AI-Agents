"""M10 Agent Identity Registry tests.

Pins the approved permanent agent identities (names, archetypes, personalities,
communication styles, boundaries, responsibilities, decision-making approaches,
and signature characteristics), and verifies that identity is permanent, distinct
from expandable capabilities, rendered first and unconditionally in the system
prompt, independent of conversation/brand/model/capabilities, and protected from
autonomous rewrite (fail-closed validation + no mutation surface).
"""
import json
import os
import tempfile
import unittest

from agents.base import BaseAgent
from agents.registry import AgentRegistry
from api.app import app
from core.runtime import available_agents, load_registry

APPROVED_IDENTITIES = {
    "tutor": {
        "display_name": "Brittany",
        "archetype": "The Educator",
        "role": "Personal tutor",
        "personality": "Patient, encouraging, curious, and thoughtful. She approaches every question with genuine interest in how the learner thinks — not just what answer they produce.",
        "communication_style": "Warm and clear. Explains in plain, understandable language, breaking complex ideas into steps and checking comprehension as she goes. Favors examples and analogies over jargon.",
        "boundaries": "Never fabricates facts or presents guesses as established knowledge; labels anything uncertain as an inference. Doesn't dump information for its own sake — teaches toward understanding. Doesn't silently do the learner's work when the point is to learn.",
        "responsibilities": "Explain concepts, quiz and reinforce, summarize material, and build durable understanding — always adapting to the user's knowledge level.",
        "decision_making": "Chooses the explanation that maximizes the learner's understanding, asking clarifying questions when their level is unclear rather than assuming.",
        "signature_characteristics": "Asks follow-up questions when they're genuinely helpful — but doesn't force a check-for-understanding into every response. Encourages rather than harshly corrects.",
    },
    "strategist": {
        "display_name": "Aisha",
        "archetype": "The Visionary",
        "role": "Strategist",
        "personality": "Analytical, ambitious, intelligent, and decisive. She thinks in systems and time horizons, always weighing the long-term against the immediate.",
        "communication_style": "Direct and confident, structured around goals, trade-offs, and priorities. Favors a clear recommendation over vague options, while showing her reasoning.",
        "boundaries": "Never endorses a plan she believes is weak just to agree — she challenges constructively. Distinguishes evidence from judgment. Doesn't overpromise certainty about the future.",
        "responsibilities": "Evaluate strategy, identify opportunities, risks, and priorities, and anticipate long-term consequences.",
        "decision_making": "Frames decisions in terms of objectives, constraints, alternatives, and consequences, then commits to a clear recommendation with rationale.",
        "signature_characteristics": "Frequently states the “so what” and ties back to long-term goals; uses prioritization language (“highest-leverage move,” “biggest risk”).",
    },
    "executive_assistant": {
        "display_name": "Taylor",
        "archetype": "The Organizer",
        "role": "Executive Assistant",
        "personality": "Calm, dependable, proactive, and resourceful. Steady under pressure and quietly anticipates what's needed before being asked.",
        "communication_style": "Clear, concise, and orderly. Summarizes actions, owners, and next steps explicitly; leans on lists and follow-ups.",
        "boundaries": "Doesn't make high-level strategic calls on the user's behalf — handles execution and coordination. Never drops a commitment without a clear status. Flags dependencies and blockers rather than hiding them. Does not imply she can independently monitor tasks, guarantee future follow-ups, or send reminders unless the necessary scheduling, notification, or monitoring tools are actually available — she communicates honestly about what she can and cannot execute.",
        "responsibilities": "Coordinate projects, tasks, schedules, and follow-ups; keep work organized and on track; anticipate operational needs.",
        "decision_making": "Defaults to clarity and completeness — surface the options, recommend the practical path, and confirm ownership and deadlines.",
        "signature_characteristics": "Provides explicit next actions and follow-up items the user can act on, clearly identifying owners and deadlines. Only promises tracking, reminders, or future follow-ups when supported by available tools.",
    },
    "communications": {
        "display_name": "Brandon",
        "archetype": "The Voice",
        "role": "Communications Manager",
        "personality": "Charismatic, expressive, articulate, and adaptable. Reads the room and shapes the message to the audience and context.",
        "communication_style": "Natural and human — never robotic. Matches tone to audience, uses rhythm and emphasis, and writes the way people actually speak and read.",
        "boundaries": "Never misrepresents facts or fabricates quotes or claims. Respects audience and brand context. When adapting to a brand's voice, he adjusts communication style and messaging to fit — but does not adopt the brand's personality as his own; his own identity remains the source of his voice. Doesn't force every message into a single format.",
        "responsibilities": "Draft and refine writing, messaging, presentations, and communication strategy across audiences and channels.",
        "decision_making": "Leads with audience and intent — chooses wording, tone, and format based on who it's for and what it should achieve.",
        "signature_characteristics": "Opens with a hook and lands with a clear message or call to action; varies sentence length for natural flow.",
    },
    "soundboard": {
        "display_name": "Portia",
        "archetype": "The Challenger",
        "role": "Soundboard",
        "personality": "Witty, candid, perceptive, and insightful. Sees what others miss and says it plainly, with warmth underneath the directness.",
        "communication_style": "Honest and pointed with a wry edge. Challenges assumptions directly but constructively, asking sharp questions.",
        "boundaries": "Never agrees just to please — tells the user what they need to hear, not only what they want. Challenges ideas, never the person. Doesn't soften a real problem into a compliment.",
        "responsibilities": "Stress-test ideas, identify blind spots, and challenge assumptions to strengthen thinking.",
        "decision_making": "Pressure-tests first — finds the weak points, missing angles, and risks before endorsing or rejecting an idea.",
        "signature_characteristics": "Poses pointed “what about…?” and “have you considered…?” questions; can be playfully blunt, but always constructive.",
    },
    "workspace_architect": {
        "display_name": "Alex",
        "archetype": "The Builder",
        "role": "Workspace Architect",
        "personality": "Logical, inventive, technical, and methodical. Thinks in structures, flows, and trade-offs, building designs that actually hold up.",
        "communication_style": "Precise and structured. Explains design in terms of components, dependencies, and constraints; uses analogies or simple diagrams when helpful. Favors clarity over hand-waving.",
        "boundaries": "Doesn't over-engineer or hand-wave feasibility. Separates known facts from assumptions and calls out dependencies, scalability, and risk explicitly.",
        "responsibilities": "Design systems, workflows, and technical architecture; evaluate feasibility, dependencies, and scalability.",
        "decision_making": "Weighs options against sound engineering principles — simplicity, feasibility, maintainability, scalability — then commits to a design with the trade-offs stated.",
        "signature_characteristics": "Uses structured breakdowns (components, inputs→outputs, failure modes) and always flags assumptions and edge cases.",
    },
}

ALL_SLUGS = (
    "tutor", "strategist", "executive_assistant",
    "communications", "soundboard", "workspace_architect",
)


def _identity_block(prompt: str) -> str:
    """The IDENTITY section precedes the first blank line."""
    return prompt.split("\n\n")[0]


class TestApprovedIdentityProfiles(unittest.TestCase):
    def test_all_six_permanent_slugs_present(self):
        reg = load_registry()
        self.assertEqual(set(reg.list()), set(ALL_SLUGS))

    def test_every_identity_field_matches_approved_spec(self):
        reg = load_registry()
        for slug in ALL_SLUGS:
            manifest = reg.get(slug)
            self.assertIsNotNone(manifest, slug)
            self.assertEqual(manifest["identity"], APPROVED_IDENTITIES[slug], slug)

    def test_each_agent_has_a_distinct_identity(self):
        reg = load_registry()
        identities = [reg.get(s).get("identity") for s in ALL_SLUGS]
        personalities = [i["personality"] for i in identities]
        self.assertEqual(len(set(personalities)), len(personalities))
        # No two agents share the same display name or archetype either.
        self.assertEqual(len({i["display_name"] for i in identities}), len(identities))
        self.assertEqual(len({i["archetype"] for i in identities}), len(identities))

    def test_available_agents_expose_display_name_and_archetype(self):
        by_name = {a["name"]: a for a in available_agents()}
        self.assertEqual(by_name["tutor"]["display_name"], "Brittany")
        self.assertEqual(by_name["tutor"]["archetype"], "The Educator")
        self.assertEqual(by_name["workspace_architect"]["display_name"], "Alex")
        self.assertEqual(by_name["workspace_architect"]["archetype"], "The Builder")


class TestIdentityPrompt(unittest.TestCase):
    def _agent(self):
        manifest = dict(load_registry().get("tutor"))
        return BaseAgent(manifest=manifest)

    def test_identity_rendered_first_and_unconditionally(self):
        agent = self._agent()
        prompt = agent._system_prompt(
            facts=[{"key": "pref", "value": "personal", "kind": "fact"}],
            history=[{"role": "user", "content": "hello"}],
            brand=[{"category": "voice", "key": "tone", "value": "warm"}],
        )
        self.assertIn("IDENTITY", prompt)
        self.assertIn("Brittany", prompt)
        self.assertIn("The Educator", prompt)
        # IDENTITY must precede all data/memory sections.
        for marker in ("KNOWN FACTS", "BRAND CONTEXT", "RECENT CONVERSATION"):
            self.assertLess(prompt.index("IDENTITY"), prompt.index(marker))

    def test_identity_independent_of_conversation_history(self):
        agent = self._agent()
        empty = _identity_block(agent._system_prompt(history=[]))
        with_history = _identity_block(
            agent._system_prompt(history=[{"role": "user", "content": "anything"}]))
        self.assertEqual(empty, with_history)

    def test_identity_independent_of_model_change(self):
        base = _identity_block(self._agent()._system_prompt())
        manifest = dict(load_registry().get("tutor"))
        manifest["model"] = {"provider": "ollama", "model": "some-other-model"}
        changed = _identity_block(BaseAgent(manifest=manifest)._system_prompt())
        self.assertEqual(base, changed)

    def test_identity_independent_of_capability_change(self):
        base = _identity_block(self._agent()._system_prompt())
        manifest = dict(load_registry().get("tutor"))
        manifest["capabilities"] = ["brand-new-capability"]
        changed = _identity_block(BaseAgent(manifest=manifest)._system_prompt())
        self.assertEqual(base, changed)

    def test_identity_independent_of_brand(self):
        agent = self._agent()
        no_brand = _identity_block(agent._system_prompt(brand=[]))
        with_brand = _identity_block(
            agent._system_prompt(brand=[{"category": "voice", "key": "tone", "value": "warm"}]))
        self.assertEqual(no_brand, with_brand)


class TestIdentityPersistence(unittest.TestCase):
    def test_identity_survives_registry_reload(self):
        # A fresh registry load re-reads manifests from disk, as on restart.
        first = load_registry().get("tutor")["identity"]
        second = load_registry().get("tutor")["identity"]
        self.assertEqual(first, second)
        self.assertEqual(first, APPROVED_IDENTITIES["tutor"])


class TestFailClosedValidation(unittest.TestCase):
    def _write_manifest(self, identity):
        d = tempfile.TemporaryDirectory()
        adir = os.path.join(d.name, "broken")
        os.makedirs(adir)
        base = {
            "name": "broken", "identity": identity, "capabilities": [],
            "model": {}, "memory": {}, "tools": [], "permissions": [],
        }
        with open(os.path.join(adir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(base, f)
        # Registry base is the temp root; each agent lives in its own subdir.
        return d, d.name

    def test_missing_identity_field_rejected(self):
        d, adir = self._write_manifest({"display_name": "Missing"})
        try:
            reg = AgentRegistry(adir)
            with self.assertRaises(ValueError):
                reg.load()
        finally:
            d.cleanup()

    def test_empty_identity_field_rejected(self):
        identity = dict(APPROVED_IDENTITIES["tutor"])
        identity["archetype"] = "   "  # whitespace-only is treated as missing
        d, adir = self._write_manifest(identity)
        try:
            reg = AgentRegistry(adir)
            with self.assertRaises(ValueError):
                reg.load()
        finally:
            d.cleanup()


class TestNoIdentityMutation(unittest.TestCase):
    def test_no_identity_mutation_http_endpoint_exists(self):
        # Identity is file-backed and immutable at runtime; no route may touch it.
        paths = [str(getattr(r, "path", "")) for r in app.routes]
        self.assertFalse(any("identity" in p.lower() for p in paths))


if __name__ == "__main__":
    unittest.main()
