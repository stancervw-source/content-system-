from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Source(BaseModel):
    id: Optional[UUID] = None

    # Identity
    source_name: str
    canonical_name: str
    canonical_key: str

    # Classification
    source_type: str
    region: Optional[str] = None
    language: Optional[str] = None          # ru | en | mixed
    primary_platform: Optional[str] = None
    platforms: list[str] = Field(default_factory=list)

    # Contact / access
    url: Optional[str] = None
    handle: Optional[str] = None

    # Signal metadata
    themes: list[str] = Field(default_factory=list)
    signal_type: Optional[str] = None
    signal_quality: Optional[int] = None
    early_signal_potential: Optional[int] = None
    startup_signal_value: Optional[int] = None
    content_adaptation_value: Optional[int] = None
    brand_fit: Optional[int] = None
    tier: int = 3
    wave: int = 1

    # Scheduling
    monitoring_frequency: Optional[str] = None
    fetch_method: str = "manual_import"
    fetch_config: dict = Field(default_factory=dict)

    # State
    is_active: bool = True
    notes: Optional[str] = None
    error_count: int = 0
    last_error_at: Optional[datetime] = None
    last_error_msg: Optional[str] = None
    last_checked_at: Optional[datetime] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SourceCreate(BaseModel):
    """Subset used when inserting a new source."""
    source_name: str
    canonical_name: str
    canonical_key: str
    source_type: str
    region: Optional[str] = None
    language: Optional[str] = None
    primary_platform: Optional[str] = None
    platforms: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    handle: Optional[str] = None
    themes: list[str] = Field(default_factory=list)
    signal_type: Optional[str] = None
    signal_quality: Optional[int] = None
    early_signal_potential: Optional[int] = None
    startup_signal_value: Optional[int] = None
    content_adaptation_value: Optional[int] = None
    brand_fit: Optional[int] = None
    tier: int = 3
    wave: int = 1
    monitoring_frequency: Optional[str] = None
    fetch_method: str = "manual_import"
    fetch_config: dict = Field(default_factory=dict)
    is_active: bool = True
    notes: Optional[str] = None
