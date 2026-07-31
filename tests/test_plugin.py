import types
from unittest.mock import MagicMock

import pytest

from antikythera import plugin as plugin_module
from antikythera.plugin import PLUGIN_MANAGER


@pytest.fixture(autouse=True)
def _isolated_plugin_manager_state():
    """Snapshot/restore the singleton's discovery state around each test.

    `PLUGIN_MANAGER` is a process-wide singleton (other test modules, e.g.
    tests/agents/test_cli.py, trigger real discovery on it), so tests here must not leak
    state into it or inherit state from it.
    """
    saved_done = PLUGIN_MANAGER._auto_discovery_done
    saved_loaded = set(PLUGIN_MANAGER._loaded_modules)
    saved_files = set(PLUGIN_MANAGER._module_files)
    PLUGIN_MANAGER._auto_discovery_done = False
    PLUGIN_MANAGER._loaded_modules = set()
    PLUGIN_MANAGER._module_files = set()
    yield
    PLUGIN_MANAGER._auto_discovery_done = saved_done
    PLUGIN_MANAGER._loaded_modules = saved_loaded
    PLUGIN_MANAGER._module_files = saved_files


def _fake_module_entry_point(name):
    """An entry point whose target is a module (has __file__), like a real plugin."""
    module = types.ModuleType(name)
    module.__file__ = f"/fake/{name}.py"
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = module
    return ep


def _failing_entry_point(name, error):
    ep = MagicMock()
    ep.name = name
    ep.load.side_effect = error
    return ep


def test_discover_plugins_strict_returns_no_failures_when_all_import(monkeypatch):
    entry_points = [_fake_module_entry_point("good_a"), _fake_module_entry_point("good_b")]
    monkeypatch.setattr(plugin_module, "entry_points", lambda group: entry_points)

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == []
    assert "good_a" in PLUGIN_MANAGER._loaded_modules
    assert "good_b" in PLUGIN_MANAGER._loaded_modules


def test_discover_plugins_strict_collects_failures_without_warning(monkeypatch, recwarn):
    error = RuntimeError("dependency missing")
    monkeypatch.setattr(plugin_module, "entry_points", lambda group: [_failing_entry_point("broken", error)])

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == [("broken", error)]
    assert len(recwarn) == 0


def test_discover_plugins_strict_still_imports_successful_plugins_when_another_fails(monkeypatch):
    error = ImportError("no ROS")
    entry_points = [_fake_module_entry_point("good"), _failing_entry_point("broken", error)]
    monkeypatch.setattr(plugin_module, "entry_points", lambda group: entry_points)

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == [("broken", error)]
    assert "good" in PLUGIN_MANAGER._loaded_modules


def test_discover_plugins_strict_always_reattempts_every_entry_point(monkeypatch):
    calls = MagicMock(return_value=[_fake_module_entry_point("good")])
    monkeypatch.setattr(plugin_module, "entry_points", calls)

    PLUGIN_MANAGER.discover_plugins_strict()
    PLUGIN_MANAGER.discover_plugins_strict()

    assert calls.call_count == 2


def test_discover_plugins_warns_and_continues_on_failure(monkeypatch):
    error = RuntimeError("boom")
    monkeypatch.setattr(plugin_module, "entry_points", lambda group: [_failing_entry_point("broken", error)])

    with pytest.warns(RuntimeWarning, match="broken"):
        PLUGIN_MANAGER.discover_plugins()

    assert PLUGIN_MANAGER._auto_discovery_done is True


def test_discover_plugins_skips_second_call_once_done(monkeypatch):
    calls = MagicMock(return_value=[])
    monkeypatch.setattr(plugin_module, "entry_points", calls)

    PLUGIN_MANAGER.discover_plugins()
    PLUGIN_MANAGER.discover_plugins()

    assert calls.call_count == 1
