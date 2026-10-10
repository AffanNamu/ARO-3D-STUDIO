"""Structured asset metadata (spec §7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AssetMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    manufacturer: str | None = None
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    drive_configuration: str | None = None
    asset_version: str = "0.1.0"
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
