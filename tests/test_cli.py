import socket

import pytest

from paper_cart import cli


def test_choose_port_reuses_a_running_app(monkeypatch):
    monkeypatch.setattr(cli, "running_instance", lambda port, host=cli.HOST: port == 8001)
    monkeypatch.setattr(cli, "port_is_free", lambda port, host=cli.HOST: port == 8002)
    assert cli.choose_port(8000) == (8001, True)


def test_choose_port_skips_ports_in_use(monkeypatch):
    monkeypatch.setattr(cli, "running_instance", lambda port, host=cli.HOST: False)
    monkeypatch.setattr(cli, "port_is_free", lambda port, host=cli.HOST: port >= 8002)
    assert cli.choose_port(8000) == (8002, False)


def test_choose_port_gives_up(monkeypatch):
    monkeypatch.setattr(cli, "running_instance", lambda port, host=cli.HOST: False)
    monkeypatch.setattr(cli, "port_is_free", lambda port, host=cli.HOST: False)
    with pytest.raises(SystemExit):
        cli.choose_port(8000, tries=3)


def test_server_stays_on_localhost():
    assert cli.HOST == "127.0.0.1"


def test_port_is_free_sees_a_bound_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((cli.HOST, 0))
        holder.listen()
        port = holder.getsockname()[1]
        assert not cli.port_is_free(port)
        assert not cli.running_instance(port)
