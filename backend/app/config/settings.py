import json
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["native", "mock"] = "native"
    interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    stale_after_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    history_size: int = Field(default=60, ge=1, le=600)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    allowed_origins: list[str] = ["http://localhost:8088", "http://127.0.0.1:8088"]
    ros2_enabled: bool = False
    ros2_interval_seconds: float = Field(default=10.0, ge=5.0, le=300.0)
    ros2_probe_timeout_seconds: float = Field(default=8.0, ge=2.0, le=30.0)
    bpu_temperature_timeout_seconds: float = Field(default=1.0, ge=0.1, le=3.0)
    bpu_temperature_interval_seconds: float = Field(default=30.0, ge=10.0, le=300.0)
    bpu_temperature_max_backoff_seconds: float = Field(default=300.0, ge=30.0, le=1800.0)
    bpu_cpu_proxy_enabled: bool = True
    storage_paths: list[str] = ["/"]

    @field_validator("allowed_hosts")
    @classmethod
    def hosts(cls, values):
        if not values or len(values) > 16:
            raise ValueError("one to sixteen explicit hosts required")
        for value in values:
            if len(value) > 253 or not re.fullmatch(
                r"[a-zA-Z0-9]+(?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", value
            ):
                raise ValueError("explicit hostnames or IPv4 addresses only")
        return values

    @field_validator("allowed_origins")
    @classmethod
    def origins(cls, values):
        if not values or len(values) > 16:
            raise ValueError("explicit origins required")
        for value in values:
            u = urlsplit(value)
            if (
                u.scheme not in ("http", "https")
                or not u.hostname
                or u.username
                or u.password
                or u.path
                or u.query
                or u.fragment
            ):
                raise ValueError("origins must be explicit HTTP(S) origins without paths")
            cls.hosts([u.hostname])
            if u.port is not None and not 1 <= u.port <= 65535:
                raise ValueError("invalid port")
        return values

    @field_validator("storage_paths")
    @classmethod
    def paths(cls, values):
        if not values or len(values) > 16:
            raise ValueError("one to sixteen paths required")
        if any(
            not p.startswith("/")
            or ".." in Path(p).parts
            or not re.fullmatch(r"/[a-zA-Z0-9_./-]*", p)
            for p in values
        ):
            raise ValueError("only absolute local storage paths allowed")
        return values

    @model_validator(mode="after")
    def freshness(self):
        if self.stale_after_seconds < self.interval_seconds * 2:
            raise ValueError("stale threshold must be at least twice the interval")
        if self.bpu_temperature_max_backoff_seconds < self.bpu_temperature_interval_seconds:
            raise ValueError("temperature max backoff must cover the normal interval")
        return self


def load_settings(path: str | None = None) -> Settings:
    # JSON is a strict subset of YAML 1.2; no executable YAML tags or extra parser.
    file = Path(path or os.environ.get("RDK_CONFIG", ROOT / "config/default.yaml"))
    return Settings.model_validate(json.loads(file.read_text()))
