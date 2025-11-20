"""Test fixtures"""
import pytest
from src.database.sqlite import SQLiteDatabase

@pytest.fixture
async def test_db():
    """Fixture for test database"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    return db

@pytest.fixture
async def test_user(test_db):
    """Fixture for test user"""
    user = await test_db.create_user("testuser")
    return user
