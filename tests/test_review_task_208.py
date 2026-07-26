from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mvp_announcement_headline_matches_the_item_picker() -> None:
    announcement = (ROOT / "docs" / "announcements" / "mvp_launch.md").read_text()
    headline = next(
        line for line in announcement.splitlines() if line.startswith("# The MVP is live:")
    )

    assert "pick an item" in headline.lower(), (
        "v0 exposes an item picker, so the launch headline must describe picking an item"
    )
    assert "paste an item" not in headline.lower(), (
        "v0 has no item-paste input; advertising one repeats the copy defect"
    )
