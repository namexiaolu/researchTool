from __future__ import annotations

from dataclasses import replace

from research_tool.shared.config_import import ImportedProfiles
from research_tool.shared.errors import ConfigurationError
from research_tool.shared.settings import AppSettings


def merge_imported_profiles(
    settings: AppSettings,
    imported: ImportedProfiles,
    *,
    activate: bool = True,
    overwrite: bool = False,
) -> AppSettings:
    profiles = dict(settings.profiles)
    for name, profile in imported.profiles.items():
        if name in profiles and not overwrite:
            raise ConfigurationError(f"Provider 档案已存在：{name}")
        profiles[name] = profile
    active = imported.preferred_active if activate else settings.active_provider
    return replace(settings, profiles=profiles, active_provider=active)
