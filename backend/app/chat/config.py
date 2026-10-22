"""Compatibility loader for server configuration."""
from ..config import load_environment


def load_chat_env():
    load_environment()
