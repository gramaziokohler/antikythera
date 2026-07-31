import json

import pytest

from antikythera.plugin import PLUGIN_MANAGER
from antikythera_agents import cli


def test_no_subcommand_exits_nonzero_with_usage(capsys):
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([])

    assert exc_info.value.code != 0
    assert "usage" in capsys.readouterr().err.lower()


def test_run_parses_default_flags():
    parser = cli.build_parser()

    args = parser.parse_args(["run"])

    assert args.broker_host == "127.0.0.1"
    assert args.broker_port == 1883
    assert args.dev is False
    assert args.sys_only is False
    assert args.func is cli._run


def test_run_parses_all_flags():
    parser = cli.build_parser()

    args = parser.parse_args(["run", "--broker-host", "10.0.0.1", "--broker-port", "9999", "--dev", "--sys-only"])

    assert args.broker_host == "10.0.0.1"
    assert args.broker_port == 9999
    assert args.dev is True
    assert args.sys_only is True


def test_main_dispatches_to_run(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_run", lambda args: calls.append(args))

    cli.main(["run", "--broker-host", "10.0.0.1"])

    assert len(calls) == 1
    assert calls[0].broker_host == "10.0.0.1"


def test_describe_parses_default_format():
    parser = cli.build_parser()

    args = parser.parse_args(["describe"])

    assert args.format == "json"
    assert args.func is cli._describe


def test_describe_writes_json_catalog_to_stdout(capsys):
    cli.main(["describe"])

    catalog = json.loads(capsys.readouterr().out)

    agents = {entry["agent"]: entry for entry in catalog}
    assert "system" in agents

    tools = {tool["name"]: tool for tool in agents["system"]["tools"]}
    assert tools["start"] == {"name": "start", "type": "system.start"}
    assert tools["sleep"]["params"] == [{"name": "duration", "type_hint": "float", "optional": True}]


def test_describe_parses_allow_partial_default_false():
    parser = cli.build_parser()

    args = parser.parse_args(["describe"])

    assert args.allow_partial is False


def test_describe_parses_allow_partial_flag():
    parser = cli.build_parser()

    args = parser.parse_args(["describe", "--allow-partial"])

    assert args.allow_partial is True


def test_describe_exits_nonzero_and_writes_nothing_to_stdout_on_plugin_failure(monkeypatch, capsys):
    monkeypatch.setattr(PLUGIN_MANAGER, "discover_plugins_strict", lambda: [("broken", RuntimeError("boom"))])

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["describe"])

    assert exc_info.value.code != 0
    out, err = capsys.readouterr()
    assert out == ""
    assert "broken" in err
    assert "boom" in err


def test_describe_allow_partial_writes_catalog_and_failed_section(monkeypatch, capsys):
    monkeypatch.setattr(PLUGIN_MANAGER, "discover_plugins_strict", lambda: [("broken", RuntimeError("boom"))])

    cli.main(["describe", "--allow-partial"])

    result = json.loads(capsys.readouterr().out)

    assert "system" in {entry["agent"] for entry in result["agents"]}
    assert result["failed"] == [{"name": "broken", "error": "RuntimeError: boom"}]


def test_describe_exits_zero_when_every_plugin_imports(monkeypatch, capsys):
    monkeypatch.setattr(PLUGIN_MANAGER, "discover_plugins_strict", lambda: [])

    cli.main(["describe"])

    catalog = json.loads(capsys.readouterr().out)
    assert isinstance(catalog, list)
    assert "system" in {entry["agent"] for entry in catalog}
