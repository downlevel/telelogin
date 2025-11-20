"""
Test SQLite database implementation
"""
import pytest
from src.database.sqlite import SQLiteDatabase

@pytest.mark.asyncio
async def test_create_user():
    """Test creating a user"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    
    user = await db.create_user("testuser")
    
    assert user is not None
    assert user.username == "testuser"
    assert user.telegram_id is None

@pytest.mark.asyncio
async def test_get_user_by_username():
    """Test retrieving user by username"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    
    await db.create_user("testuser")
    user = await db.get_user_by_username("testuser")
    
    assert user is not None
    assert user.username == "testuser"

@pytest.mark.asyncio
async def test_link_telegram_id():
    """Test linking Telegram ID"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    
    user = await db.create_user("testuser")
    result = await db.link_telegram_id(user.id, 123456789)
    
    assert result is True
    
    linked_user = await db.get_user_by_telegram_id(123456789)
    assert linked_user is not None
    assert linked_user.username == "testuser"

@pytest.mark.asyncio
async def test_create_login_request():
    """Test creating login request"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    
    user = await db.create_user("testuser")
    login_id = await db.create_login_request(user.id)
    
    assert login_id is not None
    
    login_request = await db.get_login_request(login_id)
    assert login_request is not None
    assert login_request["status"] == "pending"
