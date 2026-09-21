"""Interview training models and state transitions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class InterviewMode(StrEnum):
    STRUCTURED = "structured"
    SPECIALIZED = "specialized"
    PRESSURE = "pressure"


class InterviewStage(StrEnum):
    FIRST = "first_round"
    SECOND = "second_round"
    THIRD = "third_round"
    HR = "hr_round"
    COMPLETED = "completed"


class InterviewTurn(BaseModel):
    question: str
    answer: str = ""
    follow_up: bool = False
    score: float | None = Field(default=None, ge=0, le=100)
    evidence: list[str] = Field(default_factory=list)
    action: str = "neutral"


class InterviewSession(BaseModel):
    session_id: str
    owner_id: str
    job_title: str
    company: str = ""
    mode: InterviewMode
    stage: InterviewStage = InterviewStage.FIRST
    resume_document_id: str | None = None
    job_document_id: str | None = None
    company_document_id: str | None = None
    turns: list[InterviewTurn] = Field(default_factory=list)
    interrupted: bool = False


class CreateInterviewRequest(BaseModel):
    job_title: str = Field(min_length=1, max_length=200)
    company: str = Field(default="", max_length=200)
    mode: InterviewMode = InterviewMode.STRUCTURED
    resume_document_id: str | None = Field(default=None, max_length=128)
    job_document_id: str | None = Field(default=None, max_length=128)
    company_document_id: str | None = Field(default=None, max_length=128)


class InterviewTurnRequest(BaseModel):
    answer: str = Field(default="", max_length=8000)
    action: str = Field(default="answer", pattern="^(answer|hint|skip|correction|interrupt|resume)$")


class InterviewEvaluation(BaseModel):
    session_id: str
    stage: InterviewStage
    completed: bool
    scores: dict[str, float]
    suggestions: list[str]


class InterviewTurnResponse(BaseModel):
    session: InterviewSession
    question: str
