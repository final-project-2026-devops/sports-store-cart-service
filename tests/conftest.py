import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

os.environ["JWT_SECRET"] = "test-secret"
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-table")

import jwt
import pytest
from fastapi.testclient import TestClient

from database import get_db_table
from main import app


def make_token(user_id="507f1f77bcf86cd799439011", email="user@test.com",
               role="customer", expires_minutes=60):
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, "test-secret", algorithm="HS256")


@pytest.fixture
def mock_table():
    """Stand-in for the DynamoDB Table resource yielded by get_db_table.

    get_item/put_item/delete_item are AsyncMocks; configure their
    return_value per-test to emulate DynamoDB response shapes.
    """
    table = MagicMock()
    table.get_item = AsyncMock(return_value={})
    table.put_item = AsyncMock(return_value={})
    table.delete_item = AsyncMock(return_value={})
    return table


@pytest.fixture
def client(mock_table):
    async def _override_get_db_table():
        yield mock_table

    app.dependency_overrides[get_db_table] = _override_get_db_table
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_table, None)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {make_token()}"}


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {make_token(role='admin')}"}
