"""Infrared camera player package."""


def run() -> int:
    from .app import run as _run

    return _run()


__all__ = ["run"]
