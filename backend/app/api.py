"""Primary local development API: news v1 and article-scoped chat."""

from .chat.config import load_chat_env

load_chat_env()

from .connection_api import app  # noqa: E402
from .chat.router import router  # noqa: E402

app.include_router(router)
from .account_auth import router as account_router
from .reader_accounts import router as reader_router
from .editorial_api import router as editorial_router
app.include_router(account_router)
app.include_router(reader_router)
app.include_router(editorial_router)
from .local_article_body import router as body_router
app.include_router(body_router)
from .ai_pipeline.router import router as ai_router
app.include_router(ai_router)

from .reading_api import router as reading_router
app.include_router(reading_router)
