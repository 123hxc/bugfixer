import pytest
from pathlib import Path


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A temporary project directory with a sample Python file."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "buggy.py").write_text(
        "def add(a, b):\n    return a - b  # bug: should be a + b\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_buggy.py").write_text(
        "from src.buggy import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
    )
    return tmp_path


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """A temporary config directory mimicking ~/.bugfixer/."""
    config_dir = tmp_path / ".bugfixer"
    config_dir.mkdir()
    return config_dir
