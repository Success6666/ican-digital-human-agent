"""Deterministic interview workflow; model/RAG orchestration can be injected later."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from .models import (
    CreateInterviewRequest,
    InterviewEvaluation,
    InterviewSession,
    InterviewStage,
    InterviewTurn,
    InterviewTurnRequest,
    InterviewTurnResponse,
)


class InterviewService:
    def __init__(
        self,
        *,
        retrieve: Callable[[str, str, str], Awaitable[list[str]]] | None = None,
    ) -> None:
        self.retrieve = retrieve
        self._sessions: dict[tuple[str, str], InterviewSession] = {}

    async def create(self, owner_id: str, request: CreateInterviewRequest) -> InterviewSession:
        session = InterviewSession(
            session_id=uuid4().hex,
            owner_id=owner_id,
            job_title=request.job_title,
            company=request.company,
            mode=request.mode,
            resume_document_id=request.resume_document_id,
            job_document_id=request.job_document_id,
            company_document_id=request.company_document_id,
        )
        self._sessions[(owner_id, session.session_id)] = session
        return session

    async def turn(self, owner_id: str, session_id: str, request: InterviewTurnRequest) -> InterviewTurnResponse:
        session = self._get(owner_id, session_id)
        if request.action == "interrupt":
            session.interrupted = True
            return InterviewTurnResponse(session=session, question="面试已暂停，请准备好后继续。")
        if request.action == "resume":
            session.interrupted = False
            return InterviewTurnResponse(session=session, question=self._next_question(session))
        if session.interrupted:
            return InterviewTurnResponse(session=session, question="当前面试已暂停，请先恢复面试。")
        if request.action == "hint":
            return InterviewTurnResponse(session=session, question="提示：请用 STAR 结构说明背景、行动和可量化结果。")
        if request.action == "correction":
            session.turns.append(InterviewTurn(question="回答修正", answer=request.answer, action="correction"))
        elif request.action == "skip":
            session.turns.append(InterviewTurn(question=self._next_question(session), action="skip"))
        else:
            question = self._next_question(session)
            evidence = await self.retrieve(owner_id, session.job_title, request.answer) if self.retrieve else []
            score = min(100.0, max(0.0, 45.0 + min(40.0, len(request.answer) / 12)))
            session.turns.append(
                InterviewTurn(
                    question=question,
                    answer=request.answer,
                    follow_up=self._needs_follow_up(request.answer),
                    score=round(score, 2),
                    evidence=evidence[:5],
                    action="concern" if score < 65 else "positive",
                )
            )
        if len(session.turns) >= 4:
            session.stage = _next_stage(session.stage)
        return InterviewTurnResponse(session=session, question=self._next_question(session))

    async def evaluate(self, owner_id: str, session_id: str) -> InterviewEvaluation:
        session = self._get(owner_id, session_id)
        scores = {
            "expression_clarity": self._average(session, fallback=60),
            "answer_completeness": self._average(session, fallback=55),
            "job_match": self._average(session, fallback=50),
            "star_structure": self._star_score(session),
            "technical_depth": self._average(session, fallback=45),
        }
        return InterviewEvaluation(
            session_id=session.session_id,
            stage=session.stage,
            completed=session.stage is InterviewStage.COMPLETED,
            scores={key: round(value, 2) for key, value in scores.items()},
            suggestions=["补充可量化结果", "用 STAR 结构压缩表达", "结合目标公司的业务场景说明决策依据"],
        )

    def _get(self, owner_id: str, session_id: str) -> InterviewSession:
        session = self._sessions.get((owner_id, session_id))
        if session is None:
            raise KeyError("interview session not found")
        return session

    @staticmethod
    def _next_question(session: InterviewSession) -> str:
        if session.stage is InterviewStage.FIRST:
            return f"请做一个与 {session.job_title} 相关的自我介绍。"
        if session.stage is InterviewStage.SECOND:
            return "请深入说明一个最能体现岗位能力的项目，以及最终业务结果。"
        if session.stage is InterviewStage.THIRD:
            return "如果关键指标连续两周下降，你会如何定位问题并制定方案？"
        if session.stage is InterviewStage.HR:
            return "你为什么选择这家公司？未来三年的职业规划是什么？"
        return "本轮面试已完成。"

    @staticmethod
    def _needs_follow_up(answer: str) -> bool:
        return len(answer.strip()) < 80 or not any(token in answer for token in ("结果", "提升", "%", "增长", "降低"))

    @staticmethod
    def _average(session: InterviewSession, *, fallback: float) -> float:
        scores = [turn.score for turn in session.turns if turn.score is not None]
        return sum(scores) / len(scores) if scores else fallback

    @staticmethod
    def _star_score(session: InterviewSession) -> float:
        answer = " ".join(turn.answer for turn in session.turns)
        return min(100.0, 40 + sum(token in answer for token in ("背景", "目标", "行动", "结果")) * 15)


def _next_stage(stage: InterviewStage) -> InterviewStage:
    order = list(InterviewStage)
    index = order.index(stage)
    return order[min(index + 1, len(order) - 1)]
