"""Configuration models for the SRT voice generation service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional


@dataclass(slots=True)
class ProviderConfig:
    """Configuration for the third-party text-to-speech provider."""

    base_url: str
    api_key: Optional[str] = None
    timeout_seconds: float = 30.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ProviderConfig":
        base_url = str(payload.get("base_url", "")).strip()
        if not base_url:
            raise ValueError("Provider configuration requires a 'base_url'.")
        api_key = payload.get("api_key")
        timeout = float(payload.get("timeout_seconds", 30.0))
        return cls(base_url=base_url, api_key=str(api_key) if api_key else None, timeout_seconds=timeout)


@dataclass(slots=True)
class RoleConfig:
    """Voice configuration for a single speaker."""

    voice_id: str
    audio_format: str = "mp3"
    speaking_rate: float = 1.0
    pitch: float = 0.0
    extra: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "RoleConfig":
        voice_id = str(payload.get("voice_id", "")).strip()
        if not voice_id:
            raise ValueError("Each role must define a non-empty 'voice_id'.")
        audio_format = str(payload.get("audio_format", "mp3"))
        speaking_rate = float(payload.get("speaking_rate", 1.0))
        pitch = float(payload.get("pitch", 0.0))
        extra = {
            key: value
            for key, value in payload.items()
            if key not in {"voice_id", "audio_format", "speaking_rate", "pitch"}
        }
        return cls(
            voice_id=voice_id,
            audio_format=audio_format,
            speaking_rate=speaking_rate,
            pitch=pitch,
            extra=extra,
        )


@dataclass(slots=True)
class GenerationConfig:
    """Aggregate configuration used during a voice generation job."""

    roles: Dict[str, RoleConfig]
    provider: Optional[ProviderConfig] = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GenerationConfig":
        raw_roles = payload.get("roles")
        if not isinstance(raw_roles, Mapping):
            raise ValueError("Configuration must contain a 'roles' mapping of speaker names to settings.")

        roles = {name: RoleConfig.from_mapping(config) for name, config in raw_roles.items()}

        provider_config: Optional[ProviderConfig] = None
        raw_provider = payload.get("provider")
        if isinstance(raw_provider, Mapping):
            base_url = str(raw_provider.get("base_url", "")).strip()
            if base_url:
                provider_config = ProviderConfig.from_mapping(raw_provider)

        return cls(roles=roles, provider=provider_config)
