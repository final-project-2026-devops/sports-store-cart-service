from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import catalog_client
from database import carts_table
from models import AddItemRequest, UpdateItemRequest
from security import bearer_scheme, get_current_user

router = APIRouter(prefix="/cart", tags=["cart"])


def _decimal_to_float(obj):
    """Recursively convert Decimal values for JSON serialisation."""
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def cart_response(items: list[dict]) -> dict:
    subtotal = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)
    return {"items": items, "subtotal": subtotal}


def load_items(user_id: str) -> list[dict]:
    result = carts_table.get_item(Key={"user_id": user_id})
    item = result.get("Item")
    if item is None:
        return []
    raw_items = item.get("items", [])
    return _decimal_to_float(raw_items)


def save_items(user_id: str, items: list[dict]) -> None:
    # Convert floats to Decimal for DynamoDB storage
    def to_decimal(obj):
        if isinstance(obj, list):
            return [to_decimal(i) for i in obj]
        if isinstance(obj, dict):
            return {k: to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, float):
            return Decimal(str(obj))
        return obj

    carts_table.put_item(Item={
        "user_id": user_id,
        "items": to_decimal(items),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@router.get("")
async def get_cart(user: dict = Depends(get_current_user)):
    return cart_response(load_items(user["sub"]))


@router.post("/items")
async def add_item(
    payload: AddItemRequest,
    user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    variant = await catalog_client.get_variant(payload.sku, credentials.credentials)

    items = load_items(user["sub"])
    existing = next((i for i in items if i["sku"] == payload.sku), None)
    new_quantity = payload.quantity + (existing["quantity"] if existing else 0)
    if variant["stock_quantity"] < new_quantity:
        raise HTTPException(status_code=409, detail="Insufficient stock")

    if existing:
        existing["quantity"] = new_quantity
    else:
        items.append(
            {
                "product_id": variant["product_id"],
                "sku": variant["sku"],
                "name": variant["name"],
                "size": variant["size"],
                "color": variant["color"],
                "quantity": payload.quantity,
                "unit_price": variant["price"],
                "image_url": variant["image_url"],
            }
        )
    save_items(user["sub"], items)
    return cart_response(items)


@router.put("/items/{sku}")
async def update_item(
    sku: str,
    payload: UpdateItemRequest,
    user: dict = Depends(get_current_user),
):
    items = load_items(user["sub"])
    existing = next((i for i in items if i["sku"] == sku), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Item not in cart")
    if payload.quantity == 0:
        items = [i for i in items if i["sku"] != sku]
    else:
        existing["quantity"] = payload.quantity
    save_items(user["sub"], items)
    return cart_response(items)


@router.delete("/items/{sku}")
async def remove_item(sku: str, user: dict = Depends(get_current_user)):
    items = load_items(user["sub"])
    if not any(i["sku"] == sku for i in items):
        raise HTTPException(status_code=404, detail="Item not in cart")
    items = [i for i in items if i["sku"] != sku]
    save_items(user["sub"], items)
    return cart_response(items)


@router.delete("")
async def clear_cart(user: dict = Depends(get_current_user)):
    carts_table.delete_item(Key={"user_id": user["sub"]})
    return {"message": "Cart cleared"}
