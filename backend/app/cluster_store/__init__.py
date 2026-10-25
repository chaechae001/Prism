"""Explicit private storage; importing this package never connects to a database."""
from .bundle import prepare_bundle, validate_bundle, summarize_bundle, write_bundle


def store_bundle(value, *, engine=None):
    from .repository import store_bundle as store
    return store(value,engine=engine)


__all__ = ['prepare_bundle','validate_bundle','summarize_bundle','write_bundle','store_bundle']
