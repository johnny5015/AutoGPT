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
        """从用户提交的字典数据中解析语音服务提供商配置。"""

        # base_url 是调用外部接口的关键字段，如果缺失就直接报错
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
    gender: Optional[str] = None
    extra: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "RoleConfig":
        """解析单个角色的语音配置项。"""

        # voice_id 对应第三方语音模型或音色 ID，是必填项
        voice_id = str(payload.get("voice_id", "")).strip()
        if not voice_id:
            raise ValueError("Each role must define a non-empty 'voice_id'.")
        audio_format = str(payload.get("audio_format", "mp3"))
        speaking_rate = float(payload.get("speaking_rate", 1.0))
        pitch = float(payload.get("pitch", 0.0))
        gender_value = payload.get("gender")
        gender = str(gender_value).strip() if gender_value else None
        extra = {
            key: value
            for key, value in payload.items()
            if key
            not in {"voice_id", "audio_format", "speaking_rate", "pitch", "gender"}
        }
        return cls(
            voice_id=voice_id,
            audio_format=audio_format,
            speaking_rate=speaking_rate,
            pitch=pitch,
            gender=gender,
            extra=extra,
        )


@dataclass(slots=True)
class GenerationConfig:
    """Aggregate configuration used during a voice generation job."""

    roles: Dict[str, RoleConfig]
    provider: Optional[ProviderConfig] = None
    gender_roles: Dict[str, RoleConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GenerationConfig":
        """将前端提交的完整配置转换为内部数据结构。"""

        # roles 是按角色名称划分的配置主体，必须存在
        raw_roles = payload.get("roles")
        if not isinstance(raw_roles, Mapping):
            raise ValueError("Configuration must contain a 'roles' mapping of speaker names to settings.")

        roles = {name: RoleConfig.from_mapping(config) for name, config in raw_roles.items()}

        gender_roles: Dict[str, RoleConfig] = {}
        raw_gender_roles = payload.get("gender_roles")
        if isinstance(raw_gender_roles, Mapping):
            for gender_key, config in raw_gender_roles.items():
                if not isinstance(config, Mapping):
                    continue
                normalized_gender = str(gender_key).strip().lower()
                if not normalized_gender:
                    continue
                gender_roles[normalized_gender] = RoleConfig.from_mapping(config)
                gender_roles[normalized_gender].gender = normalized_gender

        provider_config: Optional[ProviderConfig] = None
        raw_provider = payload.get("provider")
        if isinstance(raw_provider, Mapping):
            base_url = str(raw_provider.get("base_url", "")).strip()
            if base_url:
                provider_config = ProviderConfig.from_mapping(raw_provider)

        return cls(roles=roles, provider=provider_config, gender_roles=gender_roles)

    def resolve_role(self, speaker: str, gender: Optional[str]) -> RoleConfig:
        """Return the best matching role configuration for the supplied speaker."""

        # 优先匹配角色名称；若无精确匹配，再尝试根据性别 fallback
        if speaker in self.roles:
            return self.roles[speaker]

        normalized_gender = (gender or "").strip().lower()
        if normalized_gender:
            for role in self.roles.values():
                if role.gender and role.gender.strip().lower() == normalized_gender:
                    return role
            if normalized_gender in self.gender_roles:
                return self.gender_roles[normalized_gender]

        raise ValueError(
            f"No voice configuration found for speaker '{speaker}'. "
            "Please add a mapping in the role configuration or provide a matching gender role."
        )
