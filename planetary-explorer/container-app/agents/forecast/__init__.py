"""Forecast Agent — multi-model atmospheric forecasting under the GEOINT
module surface.

Topology
--------
::

    ForecastQuery
        │
        ▼
    PlannerExecutor          (validate + decide which providers to call)
        │  fan-out
        ├──► ProviderExecutor("aurora-1.x")          # Microsoft Aurora
        ├──► ProviderExecutor("earth2-fcn")          # NVIDIA Earth-2 FCN
        └──► ProviderExecutor("mai-weather-1.x")     # Microsoft MAI Weather (Foundry)
        │  fan-in
        ▼
    AggregatorExecutor       (compose dossier, compute ensemble spread,
                              gracefully degrade if a provider failed)

The module requires ``FORECAST_AGENT_ENABLED=1`` and an available Microsoft
Agent Framework runtime. It does not provide a non-MAF execution path.
"""

from .workflow import (
    forecast,
    is_available,
)
from .messages import (
    ForecastAgentQuery,
    ForecastDossier,
)

__all__ = [
    "forecast",
    "is_available",
    "ForecastAgentQuery",
    "ForecastDossier",
]
