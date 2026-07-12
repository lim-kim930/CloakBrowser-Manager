"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Kernel version pin: 4 or 5 dot-separated numeric components, matching what
# the cloakbrowser package accepts as browser_version (and kernel dir names).
_KERNEL_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3,4}$")


def _validate_kernel_version(v: object) -> str | None:
    """Shared kernel_version normalizer: empty → None, else enforce the pin format."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("kernel_version must be a string")
    v = v.strip()
    if not v:
        return None
    if not _KERNEL_VERSION_RE.fullmatch(v):
        raise ValueError(
            "kernel_version must be a full numeric version, e.g. 146.0.7680.177.5"
        )
    return v


class ProfileCreate(BaseModel):
    name: str
    fingerprint_seed: int | None = None  # random if not set
    proxy: str | None = None  # "http://user:pass@host:port" or null
    timezone: str | None = None  # "America/New_York"
    locale: str | None = None  # "en-US"
    platform: Literal["windows", "macos", "linux"] = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    humanize: bool = False
    human_preset: Literal["default", "careful"] = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    auto_launch: bool = False
    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    launch_args: list[str] = Field(default_factory=list)
    notes: str | None = None
    kernel_version: str | None = None  # None = use the default kernel
    tags: list[TagCreate] | None = None

    _kernel_version = field_validator("kernel_version", mode="before")(
        _validate_kernel_version
    )


class ProfileUpdate(BaseModel):
    name: str | None = None
    fingerprint_seed: int | None = None
    proxy: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    locale: str | None = Field(default=None)
    platform: Literal["windows", "macos", "linux"] | None = None
    user_agent: str | None = Field(default=None)
    screen_width: int | None = None
    screen_height: int | None = None
    gpu_vendor: str | None = Field(default=None)
    gpu_renderer: str | None = Field(default=None)
    hardware_concurrency: int | None = Field(default=None)
    humanize: bool | None = None
    human_preset: Literal["default", "careful"] | None = None
    headless: bool | None = None
    geoip: bool | None = None
    clipboard_sync: bool | None = None
    auto_launch: bool | None = None
    color_scheme: Literal["light", "dark", "no-preference"] | None = Field(default=None)
    launch_args: list[str] | None = None
    notes: str | None = Field(default=None)
    kernel_version: str | None = Field(default=None)
    tags: list[TagCreate] | None = None

    _kernel_version = field_validator("kernel_version", mode="before")(
        _validate_kernel_version
    )


class TagCreate(BaseModel):
    tag: str
    color: str | None = None  # hex color


class TagResponse(BaseModel):
    tag: str
    color: str | None = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    fingerprint_seed: int
    proxy: str | None = None
    timezone: str | None = None
    locale: str | None = None
    platform: str = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    humanize: bool = False
    human_preset: str = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    auto_launch: bool = False

    @field_validator("clipboard_sync", mode="before")
    @classmethod
    def coerce_clipboard_sync(cls, v: object) -> bool:
        return v if v is not None else True

    color_scheme: str | None = None
    launch_args: list[str] = []
    notes: str | None = None
    kernel_version: str | None = None
    user_data_dir: str
    created_at: str
    updated_at: str
    tags: list[TagResponse] = []
    status: str = "stopped"  # "running" | "stopped"
    vnc_ws_port: int | None = None
    cdp_url: str | None = None


class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None


class StatusResponse(BaseModel):
    running_count: int
    binary_version: str
    profiles_total: int
    display_mode: str = "vnc"


class ProfileStatusResponse(BaseModel):
    status: str  # "running" | "stopped"
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None


class ClipboardRequest(BaseModel):
    text: str = Field(max_length=1_048_576)  # 1MB max


class LoginRequest(BaseModel):
    token: str


class BinaryLocationUpdate(BaseModel):
    """New kernel storage directory; None/empty resets to the package default."""

    kernel_dir: str | None = Field(default=None, max_length=4096)


class KernelInfo(BaseModel):
    """One installed kernel found in the storage directory."""

    version: str
    path: str
    size: int | None = None
    pro: bool = False
    in_use: bool = False  # a running profile launched with this version


class KernelListResponse(BaseModel):
    kernels: list[KernelInfo]
    default_version: str | None = None
    kernel_dir: str


class KernelImportRequest(BaseModel):
    """Import a user-downloaded kernel (.zip archive or extracted folder)."""

    source_path: str = Field(min_length=1, max_length=4096)
    version: str | None = Field(default=None, max_length=64)

    _version = field_validator("version", mode="before")(_validate_kernel_version)


class KernelDefaultUpdate(BaseModel):
    """Set the default kernel version; None/empty clears it (newest wins)."""

    version: str | None = Field(default=None, max_length=64)

    _version = field_validator("version", mode="before")(_validate_kernel_version)
