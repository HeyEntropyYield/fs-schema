from datetime import datetime
from pathlib import Path

import fs_schema as fss
from glom_navigation import Library, body_on, latest_body, latest_title


def test_glom_follows_one_chain(tmp_path: Path) -> None:
    day = tmp_path / "shelf" / "2026-09-17"
    other = tmp_path / "shelf" / "2026-09-18"
    fss.put(day / "body.txt", "body")
    fss.put(day / "note.json", '{"title": "hi"}')
    fss.put(other / "body.txt", "later")
    fss.put(other / "note.json", '{"title": "later"}')

    bound = fss.raise_mismatch(Library.bind(tmp_path))
    assert latest_body(bound) == other / "body.txt"
    assert latest_title(bound) == "later"
    assert body_on(bound, datetime(2026, 9, 17)) == day / "body.txt"
    assert body_on(bound, datetime(2026, 1, 1)) is None
