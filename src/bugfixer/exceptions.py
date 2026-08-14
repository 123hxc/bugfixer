# src/bugfixer/exceptions.py
"""Custom exceptions for bugfixer harness."""


class BugfixerError(Exception):
    """Base exception for all bugfixer errors."""


class LLMError(BugfixerError):
    """LLM API call failed (timeout, rate limit, empty response)."""


class DecisionError(BugfixerError):
    """Failed to parse LLM response into a Decision."""


class ToolError(BugfixerError):
    """Tool execution failed (file not found, command timeout, unknown action)."""


class ConfigError(BugfixerError):
    """Configuration loading or validation failed."""


class GuardrailError(BugfixerError):
    """Guardrail check encountered an unexpected error."""
