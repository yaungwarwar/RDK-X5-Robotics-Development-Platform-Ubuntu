from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: Any = None
    unit: str
    status: Literal["ok", "unavailable", "error", "warming_up"]
    reason: str | None = None
    source: str
    timestamp: str = Field(default_factory=now)
    age_seconds: float = 0.0
    stale: bool = False


def metric(
    value: Any, unit: str, source: str, reason: str | None = None, status: str | None = None
) -> dict:
    return Measurement(
        value=value,
        unit=unit,
        source=source,
        status=status or ("ok" if value is not None else "unavailable"),
        reason=reason,
    ).model_dump()


def freshen(value: Any, threshold: float, current: datetime | None = None) -> Any:
    current = current or datetime.now(timezone.utc)
    if isinstance(value, dict):
        result = {k: freshen(v, threshold, current) for k, v in value.items()}
        if "timestamp" in value and "status" in value and "unit" in value:
            age = max(0.0, (current - datetime.fromisoformat(value["timestamp"])).total_seconds())
            result.update(
                age_seconds=round(age, 3), stale=value.get("stale", False) or age > threshold
            )
        return result
    if isinstance(value, list):
        return [freshen(v, threshold, current) for v in value]
    return value
