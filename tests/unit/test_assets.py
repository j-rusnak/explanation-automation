from __future__ import annotations

from pathlib import Path

from techshort.assets import BUILTIN_FONT_ASSET_IDS, ensure_builtin_assets
from techshort.domain.storage import ProjectStore
from techshort.review import approve_rights


def test_builtin_fonts_are_hashed_licensed_and_idempotent(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", "font-assets")
    store.initialize("Font assets")

    assets = ensure_builtin_assets(store)
    assert {asset.asset_id for asset in assets.assets} == BUILTIN_FONT_ASSET_IDS
    assert all(asset.license == "SIL Open Font License 1.1" for asset in assets.assets)
    assert all(store.path(asset.local_path).is_file() for asset in assets.assets)

    approve_rights(store, "test-reviewer")
    again = ensure_builtin_assets(store)
    assert all(asset.review_status == "approved" for asset in again.assets)
    assert store.project().approvals.rights == "approved"
