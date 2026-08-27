"""Tests for owner-scoped internal session keys."""

from pipeline.session_store import scope_session_id


def test_given_same_client_session_when_owners_differ_then_keys_are_isolated() -> None:
    # Act
    first_key = scope_session_id("tenant:user-1", "conversation-1")
    second_key = scope_session_id("tenant:user-2", "conversation-1")

    # Assert
    assert first_key != second_key


def test_given_same_owner_and_client_session_when_scoped_then_key_is_stable() -> None:
    # Act
    first_key = scope_session_id("tenant:user-1", "conversation-1")
    second_key = scope_session_id("tenant:user-1", "conversation-1")

    # Assert
    assert first_key == second_key