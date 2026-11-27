import types
from unittest.mock import MagicMock

import pytest

from antikythera import plugin as plugin_module
from antikythera.plugin import PLUGIN_MANAGER


@pytest.fixture(autouse=True)
def _isolated_plugin_manager_state():
    """Snapshot/restore the singleton's discovery state around each test.

    `PLUGIN_MANAGER` is a process-wide singleton (other test modules, e.g.
    tests/actors/test_cli.py, trigger real discovery on it), so tests here must not leak
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


def _only_current_group(plugins):
    """A fake `entry_points` that returns `plugins` for the actors group and nothing for others."""

    def fake(group):
        return plugins if group == plugin_module._PLUGINS_GROUP else []

    return MagicMock(side_effect=fake)


def _current_group_calls(calls):
    return [c for c in calls.call_args_list if c.kwargs.get("group") == plugin_module._PLUGINS_GROUP]


def test_discover_plugins_strict_returns_no_failures_when_all_import(monkeypatch):
    entry_points = [_fake_module_entry_point("good_a"), _fake_module_entry_point("good_b")]
    monkeypatch.setattr(plugin_module, "entry_points", _only_current_group(entry_points))

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == []
    assert "good_a" in PLUGIN_MANAGER._loaded_modules
    assert "good_b" in PLUGIN_MANAGER._loaded_modules


def test_discover_plugins_strict_collects_failures_without_warning(monkeypatch, recwarn):
    error = RuntimeError("dependency missing")
    monkeypatch.setattr(plugin_module, "entry_points", _only_current_group([_failing_entry_point("broken", error)]))

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == [("broken", error)]
    assert len(recwarn) == 0


def test_discover_plugins_strict_still_imports_successful_plugins_when_another_fails(monkeypatch):
    error = ImportError("no ROS")
    entry_points = [_fake_module_entry_point("good"), _failing_entry_point("broken", error)]
    monkeypatch.setattr(plugin_module, "entry_points", _only_current_group(entry_points))

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == [("broken", error)]
    assert "good" in PLUGIN_MANAGER._loaded_modules


def test_discover_plugins_strict_always_reattempts_every_entry_point(monkeypatch):
    calls = _only_current_group([_fake_module_entry_point("good")])
    monkeypatch.setattr(plugin_module, "entry_points", calls)

    PLUGIN_MANAGER.discover_plugins_strict()
    PLUGIN_MANAGER.discover_plugins_strict()

    assert len(_current_group_calls(calls)) == 2


def test_discover_plugins_warns_and_continues_on_failure(monkeypatch):
    error = RuntimeError("boom")
    monkeypatch.setattr(plugin_module, "entry_points", _only_current_group([_failing_entry_point("broken", error)]))

    with pytest.warns(RuntimeWarning, match="broken"):
        PLUGIN_MANAGER.discover_plugins()

    assert PLUGIN_MANAGER._auto_discovery_done is True


def test_discover_plugins_skips_second_call_once_done(monkeypatch):
    calls = _only_current_group([])
    monkeypatch.setattr(plugin_module, "entry_points", calls)

    PLUGIN_MANAGER.discover_plugins()
    PLUGIN_MANAGER.discover_plugins()

    assert len(_current_group_calls(calls)) == 1


def test_plugins_under_the_legacy_group_are_reported_not_loaded(monkeypatch):
    legacy = _fake_module_entry_point("old_style")

    def fake(group):
        return [legacy] if group == plugin_module._LEGACY_PLUGINS_GROUP else []

    monkeypatch.setattr(plugin_module, "entry_points", fake)

    with pytest.warns(RuntimeWarning, match="antikythera.actors"):
        failures = PLUGIN_MANAGER.discover_plugins_strict()

    assert failures == []
    assert "old_style" not in PLUGIN_MANAGER._loaded_modules
