"""The two single-deal lookups (`deal_item` for a deal in progress, `deal_history_item` for an
archived one) shared by `buying` (reconciliation) and `deals` (`get`). Each caller keeps its own
policy for what a miss or a failure means."""

from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._mappers.deals import map_archived_deal, map_deal
from whitemarket._runtime.unset import UNSET, UnsetType
from whitemarket.models.deals import Deal


async def find_live_deal(
    generated: AsyncGeneratedClient,
    *,
    id: str | UnsetType = UNSET,
    custom_id: str | UnsetType = UNSET,
) -> Deal:
    """The deal in progress with this id or custom id; `NotFoundError` when there is none."""
    found = await generated.deal_item(custom_id=custom_id, id=id)
    return map_deal(found.deal_item, ("deal_item",))


async def find_archived_deal(
    generated: AsyncGeneratedClient,
    *,
    id: str | UnsetType = UNSET,
    custom_id: str | UnsetType = UNSET,
) -> Deal:
    """The archived deal with this id or custom id; `NotFoundError` when there is none."""
    found = await generated.deal_history_item(custom_id=custom_id, id=id)
    return map_archived_deal(found.deal_history_item, ("deal_history_item",))
