from __future__ import annotations

import pytest

from app.messaging.reliable_bus import ReliableMessageBus


@pytest.mark.asyncio
async def test_publish_falls_back_to_durable_local_outbox(tmp_path) -> None:
    bus = ReliableMessageBus(outbox_path=str(tmp_path / 'outbox.jsonl'))
    message_id = await bus.publish(topic='presentation', payload={'text': '你好'})
    assert message_id
    content = (tmp_path / 'outbox.jsonl').read_text(encoding='utf-8')
    assert message_id in content
    assert '你好' in content


def test_dead_letter_names_are_stable() -> None:
    bus = ReliableMessageBus(exchange='ican.agent', queue='digital-human.presentation.v2')
    assert bus.dead_letter_exchange == 'ican.agent.dlx'
    assert bus.dead_letter_queue == 'digital-human.presentation.v2.dead'
