import pytest

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
