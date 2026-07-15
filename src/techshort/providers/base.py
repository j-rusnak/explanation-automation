from __future__ import annotations

from typing import Protocol

from techshort.domain.models import (
    AnglesManifest,
    ClaimsManifest,
    ScriptManifest,
    StoryboardManifest,
)


class GenerationProvider(Protocol):
    def generate_claims(
        self, source_text: str, source_id: str, source_hash: str
    ) -> ClaimsManifest: ...
    def generate_angles(self, claims: ClaimsManifest) -> AnglesManifest: ...
    def generate_script(self, claims: ClaimsManifest, angle: str) -> ScriptManifest: ...
    def generate_storyboard(self, script: ScriptManifest) -> StoryboardManifest: ...
    def critique(self, claims: ClaimsManifest) -> list[str]: ...
