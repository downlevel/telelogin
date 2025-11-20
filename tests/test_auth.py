"""
Test authentication service
"""
import pytest
from src.services.auth_service import AuthService
from src.database.sqlite import SQLiteDatabase

@pytest.mark.asyncio
async def test_start_login():
    """Test starting login process"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    
    auth_service = AuthService(db)
    
    # Create and link user
    user = await db.create_user("testuser")
    await db.link_telegram_id(user.id, 123456789)
    
    # Start login
    result = await auth_service.start_login("testuser")
    
    assert result is not None
    assert "login_id" in result
    assert result["status"] == "pending"

@pytest.mark.asyncio
async def test_confirm_login():
    """Test confirming login"""
    db = SQLiteDatabase(":memory:")
    await db.init_db()
    
    auth_service = AuthService(db)
    
    # Create and link user
    user = await db.create_user("testuser")
    await db.link_telegram_id(user.id, 123456789)
    
    # Start login
    login_result = await auth_service.start_login("testuser")
    login_id = login_result["login_id"]
    
    # Confirm login
    confirm_result = await auth_service.confirm_login(login_id, 123456789)
    
    assert confirm_result is not None
    assert confirm_result["status"] == "authenticated"
    assert "session_token" in confirm_result
