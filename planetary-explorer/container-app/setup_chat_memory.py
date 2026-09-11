"""Preview or create the dedicated Azure AI Search chat-memory index."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from typing import Any

from chat_memory_search import create_memory_index_schema


def ensure_memory_index(client: Any, schema: Any) -> str:
    """Create a missing index or validate an existing one without replacing it."""
    from azure.core.exceptions import ResourceNotFoundError

    try:
        existing = client.get_index(schema.name)
    except ResourceNotFoundError:
        client.create_index(schema)
        return "created"
    fields = {field.name: field for field in existing.fields}
    for required in schema.fields:
        actual = fields.get(required.name)
        if (
            actual is None
            or actual.type != required.type
            or (required.key and not actual.key)
            or (required.filterable and not actual.filterable)
            or (required.searchable and not actual.searchable)
        ):
            raise ValueError(f"Existing index has an incompatible {required.name} field; choose a new index name.")
    return "validated"


def create_parser() -> argparse.ArgumentParser:
    """Describe the preview-first index setup command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-name", default=os.getenv("CHAT_MEMORY_SEARCH_INDEX") or "chat-memory-v1")
    parser.add_argument("--apply", action="store_true", help="Create or validate the index in AZURE_SEARCH_ENDPOINT.")
    return parser


def configure_memory_index_from_env() -> str:
    """Create or validate the dedicated index with the deployment's managed identity."""
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient

    endpoint = (os.getenv("CHAT_MEMORY_SEARCH_ENDPOINT") or os.getenv("AZURE_SEARCH_ENDPOINT") or "").strip()
    index_name = os.getenv("CHAT_MEMORY_SEARCH_INDEX", "").strip()
    if not endpoint or not index_name:
        raise ValueError("Memory Search endpoint and index are required for automatic setup.")
    if index_name == os.getenv("AZURE_SEARCH_INDEX"):
        raise ValueError("Memory must use a dedicated Search index.")
    with DefaultAzureCredential() as credential:
        with SearchIndexClient(endpoint, credential) as client:
            return ensure_memory_index(client, create_memory_index_schema(index_name))


def main() -> int:
    """Preview the schema by default; cloud writes require --apply."""
    parser = create_parser()
    arguments = parser.parse_args()
    schema = create_memory_index_schema(arguments.index_name)
    if not arguments.apply:
        print(json.dumps(schema.serialize(), indent=2))
        return 0
    endpoint = (os.getenv("CHAT_MEMORY_SEARCH_ENDPOINT") or os.getenv("AZURE_SEARCH_ENDPOINT") or "").strip()
    if not endpoint:
        parser.error("AZURE_SEARCH_ENDPOINT is required with --apply.")
    if arguments.index_name == os.getenv("AZURE_SEARCH_INDEX"):
        parser.error("Use a dedicated memory index, not AZURE_SEARCH_INDEX.")

    from azure.core.credentials import AzureKeyCredential
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient

    with ExitStack() as resources:
        key = os.getenv("AZURE_SEARCH_KEY", "").strip()
        credential = AzureKeyCredential(key) if key else resources.enter_context(DefaultAzureCredential())
        client = resources.enter_context(SearchIndexClient(endpoint, credential))
        outcome = ensure_memory_index(client, schema)
    print(f"Chat memory index {arguments.index_name}: {outcome}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())