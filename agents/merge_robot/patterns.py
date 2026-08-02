"""Shared protected-path and adversarial-change patterns."""

import fnmatch

PROTECTED = [
    "agents/*", ".github/*", "contracts/*", "PRODUCT_DOCTRINE.md",
    "AGENTS.md", "engine/corpus/*", "scripts/check_invariants.py",
    "tasks/packets/*",
]


def matches_protected(path: str) -> bool:
    """Match using the recursive semantics on which the protection floor relies."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED)


BANNED = [
    r"WriteProcessMemory", r"ReadProcessMemory", r"SendInput\b",
    r"keybd_event", r"mouse_event", r"CreateRemoteThread",
    r"OpenProcess\(", r"pathofexile\.com/(?!api/)",
]
TEST_SIG = [
    r"^-\s*def test_", r"^-\s*it\(", r"^-\s*test\(",
    r"^\+.*@pytest\.mark\.skip",
    r"^\+\s*(it|test|describe)\.skip\(",
    r"^\+\s*xit\(",
]
