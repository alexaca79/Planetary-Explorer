"""Non-destructive memory-index setup contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from chat_memory_search import create_memory_index_schema
from setup_chat_memory import create_parser, ensure_memory_index


def test_given_default_arguments_when_parsed_then_cloud_writes_are_disabled():
    assert create_parser().parse_args([]).apply is False


def test_given_missing_index_when_applied_then_only_the_dedicated_index_is_created():
    created = []

    def missing_index(name):
        raise ResourceNotFoundError("Missing")

    client = SimpleNamespace(get_index=missing_index, create_index=created.append)
    schema = create_memory_index_schema("chat-memory-test")

    assert ensure_memory_index(client, schema) == "created"
    assert created == [schema]


def test_given_compatible_index_when_applied_then_no_existing_schema_is_changed():
    schema = create_memory_index_schema("chat-memory-test")
    client = SimpleNamespace(get_index=lambda name: schema)

    assert ensure_memory_index(client, schema) == "validated"


def test_given_incompatible_index_when_applied_then_replacement_is_refused():
    schema = create_memory_index_schema("chat-memory-test")
    client = SimpleNamespace(get_index=lambda name: SimpleNamespace(fields=[]))

    with pytest.raises(ValueError, match="choose a new index name"):
        ensure_memory_index(client, schema)