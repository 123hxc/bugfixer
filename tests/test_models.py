# tests/test_models.py
from bugfixer.models import (
    TaskConfig, LLMResponse, Decision, Action, ToolResult,
    GuardrailResult, HITLRequest, HITLStatus, Failure, TestResult,
    StopDecision, StopReason, SessionRecord,
)


def test_task_config_valid():
    tc = TaskConfig(
        test_node="tests/test_foo.py::test_bar",
        bug_description="add function returns wrong result",
        allow_paths=["src/foo.py"],
        project_root="/tmp/project",
    )
    assert tc.test_node == "tests/test_foo.py::test_bar"
    assert len(tc.allow_paths) == 1


def test_task_config_empty_allow_paths_raises():
    import pytest
    with pytest.raises(ValueError, match="allow_paths must not be empty"):
        TaskConfig(
            test_node="tests/test_foo.py::test_bar",
            bug_description="bug",
            allow_paths=[],
            project_root="/tmp/project",
        )


def test_decision_fields():
    d = Decision(thought="I need to read the file", action="read_file", action_input={"path": "src/foo.py"})
    assert d.action == "read_file"
    assert d.action_input["path"] == "src/foo.py"


def test_action_with_iteration():
    a = Action(name="write_file", params={"path": "src/foo.py", "content": "fixed"}, iteration=3)
    assert a.iteration == 3
    assert a.params["content"] == "fixed"


def test_tool_result_success():
    r = ToolResult(success=True, output="file written", error=None, exit_code=None)
    assert r.success is True
    assert r.error is None


def test_guardrail_result_blocked():
    gr = GuardrailResult(allowed=False, reason="path not in whitelist", requires_hitl=True)
    assert gr.allowed is False
    assert gr.requires_hitl is True


def test_hitl_status_enum():
    assert HITLStatus.PENDING == "PENDING"
    assert HITLStatus.APPROVED == "APPROVED"
    assert HITLStatus.REJECTED == "REJECTED"


def test_hitl_request_default_pending():
    a = Action(name="write_file", params={"path": "x"}, iteration=0)
    req = HITLRequest(id="req-1", action=a, diff="--- a\n+++ b\n", command=None)
    assert req.status == HITLStatus.PENDING


def test_failure_fields():
    f = Failure(test_name="test_foo.py::test_bar", error_type="AssertionError", file="src/foo.py", line=5, message="assert 1 == 3")
    assert f.error_type == "AssertionError"
    assert f.line == 5


def test_test_result_passed():
    tr = TestResult(passed=True, failures=[], raw_output="1 passed")
    assert tr.passed is True
    assert len(tr.failures) == 0


def test_stop_reason_enum():
    assert StopReason.SUCCESS == "SUCCESS"
    assert StopReason.NO_PROGRESS == "NO_PROGRESS"
    assert StopReason.MAX_ITERATIONS == "MAX_ITERATIONS"


def test_stop_decision():
    sd = StopDecision(should_stop=True, reason=StopReason.SUCCESS, iteration=5)
    assert sd.should_stop is True
    assert sd.reason == StopReason.SUCCESS


def test_session_record_creation():
    tc = TaskConfig(
        test_node="tests/test_foo.py::test_bar",
        bug_description="bug",
        allow_paths=["src/foo.py"],
        project_root="/tmp/project",
    )
    sr = SessionRecord(
        id="session-1",
        task=tc,
        actions=[],
        results=[],
        test_results=[],
        stop_reason=None,
        created_at="2026-08-14T10:00:00Z",
        updated_at="2026-08-14T10:00:00Z",
    )
    assert sr.id == "session-1"
    assert sr.task == tc
    assert sr.stop_reason is None
