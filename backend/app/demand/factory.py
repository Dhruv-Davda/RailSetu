"""Select the demand provider from configuration."""
from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings

from .base import DemandProvider
from .fixtures import FixtureDemandProvider
from .live import LiveDemandProvider


def build_demand_provider(settings: Settings) -> DemandProvider:
    if settings.demand_provider == "live":
        return LiveDemandProvider(settings)
    return FixtureDemandProvider()


@lru_cache
def get_demand_provider() -> DemandProvider:
    return build_demand_provider(get_settings())
