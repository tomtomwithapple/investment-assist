"""Shared test setup. The socket guard keeps every test off the network: only localhost and
Unix sockets may connect, so a test that reaches the internet (or a mistyped host) fails loudly."""

import socket

import pytest

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


class NetworkBlocked(RuntimeError):
    pass


def _is_local(address) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX path
        return True
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode()
    return host in LOCAL_HOSTS or host.startswith("127.")


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch):
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, address):
        if not _is_local(address):
            raise NetworkBlocked(f"test tried to reach {address!r}; only localhost is allowed")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _is_local(address):
            raise NetworkBlocked(f"test tried to reach {address!r}; only localhost is allowed")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not _is_local((host,)):
            raise NetworkBlocked(f"test tried to resolve {host!r}; only localhost is allowed")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
