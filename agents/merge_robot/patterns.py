"""Shared protected-path and adversarial-change patterns."""

PROTECTED = [
    "agents/*", ".github/*", "contracts/*", "PRODUCT_DOCTRINE.md",
    "AGENTS.md", "engine/corpus/*", "scripts/check_invariants.py",
]
BANNED = [
    r"WriteProcessMemory", r"ReadProcessMemory", r"SendInput\b",
    r"keybd_event", r"mouse_event", r"CreateRemoteThread",
    r"OpenProcess\(", r"pathofexile\.com/(?!api/)",
]
TEST_SIG = [
    r"^-\s*def test_", r"^-\s*it\(", r"^-\s*test\(",
    r"^\+.*@pytest\.mark\.skip", r"^\+.*\.skip\(", r"^\+.*xit\(",
]
