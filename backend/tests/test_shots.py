"""Shot source-domain normalization tests."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from hoopslab.domain.shots import ArchiveShotRow, normalize_shot


def test_normalize_shot_preserves_preshot_context_and_target(
    archive_row_factory: Callable[..., dict[str, Any]],
) -> None:
    row = ArchiveShotRow.model_validate(archive_row_factory())

    shot = normalize_shot(row)

    assert shot.game_date.isoformat() == "2023-10-24"
    assert shot.seconds_remaining == 605
    assert shot.shot_value == 3
    assert shot.coordinate_x_tenths_ft == -35
    assert shot.made is True


def test_redundant_outcome_encodings_must_agree(
    archive_row_factory: Callable[..., dict[str, Any]],
) -> None:
    raw = archive_row_factory(EVENT_TYPE="Missed Shot", SHOT_MADE_FLAG=1)

    with pytest.raises(ValidationError, match="disagree"):
        ArchiveShotRow.model_validate(raw)


def test_overtime_clock_cannot_exceed_five_minutes(
    archive_row_factory: Callable[..., dict[str, Any]],
) -> None:
    raw = archive_row_factory(PERIOD=5, MINUTES_REMAINING=5, SECONDS_REMAINING=1)

    with pytest.raises(ValidationError, match="clock exceeds"):
        ArchiveShotRow.model_validate(raw)


def test_coordinate_outside_legacy_court_is_rejected(
    archive_row_factory: Callable[..., dict[str, Any]],
) -> None:
    with pytest.raises(ValidationError, match="LOC_X"):
        ArchiveShotRow.model_validate(archive_row_factory(LOC_X=251))
