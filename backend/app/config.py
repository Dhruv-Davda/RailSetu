"""
Environment-driven configuration for the RailSetu backend.

All settings are overridable via environment variables prefixed `RAILSETU_`
(or a local `.env` file). Nothing operational is hard-coded in source: data
sources, API keys, capacities and feature flags all live here so the same image
runs in dev, staging and prod with only env changes.

See `.env.example` for the full list.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAILSETU_", env_file=".env", extra="ignore"
    )

    # ---- App ----
    app_name: str = "RailSetu API"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    # NoDecode: keep pydantic-settings from JSON-decoding this from env/.env so the
    # validator below can accept a plain "*" or comma-separated list.
    cors_origins: Annotated[list[str], NoDecode] = ["*"]

    # ---- Station / geometry ----
    station_code: str = "NDLS"
    allow_graph_refresh: bool = False  # guard the /api/station/refresh endpoint

    # ---- Demand provider ----
    # "fixture" -> committed scenarios (replay/test). "live" -> third-party rail API.
    demand_provider: str = "fixture"
    live_fallback_to_fixture: bool = True  # if the live API fails, replay a fixture

    # ---- Third-party (RapidAPI) live rail API ----
    # Defaults target a common RapidAPI "Indian Railways" live-station endpoint.
    # These are NTES scrapers; field names vary by provider, so parsing is
    # centralised + defensive in app/clients/rail_api.py.
    rail_api_base_url: str = "https://irctc1.p.rapidapi.com"
    rail_api_key: str = ""          # RapidAPI key — set in env, never commit
    rail_api_host: str = "irctc1.p.rapidapi.com"
    rail_api_timeout_s: float = 20.0
    rail_api_retries: int = 2
    rail_api_cache_ttl_s: int = 120  # don't hammer a metered API (free tier 429s fast)
    rail_api_window_hours: int = 3

    # Two endpoints, two trade-offs:
    #   "timetable" (getTrainsByStation): full scheduled board, time-filtered to the
    #               next N hours -> populated + reliable, but NOT delay-adjusted.
    #   "liveboard" (getLiveStation): delay-adjusted live board, but often empty /
    #               rate-limited on the free tier.
    # Neither returns platform numbers or passenger counts (both are estimated).
    rail_api_source: str = "timetable"
    rail_api_live_path: str = "/api/v3/getLiveStation"
    rail_api_timetable_path: str = "/api/v3/getTrainsByStation"
    live_max_trains: int = 30       # cap in-window trains so estimated load stays sane

    # ---- Live demand estimation ----
    # Third-party live-station APIs return arrivals, NOT passenger counts, so load
    # is estimated. Tune these against PRS/UTS or CCTV once available.
    default_alighting_per_train: int = 1200
    special_train_multiplier: float = 2.2  # "special"/festival trains run packed
    unload_duration_s: int = 180
    live_horizon_s: int = 420

    # ---- Crowd sensing / calibration ----
    crowd_sensor: str = "none"      # "none" | "stub"
    crowd_sensor_fixture: str = ""  # optional JSON of measured observations
    calibration_enabled: bool = False
    calibration_min_scale: float = 0.3
    calibration_max_scale: float = 2.5

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v):
        # Accept a comma-separated string as well as a JSON list, for ergonomics.
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return v  # let pydantic JSON-decode it
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
