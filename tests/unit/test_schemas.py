"""
Unit tests for Core Data Schemas (ServerStatus, ServerState, LogEvent).
Tests enum consistency, model validation, serialization, defaults, and boundary types.
"""

import json
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from tests.conftest import ServerStatus, ServerState, LogEvent


def test_server_status_enum_values():
    """Verify all required server statuses exist and match lowercase string representations."""
    expected = {
        "offline": ServerStatus.OFFLINE,
        "in_queue": ServerStatus.IN_QUEUE,
        "loading": ServerStatus.LOADING,
        "online": ServerStatus.ONLINE,
        "stopping": ServerStatus.STOPPING,
        "crashed": ServerStatus.CRASHED,
        "unknown": ServerStatus.UNKNOWN,
    }
    for val, enum_obj in expected.items():
        assert enum_obj.value == val
        assert ServerStatus(val) == enum_obj


def test_server_state_defaults():
    """Verify ServerState model initializes with correct default values."""
    state = ServerState()
    assert state.status == ServerStatus.OFFLINE
    assert state.countdown_seconds is None
    assert state.countdown_text is None
    assert state.last_plus_one_click is None
    assert state.plus_one_click_count == 0
    assert state.queue_position is None
    assert state.queue_time is None
    assert state.is_keepalive_active is True
    assert state.session_valid is True
    assert isinstance(state.last_updated, datetime)


def test_server_state_full_fields():
    """Verify ServerState properly populates all fields when fully specified."""
    now = datetime.now(timezone.utc)
    state = ServerState(
        status=ServerStatus.ONLINE,
        countdown_seconds=185,
        countdown_text="03:05",
        last_plus_one_click=now,
        plus_one_click_count=5,
        queue_position=None,
        queue_time=None,
        is_keepalive_active=True,
        session_valid=True,
        last_updated=now,
    )
    assert state.status == ServerStatus.ONLINE
    assert state.countdown_seconds == 185
    assert state.countdown_text == "03:05"
    assert state.plus_one_click_count == 5
    assert state.last_plus_one_click == now


def test_server_state_serialization_roundtrip():
    """Verify ServerState serializes to JSON and deserializes without data loss."""
    now = datetime.now(timezone.utc)
    state = ServerState(
        status=ServerStatus.IN_QUEUE,
        queue_position=3,
        queue_time="45s",
        plus_one_click_count=2,
        is_keepalive_active=False,
        session_valid=True,
        last_updated=now,
    )
    json_data = state.model_dump_json() if hasattr(state, "model_dump_json") else state.json()
    parsed_dict = json.loads(json_data)

    assert parsed_dict["status"] == "in_queue"
    assert parsed_dict["queue_position"] == 3
    assert parsed_dict["queue_time"] == "45s"
    assert parsed_dict["is_keepalive_active"] is False

    # Roundtrip rebuild
    rebuilt = ServerState.model_validate(parsed_dict) if hasattr(ServerState, "model_validate") else ServerState.parse_obj(parsed_dict)
    assert rebuilt.status == ServerStatus.IN_QUEUE
    assert rebuilt.queue_position == 3


def test_log_event_creation_and_levels():
    """Verify LogEvent creation across standard log levels."""
    levels = ["INFO", "SUCCESS", "WARN", "ERROR", "PLUS_ONE"]
    for lvl in levels:
        event = LogEvent(level=lvl, message=f"Test message for {lvl}", data={"key": "val"})
        assert event.level == lvl
        assert event.message == f"Test message for {lvl}"
        assert event.data == {"key": "val"}
        assert isinstance(event.timestamp, datetime)


def test_server_state_invalid_status_raises():
    """Verify passing an unrecognized status string raises a ValidationError."""
    with pytest.raises(ValidationError):
        if hasattr(ServerState, "model_validate"):
            ServerState.model_validate({"status": "non_existent_status_1234"})
        else:
            ServerState.parse_obj({"status": "non_existent_status_1234"})
