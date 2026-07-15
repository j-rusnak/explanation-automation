from __future__ import annotations

import pytest
from pydantic import ValidationError

from techshort.domain.models import ScriptSegment


@pytest.mark.parametrize("label", ["transition", "cta"])
def test_factual_text_cannot_escape_provenance_with_a_nonfactual_label(label: str) -> None:
    with pytest.raises(ValidationError, match="requires at least one claim"):
        ScriptSegment.model_validate(
            {
                "segment_id": "bypass-attempt",
                "text": "The treatment causes a 50 percent improvement in every population.",
                "segment_type": label,
                "claim_ids": [],
                "approximate_duration": 4,
            }
        )
