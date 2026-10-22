import atexit
import os
from pathlib import Path
import tempfile

import pytest

# Set before importing settings/app; all lifespan tests share this temporary key.
_oidc_directory = tempfile.TemporaryDirectory(prefix="telelogin-test-keys-")
atexit.register(_oidc_directory.cleanup)
os.environ["OIDC_KEY_FILE"] = str(Path(_oidc_directory.name) / "oidc-signing-key.pem")

os.environ.update(BOT_TOKEN="123:test", SECRET_KEY="s" * 32, INTERNAL_API_KEY="i" * 32)

from src.database.sqlite import SQLiteDatabase  # noqa: E402 (test environment must precede settings)


@pytest.fixture(scope="session", autouse=True)
def no_checkout_signing_key():
    yield
    assert not (Path(__file__).resolve().parents[1] / "data/oidc-signing-key.pem").exists()


@pytest.fixture
async def db(tmp_path):
    database = SQLiteDatabase(str(tmp_path / "test.db"))
    await database.init_db()
    return database
