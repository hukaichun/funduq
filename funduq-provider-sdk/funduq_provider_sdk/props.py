from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KyokForwardedProps(BaseModel):
    """funduq's `forwardedProps.kyok` entry: the grant a KYOK-bound run's agent presents when calling for completions."""

    model_config = ConfigDict(frozen=True)

    token: str
