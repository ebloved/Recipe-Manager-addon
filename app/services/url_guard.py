"""Защита от SSRF для пользовательских URL.

Публичный VPS не должен ходить по внутренним адресам (127.0.0.1, 10/8,
169.254.169.254 и т.п.) по запросу пользователя. Проверяем схему и все
A/AAAA-адреса хоста; редиректы обрабатываются вручную с повторной проверкой.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from config import ALLOW_PRIVATE_URLS

_REDIRECT_CODES = {301, 302, 303, 307, 308}


class UnsafeURLError(ValueError):
    pass


def _check_ip(raw: str, allow_private: bool = False) -> None:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise UnsafeURLError(f"invalid address: {raw}") from exc
    if ALLOW_PRIVATE_URLS or allow_private:
        return
    if not ip.is_global:
        raise UnsafeURLError(f"private/reserved address is not allowed: {ip}")


def validate_public_url(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("only http/https URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        _check_ip(host, allow_private=allow_private)
        return url
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"cannot resolve host: {host}") from exc
    if not infos:
        raise UnsafeURLError(f"cannot resolve host: {host}")
    for info in infos:
        _check_ip(info[4][0], allow_private=allow_private)
    return url


async def safe_get(client, url: str, *, headers=None, max_redirects: int = 5):
    """GET с ручной проверкой каждого redirect."""
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current)
        resp = await client.get(current, headers=headers, follow_redirects=False)
        if resp.status_code in _REDIRECT_CODES:
            location = resp.headers.get("location")
            if not location:
                return resp
            current = urljoin(current, location)
            continue
        return resp
    raise UnsafeURLError("too many redirects")


def is_safe_public_url(url: str) -> bool:
    try:
        validate_public_url(url)
        return True
    except UnsafeURLError:
        return False
