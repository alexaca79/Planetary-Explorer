"""Building Damage endpoint requires rendered MPC Pro source evidence."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _JsonRequest:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


def _request_payload(**overrides) -> dict:
    return {
        "latitude": 52.8737,
        "longitude": -118.0814,
        "user_query": "Assess potential building damage.",
        "screenshot": "image-bytes",
        "stac_mode": "pro",
        "stac_items": [
            {
                "id": "tenant-scene",
                "collection": "tenant-aerial",
                "stac_mode": "pro",
            }
        ],
        **overrides,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"stac_mode": "public"},
        {"stac_items": []},
        {"stac_items": [{"id": "public-scene", "stac_mode": "public"}]},
        {"screenshot": None},
    ],
)
@pytest.mark.asyncio
async def test_given_unproven_source_when_assessing_damage_then_request_is_rejected(
    overrides,
) -> None:
    # Arrange
    import fastapi_app

    # Act and Assert
    with pytest.raises(fastapi_app.HTTPException) as error:
        await fastapi_app.geoint_building_damage_analysis(
            _JsonRequest(_request_payload(**overrides))
        )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_given_forged_pro_labels_when_scene_is_absent_then_request_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app
    import pro_stac_client

    monkeypatch.setenv("PE_FEATURE_MPC_PRO", "true")
    monkeypatch.setenv(
        "MPC_PRO_STAC_URL",
        "https://tenant.geocatalog.spatio.azure.com/stac",
    )
    monkeypatch.setattr(pro_stac_client, "pro_get_item_sync", lambda *_args: None)

    # Act and Assert
    with pytest.raises(fastapi_app.HTTPException) as error:
        await fastapi_app.geoint_building_damage_analysis(
            _JsonRequest(_request_payload())
        )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_given_pro_screenshot_when_assessing_damage_then_vision_runs(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app
    import pipeline._aoai as aoai_module
    import pro_stac_client

    class Completions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="No visible structural damage.")
                    )
                ]
            )

    monkeypatch.setattr(
        aoai_module,
        "get_aoai_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
    )
    monkeypatch.setenv("PE_FEATURE_MPC_PRO", "true")
    monkeypatch.setenv(
        "MPC_PRO_STAC_URL",
        "https://tenant.geocatalog.spatio.azure.com/stac",
    )
    monkeypatch.setattr(
        pro_stac_client,
        "pro_get_item_sync",
        lambda _collection_id, item_id: {"id": item_id},
    )

    # Act
    result = await fastapi_app.geoint_building_damage_analysis(
        _JsonRequest(_request_payload())
    )

    # Assert
    assert result["status"] == "success"
    assert result["result"]["agent"] == "building_damage_vision"
