# tests/test_exceptions.py
import pytest
from bugfixer.exceptions import (
    BugfixerError, LLMError, DecisionError, ToolError, ConfigError, GuardrailError,
)


def test_base_error():
    with pytest.raises(BugfixerError, match="something went wrong"):
        raise BugfixerError("something went wrong")


def test_llm_error_is_bugfixer_error():
    e = LLMError("API timeout")
    assert isinstance(e, BugfixerError)
    assert str(e) == "API timeout"


def test_decision_error_is_bugfixer_error():
    e = DecisionError("invalid JSON")
    assert isinstance(e, BugfixerError)


def test_tool_error_is_bugfixer_error():
    e = ToolError("file not found")
    assert isinstance(e, BugfixerError)


def test_config_error_is_bugfixer_error():
    e = ConfigError("invalid YAML")
    assert isinstance(e, BugfixerError)


def test_guardrail_error_is_bugfixer_error():
    e = GuardrailError("whitelist check failed")
    assert isinstance(e, BugfixerError)
