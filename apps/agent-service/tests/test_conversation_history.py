from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.api.schemas import ChatRequest
from app.application.chat_service import ChatApplicationService
from app.infrastructure.response_cache import ResponseCache


class ConversationHistoryTests(unittest.TestCase):
    def test_chat_request_accepts_bounded_history(self) -> None:
        payload = ChatRequest.model_validate(
            {
                "sessionId": "session-1",
                "message": "继续",
                "history": [{"role": "user", "content": "上一句"}],
            }
        )
        self.assertEqual(payload.history[0].role, "user")

        with self.assertRaises(ValidationError):
            ChatRequest.model_validate(
                {
                    "sessionId": "session-1",
                    "message": "继续",
                    "history": [{"role": "user", "content": str(index)} for index in range(13)],
                }
            )

    def test_history_is_readable_and_changes_cache_identity(self) -> None:
        cache = ResponseCache(redis_url="redis://127.0.0.1:6399/0")
        service = ChatApplicationService(graph=None, sessions=None, response_cache=cache)  # type: ignore[arg-type]
        first = [{"role": "user", "content": "我更喜欢简洁回答"}]
        second = [{"role": "user", "content": "我需要详细解释"}]

        context = service._request_context({"tone": "professional"}, first)
        self.assertIn("用户沟通偏好", context)
        self.assertIn("最近对话", context)
        self.assertNotEqual(
            service._cache_key("tenant-a", "user-a", "继续", {}, first),
            service._cache_key("tenant-a", "user-a", "继续", {}, second),
        )


if __name__ == "__main__":
    unittest.main()
