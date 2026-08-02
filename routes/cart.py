from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import catalog_client
from database import get_db_table
from models import AddItemRequest, UpdateItemRequest
from security import bearer_scheme, get_current_user

router = APIRouter(prefix="/cart", tags=["cart"])


def _item_from_dynamo(item: dict) -> dict:
    """Convert a DynamoDB-native item (Decimal numbers) to JSON-safe types."""
    converted = dict(item)
    converted["quantity"] = int(converted["quantity"])
    converted["unit_price"] = float(converted["unit_price"])
    return converted


def _item_to_dynamo(item: dict) -> dict:
    """Convert an in-memory item (float/int) to DynamoDB-native types."""
    converted = dict(item)
    converted["quantity"] = int(converted["quantity"])
    converted["unit_price"] = Decimal(str(converted["unit_price"]))
    return converted


def cart_response(items: list[dict]) -> dict:
    subtotal = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)
    return {"items": items, "subtotal": subtotal}


async def load_items(table, cart_id: str) -> list[dict]:
    resp = await table.get_item(Key={"cart_id": cart_id})
    item = resp.get("Item")
    if not item:
        return []
    return [_item_from_dynamo(i) for i in item["items"]]


async def save_items(table, cart_id: str, items: list[dict]) -> None:
    await table.put_item(
        Item={
            "cart_id": cart_id,
            "items": [_item_to_dynamo(i) for i in items],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.get("")
async def get_cart(
    user: dict = Depends(get_current_user), table=Depends(get_db_table)
):
    # user["sub"] doubles as the cart's DynamoDB partition key (cart_id) — see add_item.
    return cart_response(await load_items(table, user["sub"]))


@router.post("/items")
async def add_item(
    payload: AddItemRequest,
    user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    table=Depends(get_db_table),
):
    variant = await catalog_client.get_variant(payload.sku, credentials.credentials)

    # DynamoDB table only has one key, cart_id. We use the JWT's user_id (sub) as
    # cart_id directly, since each user has exactly one cart — replicating the old
    # Mongo unique-index-on-user_id invariant with an O(1) key lookup instead of a scan.
    cart_id = user["sub"]
    items = await load_items(table, cart_id)
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
    await save_items(table, cart_id, items)
    return cart_response(items)


@router.put("/items/{sku}")
async def update_item(
    sku: str,
    payload: UpdateItemRequest,
    user: dict = Depends(get_current_user),
    table=Depends(get_db_table),
):
    items = await load_items(table, user["sub"])
    existing = next((i for i in items if i["sku"] == sku), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Item not in cart")
    if payload.quantity == 0:
        items = [i for i in items if i["sku"] != sku]
    else:
        existing["quantity"] = payload.quantity
    await save_items(table, user["sub"], items)
    return cart_response(items)


@router.delete("/items/{sku}")
async def remove_item(
    sku: str, user: dict = Depends(get_current_user), table=Depends(get_db_table)
):
    items = await load_items(table, user["sub"])
    if not any(i["sku"] == sku for i in items):
        raise HTTPException(status_code=404, detail="Item not in cart")
    items = [i for i in items if i["sku"] != sku]
    await save_items(table, user["sub"], items)
    return cart_response(items)


@router.delete("")
async def clear_cart(
    user: dict = Depends(get_current_user), table=Depends(get_db_table)
):
    await table.delete_item(Key={"cart_id": user["sub"]})
    return {"message": "Cart cleared"}
