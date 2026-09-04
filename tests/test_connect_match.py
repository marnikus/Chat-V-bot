"""Tab URL pattern matching (pure)."""
from chatflow.browser.connect import tab_matches


def test_substring_match():
    assert tab_matches("virt-chat.com", "https://ru.virt-chat.com/chat")
    assert not tab_matches("chatgpt.com", "https://ru.virt-chat.com/chat")


def test_star_and_empty_match_any_real_tab():
    assert tab_matches("*", "https://example.com/x")
    assert tab_matches("", "https://example.com/x")
    assert tab_matches("   ", "https://example.com/x")
    assert not tab_matches("*", "about:blank")
    assert not tab_matches("*", "")


def test_case_sensitive_substring():
    assert tab_matches("ru.virt-chat.com", "https://ru.virt-chat.com/chat")
    assert not tab_matches("VIRT-CHAT", "https://ru.virt-chat.com/chat")
