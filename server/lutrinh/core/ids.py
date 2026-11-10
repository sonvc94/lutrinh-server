"""Random ids for rows that appear in packages (``rt_…`` routes, ``m_…`` media)."""

from __future__ import annotations

import secrets


def new_route_id() -> str:
    return "rt_" + secrets.token_hex(4)


def new_media_id() -> str:
    return "m_" + secrets.token_hex(6)


def new_stop_id() -> str:
    return "s_" + secrets.token_hex(4)
