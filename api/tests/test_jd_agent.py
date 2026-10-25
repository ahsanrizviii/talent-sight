from app.agents import jd_agent
from app.agents.jd_agent import BriefCheck, DraftWeights, JobDraft
from app.llm import LLMUnavailable

COMPLETE_BRIEF = BriefCheck(job_title="Backend Developer", missing_details=[], rounds_described=True)
INCOMPLETE_BRIEF = BriefCheck(
    job_title="Backend Developer", missing_details=["How many years of experience?"], rounds_described=True
)
GOOD_DRAFT = JobDraft(
    title="Mid-level Backend Developer",
    description="About the role ...",
    required_skills=["Python", "SQL"],
    preferred_skills=["Docker"],
    qualifications=["Bachelor's degree in Computer Science or equivalent experience"],
    min_experience_years=3,
    selection_criteria="Strong Python and database skills.",
    weights=DraftWeights(technical_skills=40, experience=30, qualifications=15, jd_match=15),
)


class FakeLLM:

    def __init__(self, brief_checks: list, drafts: list):
        self.brief_checks = list(brief_checks)
        self.drafts = list(drafts)
        self.prompts: list[str] = []

    def __call__(self, system_prompt, user_prompt, answer_shape):
        self.prompts.append(user_prompt)
        answers = self.brief_checks if answer_shape is BriefCheck else self.drafts
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def use_fake_llm(monkeypatch, brief_checks: list, drafts: list) -> FakeLLM:
    fake = FakeLLM(brief_checks, drafts)
    monkeypatch.setattr(jd_agent, "ask_llm", fake)
    return fake


def start(client, headers, brief: str) -> dict:
    return client.post("/api/jd-chat", json={"brief": brief}, headers=headers).json()


def reply(client, headers, chat: dict, **body) -> dict:
    return client.post(f"/api/jd-chat/{chat['thread_id']}/reply", json=body, headers=headers).json()


def test_draft_is_published_only_after_approval(client, auth_headers, monkeypatch):
    fake = use_fake_llm(monkeypatch, [COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "Mid-level Python backend developer, 3 years, SQL")
    assert chat["status"] == "waiting" and chat["kind"] == "draft"
    assert client.get("/api/public/jobs").json() == []  

    done = reply(client, auth_headers, chat, approve=True)
    assert done["status"] == "done"
    public = client.get(f"/api/public/jobs/{done['slug']}").json()
    assert public["required_skills"] == ["Python", "SQL"]
    assert "Company policies" in fake.prompts[-1]  
    assert "[bjit-hiring-policies.pdf]" in fake.prompts[-1] 


def test_missing_details_are_asked_first(client, auth_headers, monkeypatch):
    fake = use_fake_llm(monkeypatch, [INCOMPLETE_BRIEF, COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "We need a backend developer")
    assert chat["kind"] == "questions"
    assert chat["questions"] == ["How many years of experience?"]

    after = reply(client, auth_headers, chat, text="3 years, Python and SQL")
    assert after["kind"] == "draft"
    assert "3 years, Python and SQL" in fake.prompts[1]  


def test_requested_changes_go_into_the_next_draft(client, auth_headers, monkeypatch):
    senior = GOOD_DRAFT.model_copy(update={"title": "Senior Backend Developer", "min_experience_years": 5})
    fake = use_fake_llm(monkeypatch, [COMPLETE_BRIEF], [GOOD_DRAFT, senior])
    chat = start(client, auth_headers, "Python backend developer, 3 years, SQL")

    changed = reply(client, auth_headers, chat, approve=False, text="Make it a senior role")
    assert changed["kind"] == "draft"
    assert changed["draft"]["title"] == "Senior Backend Developer"
    assert "Make it a senior role" in fake.prompts[-1]


def test_a_draft_that_breaks_the_rules_is_rewritten_once(client, auth_headers, monkeypatch):
    bad_weights = DraftWeights(technical_skills=90, experience=30, qualifications=15, jd_match=15)
    bad_draft = GOOD_DRAFT.model_copy(update={"weights": bad_weights})  
    fake = use_fake_llm(monkeypatch, [COMPLETE_BRIEF], [bad_draft, GOOD_DRAFT])
    chat = start(client, auth_headers, "Python backend developer, 3 years, SQL")
    assert chat["kind"] == "draft"
    assert chat["draft"]["weights"]["technical_skills"] == 40
    assert "add up to 100" in fake.prompts[-1]  


def test_ai_failure_gives_a_clear_error(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [LLMUnavailable("The AI service is not available right now. Please try again.")], [])
    chat = start(client, auth_headers, "Python backend developer, 3 years, SQL")
    assert chat["status"] == "failed"
    assert chat["message"] == "The AI service is not available right now. Please try again."
    response = client.post(f"/api/jd-chat/{chat['thread_id']}/reply", json={"approve": True}, headers=auth_headers)
    assert response.status_code == 409


def test_the_rounds_are_asked_about_when_the_brief_does_not_give_them(client, auth_headers, monkeypatch):
    no_rounds = BriefCheck(job_title="Backend Developer", missing_details=["How many years of experience?"])
    use_fake_llm(monkeypatch, [no_rounds, COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "We need a backend developer")
    assert chat["kind"] == "questions"
    assert chat["questions"] == ["How many years of experience?", jd_agent.ROUNDS_QUESTION]


def test_the_rounds_question_is_not_asked_twice(client, auth_headers, monkeypatch):
    asked = BriefCheck(job_title="Backend Developer", missing_details=["How many interview rounds are there?"])
    use_fake_llm(monkeypatch, [asked, COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "Python backend developer, 3 years, SQL")
    assert chat["questions"] == ["How many interview rounds are there?"]


def test_cv_screening_and_the_final_decision_never_become_rounds(client, auth_headers, monkeypatch):
    steps = [
        jd_agent.DraftRound(name="CV screening", focus="resume match"),
        jd_agent.DraftRound(name="Technical interview", focus="coding and backend concepts"),
        jd_agent.DraftRound(name="HR interview", focus="communication, salary", type="hr"),
        jd_agent.DraftRound(name="Final decision", focus="hiring team review"),
    ]
    use_fake_llm(monkeypatch, [COMPLETE_BRIEF], [GOOD_DRAFT.model_copy(update={"interview_rounds": steps})])
    chat = start(client, auth_headers, "Python backend developer, 3 years, SQL, technical then HR interview")
    rounds = chat["draft"]["interview_rounds"]
    assert [(r["name"], r["type"]) for r in rounds] == [("Technical interview", "technical"), ("HR interview", "hr")]
