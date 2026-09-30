from __future__ import annotations

from originweave.capabilities.prompt import language_directive


def test_language_directive_names_the_tag_and_scopes_the_rule() -> None:
    directive = language_directive("zh-CN")
    assert "zh-CN" in directive
    assert "goal" in directive and "title" in directive
    # It must not force translation of verbatim quotes / fixed JSON enums.
    assert "verbatim" in directive
    assert "json" in directive.lower()


def test_language_directive_is_pure() -> None:
    assert language_directive("en") == language_directive("en")
    assert language_directive("en") != language_directive("zh-CN")
