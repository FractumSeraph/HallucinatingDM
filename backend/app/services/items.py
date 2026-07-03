from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryEntry, Item


async def get_or_create_item(
    db: AsyncSession,
    campaign_id: str,
    name: str,
    description: str = "",
    item_type: str = "",
    source: str = "custom",
) -> Item:
    result = await db.execute(
        select(Item).where(Item.campaign_id == campaign_id, Item.name.ilike(name.strip()))
    )
    item = result.scalars().first()
    if item:
        return item
    item = Item(
        campaign_id=campaign_id,
        name=name.strip(),
        description=description,
        item_type=item_type,
        source=source,
    )
    db.add(item)
    await db.flush()
    return item


async def change_inventory(
    db: AsyncSession,
    campaign_id: str,
    owner_type: str,
    owner_id: str,
    item_name: str,
    delta: int,
    description: str = "",
) -> dict:
    """Add (delta>0) or remove (delta<0) items; returns the resulting quantity."""
    item = await get_or_create_item(db, campaign_id, item_name, description)
    result = await db.execute(
        select(InventoryEntry).where(
            InventoryEntry.owner_type == owner_type,
            InventoryEntry.owner_id == owner_id,
            InventoryEntry.item_id == item.id,
        )
    )
    entry = result.scalars().first()
    current = entry.quantity if entry else 0
    if delta < 0 and current + delta < 0:
        return {"error": f"Only {current}x {item.name} available to remove"}
    new_qty = current + delta
    if entry is None and new_qty > 0:
        entry = InventoryEntry(
            item_id=item.id, owner_type=owner_type, owner_id=owner_id, quantity=new_qty
        )
        db.add(entry)
    elif entry is not None:
        if new_qty == 0:
            await db.delete(entry)
        else:
            entry.quantity = new_qty
    return {"item": item.name, "quantity": new_qty, "prior_quantity": current}
