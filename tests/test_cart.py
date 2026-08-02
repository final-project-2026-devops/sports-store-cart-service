from decimal import Decimal
from unittest.mock import AsyncMock, patch

USER_ID = "507f1f77bcf86cd799439011"

VARIANT_SNAPSHOT = {
    "product_id": "507f1f77bcf86cd799439021",
    "name": "Velocity Runner",
    "image_url": "/img/velocity.png",
    "sku": "VR-BLK-42",
    "color": "Black",
    "size": "42",
    "price": 129.99,
    "stock_quantity": 15,
}


def cart_item(quantity=2):
    """JSON-safe shape (float/int), as returned in HTTP responses."""
    return {
        "product_id": "507f1f77bcf86cd799439021",
        "sku": "VR-BLK-42",
        "name": "Velocity Runner",
        "size": "42",
        "color": "Black",
        "quantity": quantity,
        "unit_price": 129.99,
        "image_url": "/img/velocity.png",
    }


def dynamo_item(quantity=2):
    """DynamoDB-native shape (Decimal numbers), as stored in the table."""
    item = cart_item(quantity)
    item["quantity"] = Decimal(quantity)
    item["unit_price"] = Decimal("129.99")
    return item


def stored_cart_response(quantity=2):
    """A get_item response for an existing cart."""
    return {
        "Item": {
            "cart_id": USER_ID,
            "items": [dynamo_item(quantity)],
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    }


def test_get_cart_empty_shape(client, mock_table, auth_headers):
    mock_table.get_item.return_value = {}
    response = client.get("/api/cart", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "subtotal": 0}
    mock_table.get_item.assert_awaited_once_with(Key={"cart_id": USER_ID})


def test_get_cart_computes_subtotal(client, mock_table, auth_headers):
    mock_table.get_item.return_value = stored_cart_response(quantity=2)
    response = client.get("/api/cart", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["subtotal"] == 259.98


def test_get_cart_requires_token(client):
    response = client.get("/api/cart")
    assert response.status_code == 401


def test_add_item_creates_snapshot(client, mock_table, auth_headers):
    mock_table.get_item.return_value = {}
    with patch("routes.cart.catalog_client") as mock_catalog:
        mock_catalog.get_variant = AsyncMock(return_value=VARIANT_SNAPSHOT.copy())
        response = client.post(
            "/api/cart/items",
            json={"sku": "VR-BLK-42", "quantity": 2},
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0] == cart_item(quantity=2)
    assert body["subtotal"] == 259.98

    put_kwargs = mock_table.put_item.call_args.kwargs
    saved_item = put_kwargs["Item"]
    assert saved_item["cart_id"] == USER_ID
    assert saved_item["items"][0]["sku"] == "VR-BLK-42"
    assert saved_item["items"][0]["quantity"] == 2
    assert saved_item["items"][0]["unit_price"] == Decimal("129.99")


def test_add_same_sku_merges_quantity(client, mock_table, auth_headers):
    mock_table.get_item.return_value = stored_cart_response(quantity=2)
    with patch("routes.cart.catalog_client") as mock_catalog:
        mock_catalog.get_variant = AsyncMock(return_value=VARIANT_SNAPSHOT.copy())
        response = client.post(
            "/api/cart/items",
            json={"sku": "VR-BLK-42", "quantity": 3},
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 5


def test_add_item_insufficient_stock_409(client, mock_table, auth_headers):
    low_stock = dict(VARIANT_SNAPSHOT, stock_quantity=1)
    mock_table.get_item.return_value = {}
    with patch("routes.cart.catalog_client") as mock_catalog:
        mock_catalog.get_variant = AsyncMock(return_value=low_stock)
        response = client.post(
            "/api/cart/items",
            json={"sku": "VR-BLK-42", "quantity": 2},
            headers=auth_headers,
        )

    assert response.status_code == 409
    mock_table.put_item.assert_not_awaited()


def test_update_item_quantity(client, mock_table, auth_headers):
    mock_table.get_item.return_value = stored_cart_response(quantity=2)
    response = client.put(
        "/api/cart/items/VR-BLK-42",
        json={"quantity": 4},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 4


def test_update_item_zero_removes(client, mock_table, auth_headers):
    mock_table.get_item.return_value = stored_cart_response(quantity=2)
    response = client.put(
        "/api/cart/items/VR-BLK-42",
        json={"quantity": 0},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "subtotal": 0}


def test_update_missing_item_404(client, mock_table, auth_headers):
    mock_table.get_item.return_value = {}
    response = client.put(
        "/api/cart/items/GHOST",
        json={"quantity": 1},
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_remove_item(client, mock_table, auth_headers):
    mock_table.get_item.return_value = stored_cart_response(quantity=2)
    response = client.delete(
        "/api/cart/items/VR-BLK-42", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "subtotal": 0}


def test_remove_missing_item_404(client, mock_table, auth_headers):
    mock_table.get_item.return_value = {}
    response = client.delete(
        "/api/cart/items/GHOST", headers=auth_headers
    )

    assert response.status_code == 404


def test_clear_cart(client, mock_table, auth_headers):
    response = client.delete("/api/cart", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Cart cleared"}
    mock_table.delete_item.assert_awaited_once_with(Key={"cart_id": USER_ID})
