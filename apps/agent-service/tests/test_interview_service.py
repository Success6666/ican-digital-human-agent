from app.interview.models import (
    CreateInterviewRequest,
    InterviewStage,
    InterviewTurnRequest,
)
from app.interview.service import InterviewService


async def test_interview_progresses_through_rounds_and_evaluates() -> None:
    service = InterviewService()
    session = await service.create("user-1", CreateInterviewRequest(job_title="AI 产品经理", company="示例公司"))

    for index in range(4):
        response = await service.turn(
            "user-1",
            session.session_id,
            InterviewTurnRequest(answer=f"背景和目标明确，采取行动后结果提升 {index + 1}%。"),
        )

    assert response.session.stage is InterviewStage.SECOND
    evaluation = await service.evaluate("user-1", session.session_id)
    assert evaluation.scores["star_structure"] >= 80
    assert "expression_clarity" in evaluation.scores


async def test_interview_supports_pause_hint_and_resume() -> None:
    service = InterviewService()
    session = await service.create("user-1", CreateInterviewRequest(job_title="后端工程师"))
    paused = await service.turn("user-1", session.session_id, InterviewTurnRequest(action="interrupt"))
    assert paused.session.interrupted is True
    hinted = await service.turn("user-1", session.session_id, InterviewTurnRequest(action="hint"))
    assert "暂停" in hinted.question
    resumed = await service.turn("user-1", session.session_id, InterviewTurnRequest(action="resume"))
    assert resumed.session.interrupted is False
