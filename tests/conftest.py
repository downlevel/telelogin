import os

os.environ.update(BOT_TOKEN="123:test", SECRET_KEY="s" * 32, INTERNAL_API_KEY="i" * 32)

import pytest
from src.database.sqlite import SQLiteDatabase


@pytest.fixture
async def db(tmp_path):
    database = SQLiteDatabase(str(tmp_path / "test.db"))
    await database.init_db()
    return database
