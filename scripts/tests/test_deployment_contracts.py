"""Validate operator-facing deployment configuration without Azure writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("parameter", "binding"),
    [
        ("deployAIFoundry", "${DEPLOY_AI_FOUNDRY=true}"),
        ("azureOpenAiEndpoint", "${AZURE_OPENAI_ENDPOINT=}"),
        ("existingAiProjectEndpoint", "${EXISTING_AI_PROJECT_ENDPOINT=}"),
        ("deployChatHistory", "${DEPLOY_CHAT_HISTORY=true}"),
        ("fabricAdministrators", "${FABRIC_ADMINISTRATORS=[]}"),
        ("deployGpt5", "${DEPLOY_GPT5=false}"),
        ("deployGpt56", "${DEPLOY_GPT56=false}"),
        ("deployEmbeddingModel", "${DEPLOY_EMBEDDING_MODEL=true}"),
        ("enableFabric", "${ENABLE_FABRIC=false}"),
        ("deployFabricCapacity", "${DEPLOY_FABRIC_CAPACITY=false}"),
        ("fabricCapacityResourceId", "${FABRIC_CAPACITY_RESOURCE_ID=}"),
        ("fabricWorkspaceId", "${FABRIC_WORKSPACE_ID=}"),
        ("fabricLakehouseId", "${FABRIC_LAKEHOUSE_ID=}"),
        ("enableMpcPro", "${ENABLE_MPC_PRO=false}"),
        ("mpcProStacUrl", "${MPC_PRO_STAC_URL=}"),
        ("mpcProAssetHosts", "${MPC_PRO_ASSET_HOSTS=}"),
        ("enablePrivateEndpoints", "${ENABLE_PRIVATE_ENDPOINTS=false}"),
        ("deployWeatherStub", "${DEPLOY_WEATHER_STUB=false}"),
        ("weatherStubImageName", "${WEATHER_STUB_IMAGE_NAME=mcr.microsoft.com/k8se/quickstart:latest}"),
        ("auroraEndpointUrl", "${AURORA_ENDPOINT_URL=}"),
        ("earth2FcnEndpointUrl", "${EARTH2_FCN_ENDPOINT_URL=}"),
        ("maiWeatherEndpointUrl", "${MAI_WEATHER_ENDPOINT_URL=}"),
        ("maiWeatherScorePath", "${MAI_WEATHER_SCORE_PATH=/mai-weather/score}"),
        ("forecastAgentEnabled", "${FORECAST_AGENT_ENABLED=true}"),
        ("acrAgentPoolCount", "${ACR_AGENT_POOL_COUNT=0}"),
    ],
)
def test_given_operator_setting_when_loading_azd_parameters_then_binding_is_effective(
    parameter: str, binding: str,
) -> None:
    parameters = json.loads(
        (ROOT / "planetary-explorer/infra/main.parameters.json").read_text(encoding="utf-8")
    )["parameters"]

    assert parameters[parameter]["value"] == binding


def test_given_default_parameters_when_provisioning_then_gpu_is_opt_in() -> None:
    parameters = json.loads(
        (ROOT / "planetary-explorer/infra/main.parameters.json").read_text(encoding="utf-8")
    )["parameters"]

    assert parameters["deployGeoFm"]["value"] == "${DEPLOY_GEOFM=false}"


@pytest.mark.parametrize("manifest", ["azure.yaml", "planetary-explorer/azure.yaml"])
def test_given_cpu_weather_when_using_azd_then_image_and_runtime_are_deployed(manifest: str) -> None:
    configuration = yaml.safe_load((ROOT / manifest).read_text(encoding="utf-8"))
    service = configuration["services"]["weather-stub"]

    assert service["host"] == "containerapp"
    assert (ROOT / manifest).parent.joinpath(service["project"], "Dockerfile").is_file()
    assert service["resourceName"] == "${AZURE_WEATHER_STUB_CONTAINER_APP_NAME}"
    assert "--profile weather" in service["hooks"]["postdeploy"]["windows"]["run"]
    assert "--profile weather" in service["hooks"]["postdeploy"]["posix"]["run"]


def test_given_fresh_api_when_provisioning_then_weather_secrets_are_deferred() -> None:
    source = (ROOT / "planetary-explorer/infra/main.bicep").read_text(encoding="utf-8")

    for parameter in (
        "auroraEndpointUrlConfigured", "earth2FcnEndpointUrlConfigured",
        "maiWeatherEndpointUrlConfigured",
    ):
        assert f"{parameter}: false" in source


def test_given_direct_arm_script_when_validating_then_azd_substitutions_are_not_submitted() -> None:
    source = (ROOT / "deploy-infrastructure.ps1").read_text(encoding="utf-8")

    assert '--parameters "planetary-explorer/infra/main.parameters.json"' not in source