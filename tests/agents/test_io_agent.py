import os
import pytest
from antikythera.models import Task, TaskParam, TaskInput
from antikythera_agents.io_agent import IOAgent


@pytest.fixture
def io_agent():
    return IOAgent()


def test_copy_single_file(io_agent, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    source_file = source_dir / "test.txt"
    source_file.write_text("hello world")

    dest_file = dest_dir / "copied.txt"

    task = Task(id="copy_task", type="io.copy", params=[TaskParam(name="source", value=str(source_file)), TaskParam(name="destination", value=str(dest_file))])

    result = io_agent.copy_file(task)

    assert os.path.exists(dest_file)
    assert dest_file.read_text() == "hello world"
    # Basic copy returns logical source/dest or list of copies?
    # Checking the code again: it returns {"copied_files": [...], "destination": "..."} for the updated version
    assert "copied_files" in result
    assert str(source_file) in result["copied_files"]


def test_copy_glob_pattern(io_agent, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    dest_dir = tmp_path / "dest"

    # Create multiple files
    (source_dir / "file1.txt").write_text("file1")
    (source_dir / "file2.txt").write_text("file2")
    (source_dir / "other.log").write_text("other")  # Should not be copied if we pattern *.txt

    task = Task(id="glob_task", type="io.copy", params=[TaskParam(name="source", value=str(source_dir / "*.txt")), TaskParam(name="destination", value=str(dest_dir))])

    result = io_agent.copy_file(task)

    assert os.path.exists(dest_dir)
    assert os.path.isdir(dest_dir)
    assert (dest_dir / "file1.txt").exists()
    assert (dest_dir / "file2.txt").exists()
    assert not (dest_dir / "other.log").exists()

    assert len(result["copied_files"]) == 2


def test_copy_glob_recursive(io_agent, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    dest_dir = tmp_path / "dest"

    (source_dir / "root.txt").write_text("root")
    (sub_dir / "nested.txt").write_text("nested")

    task = Task(id="recursive_task", type="io.copy", params=[TaskParam(name="source", value=str(source_dir / "**/*.txt")), TaskParam(name="destination", value=str(dest_dir))])

    io_agent.copy_file(task)

    assert os.path.exists(dest_dir)
    # Note: shutil.copy2 flattens if we just iterate and copy to dir.
    # The current implementation iterates sources and copies to destination dir.
    # It does not preserve directory structure in the destination, it just dumping files into destination.
    assert (dest_dir / "root.txt").exists()
    assert (dest_dir / "nested.txt").exists()


def test_copy_fail_dest_is_file(io_agent, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    dest_file = tmp_path / "existing_file.txt"
    dest_file.write_text("I exist")

    (source_dir / "f1.txt").write_text("1")
    (source_dir / "f2.txt").write_text("2")

    task = Task(id="fail_task", type="io.copy", params=[TaskParam(name="source", value=str(source_dir / "*.txt")), TaskParam(name="destination", value=str(dest_file))])

    with pytest.raises(ValueError, match="Destination .* is a file, but source matched multiple files"):
        io_agent.copy_file(task)


def test_copy_missing_params(io_agent):
    task = Task(id="bad_task", type="io.copy")

    with pytest.raises(ValueError, match="Source path.*required"):
        io_agent.copy_file(task)
