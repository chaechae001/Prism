"""Primary local development API: news v1 and article-scoped chat."""

from .chat.config import load_chat_env

load_chat_env()

from .connection_api import app  # noqa: E402
from .chat.router import router  # noqa: E402

app.include_router(router)
