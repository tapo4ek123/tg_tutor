from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Diagnostic(StrictModel):
    introduction: str
    questions: list[str] = Field(min_length=2, max_length=4)


class Module(StrictModel):
    title: str
    outcome: str
    minutes: int = Field(ge=5, le=180)
    success_criteria: list[str] = Field(min_length=1, max_length=4)


class Plan(StrictModel):
    goal: str
    diagnostic_feedback: str
    feasibility_note: str
    modules: list[Module] = Field(min_length=3, max_length=6)
    final_challenge: str


class Lesson(StrictModel):
    title: str
    explanation: str
    example: str
    task: str
    rubric: list[str] = Field(min_length=2, max_length=4)
    reference_answer: str
    hints: list[str] = Field(min_length=3, max_length=3)


class CriterionScore(StrictModel):
    criterion: str
    score: int = Field(ge=0, le=2)
    explanation: str


class Grade(StrictModel):
    criteria: list[CriterionScore] = Field(min_length=2, max_length=4)
    feedback: str
    gaps: list[str] = Field(max_length=5)


class Attempt(StrictModel):
    module_index: int
    task: str
    answer: str
    score: float
    passed: bool
    hints_used: int
    feedback: str
    gaps: list[str]


class LearningState(StrictModel):
    stage: Literal[
        "goal", "experience", "budget", "deadline", "diagnostic", "plan_review", "learning", "done"
    ] = "goal"
    goal: str = ""
    experience: str = ""
    minutes_per_session: int = 30
    sessions_per_week: int = 3
    deadline: str = ""
    diagnostic: Diagnostic | None = None
    diagnostic_answer: str = ""
    plan: Plan | None = None
    module_index: int = 0
    lesson: Lesson | None = None
    hints_used: int = 0
    attempts: list[Attempt] = Field(default_factory=list)
    adaptations: list[str] = Field(default_factory=list)
    focus: list[str] = Field(default_factory=list)
    pending_request: str | None = None
    input_mode: Literal["answer", "question"] = "answer"
