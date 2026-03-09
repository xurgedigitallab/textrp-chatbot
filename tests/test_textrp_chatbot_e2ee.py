"""Regression tests for TextRPChatbot encrypted-event recovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import os
import sys

import pytest
from nio import EncryptionError
from nio.events.room_events import MegolmEvent

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textrp_chatbot import TextRPChatbot


@pytest.mark.asyncio
async def test_request_missing_room_key_respects_cooldown(tmp_path):
    bot = TextRPChatbot(
        homeserver="https://example.org",
        username="@bot:example.org",
        access_token="token",
        store_path=str(tmp_path / "store"),
    )

    event = SimpleNamespace(
        room_id="!room:example.org",
        session_id="sess-1",
        sender="@alice:example.org",
    )

    bot.client.keys_query = AsyncMock()
    bot.client.request_room_key = AsyncMock(return_value=SimpleNamespace())
    bot._auto_trust_room_devices = AsyncMock()

    with patch.object(
        type(bot.client), "should_query_keys", new_callable=PropertyMock, return_value=False
    ):
        await bot._request_missing_room_key(event)
        await bot._request_missing_room_key(event)

    assert bot.client.request_room_key.await_count == 1


@pytest.mark.asyncio
async def test_request_missing_room_key_queries_keys_when_needed(tmp_path):
    bot = TextRPChatbot(
        homeserver="https://example.org",
        username="@bot:example.org",
        access_token="token",
        store_path=str(tmp_path / "store"),
    )

    event = SimpleNamespace(
        room_id="!room:example.org",
        session_id="sess-2",
        sender="@alice:example.org",
    )

    bot.client.keys_query = AsyncMock()
    bot.client.request_room_key = AsyncMock(return_value=SimpleNamespace())
    bot._auto_trust_room_devices = AsyncMock()

    with patch.object(
        type(bot.client), "should_query_keys", new_callable=PropertyMock, return_value=True
    ):
        await bot._request_missing_room_key(event)

    bot.client.keys_query.assert_awaited_once()
    bot.client.request_room_key.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_handle_encrypted_event_requests_room_key_on_decrypt_error(tmp_path):
    bot = TextRPChatbot(
        homeserver="https://example.org",
        username="@bot:example.org",
        access_token="token",
        store_path=str(tmp_path / "store"),
    )

    room = SimpleNamespace(room_id="!room:example.org", encrypted=True)
    event = MegolmEvent.from_dict(
        {
            "sender": "@alice:example.org",
            "event_id": "$event",
            "origin_server_ts": 1,
            "type": "m.room.encrypted",
            "content": {
                "algorithm": "m.megolm.v1.aes-sha2",
                "sender_key": "sender-key",
                "session_id": "sess-3",
                "device_id": "ALICEDEVICE",
                "ciphertext": "cipher",
            },
        }
    )
    event.room_id = "!room:example.org"

    bot.client.decrypt_event = MagicMock(side_effect=EncryptionError("missing session"))
    bot._request_missing_room_key = AsyncMock()

    await bot._handle_encrypted_event(room, event)

    bot._request_missing_room_key.assert_awaited_once_with(event)
