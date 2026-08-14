# src/bugfixer/models.py
"""Pydantic data models for bugfixer harness."""

from enum import Enum
from pydantic import BaseModel, field_validator


class HITLStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class StopReason(str, Enum):
    SUCCESS = "SUCCESS"
    NO_PROGRESS = "NO_PROGRESS"
    MAX_ITERATIONS = "MAX_ITERATIONS"


class TaskConfig(BaseModel):
    test_node: str
    bug_description: str
    allow_paths: list[str]
    project_root: str

    @field_validator("allow_paths")
    @classmethod
    def validate_allow_paths(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("allow_paths must not be empty")
        return v


class LLMResponse(BaseModel):
    content: str
    raw: dict


class Decision(BaseModel):
    thought: str
    action: str
    action_input: dict


class Action(BaseModel):
    name: str
    params: dict
    iteration: int


class ToolResult(BaseModel):
    success: bool
    output: str
    error: str | None = None
    exit_code: int | None = None


class GuardrailResult(BaseModel):
    allowed: bool
    reason: str
    requires_hitl: bool


class HITLRequest(BaseModel):
    id: str
    action: Action
    diff: str | None = None
    command: str | None = None
    status: HITLStatus = HITLStatus.PENDING


class Failure(BaseModel):
    test_name: str
    error_type: str
    file: str | None = None
    line: int | None = None
    message: str


class TestResult(BaseModel):
    __test__ = False  # prevent pytest from collecting this as a test class

    passed: bool
    failures: list[Failure]
    raw_output: str


class StopDecision(BaseModel):
    should_stop: bool
    reason: StopReason
    iteration: int


class SessionRecord(BaseModel):
    id: str
    task: TaskConfig
    actions: list[Action]
    results: list[ToolResult]
    test_results: list[TestResult]
    stop_reason: str | None = None
    created_at: str
    updated_at: str
