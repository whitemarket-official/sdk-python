"""`client.deals`: look deals up, list and search them, wait for a status, and the buyer and seller
actions on a deal (SDK_SPEC 3.4).

Reads are queries, which the transport retries on transient failures (SDK_SPEC 1.4). The three
actions (`request_cancel`, `report_offer_sent`, `cancel_sending_offer`) are mutations: each is sent
exactly once and never retried (CLAUDE.md rule 2). A mutation that takes an id or a custom id is
never sent twice to "try the other key": a reference that could be either is resolved with queries
first.
"""

import contextlib
import math
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from functools import partial
from typing import Final

from whitemarket._async.deal_lookup import find_archived_deal, find_live_deal
from whitemarket._async.pagination import forward_pagination, iterate_pages
from whitemarket._async.seams import AsyncSleeper
from whitemarket._concurrency import async_sleep
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._generated.enums import Currency, MarketDealExternalCancelReason, MarketDealStatus
from whitemarket._generated.input_types import MarkerDealHistorySearchInput
from whitemarket._mappers.common import map_list, map_page, money
from whitemarket._mappers.deals import (
    deal_state_of,
    map_archived_deal,
    map_deal,
    map_deal_state,
)
from whitemarket._mappers.search import deal_history_search_input, search_argument
from whitemarket._mappers.wire import wire_enum, wire_enums
from whitemarket._runtime.text_args import require_text
from whitemarket._runtime.unset import UNSET, UnsetType, unset_if_none
from whitemarket._runtime.uuids import is_uuid
from whitemarket.deals.history import DealHistoryFilter
from whitemarket.deals.until import DealPredicate
from whitemarket.errors import DealWaitTimeoutError, DecodeError, NotFoundError
from whitemarket.live.async_session import AsyncLiveSession
from whitemarket.models.deal_status import DealStatus
from whitemarket.models.deals import Deal, DealState
from whitemarket.models.enums import OfferCancelReason
from whitemarket.models.money import Money
from whitemarket.models.page import Page, PageRequest

MAX_STATUS_IDS: Final = 300  # SDK_SPEC 3.4 / WHITEMARKET_API.md 4: ids per `deal_buyer_statuses`
MAX_COMMENT_LENGTH: Final = 255  # `deal_cancel_sending_offer` comment, ASCII only
_COMMENT = re.compile(r"[a-zA-Z0-9 _-]*", re.ASCII)
DEFAULT_POLL_INTERVAL: Final = 5.0
# With `live`, a deal event wakes the wait early, but two polls start at least this many seconds
# apart: a burst of events must not turn into a burst of requests (rate limit, WHITEMARKET_API.md).
MIN_EVENT_POLL_GAP: Final = 1.0


class AsyncDealsApi:
    """`client.deals`.

    A reference `id_or_custom_id` is the deal id (a UUID) or the `custom_id` of the purchase. The
    two cannot be told apart by shape, because a custom id is often a UUID too (the SDK generates
    UUIDv4 ones). A UUID-shaped reference is therefore looked up as an id first and then as a
    custom id; any other string can only be a custom id. An empty reference is a `ValueError`.

    Every method can raise the `WhiteMarketError` subclasses for transport, HTTP and GraphQL
    failures, and `DecodeError` for an unreadable answer; the sections below name the rest.
    """

    def __init__(
        self,
        generated: AsyncGeneratedClient,
        *,
        sleeper: AsyncSleeper = async_sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._generated = generated
        self._sleeper = sleeper
        self._clock = clock

    async def get(self, id_or_custom_id: str) -> Deal:
        """One deal by id or custom id: in progress (`deal_item`), else archived
        (`deal_history_item`). `Deal.is_archived` tells which one it was.

        Raises `NotFoundError` when neither a live nor an archived deal has this id or custom id;
        any other failure is raised at once, without trying the next lookup.
        """
        _require_reference(id_or_custom_id)
        if is_uuid(id_or_custom_id):
            try:
                return await self._lookup(id=id_or_custom_id)
            except NotFoundError:
                pass  # Not an id: a UUID-shaped custom id is next.
        return await self._lookup(custom_id=id_or_custom_id)

    async def statuses(self, ids: Sequence[str]) -> dict[str, DealState]:
        """The status snapshot of many deals (`deal_buyer_statuses`), one request per 300 ids.

        Each entry of `ids` is a deal id or a custom id (the server accepts both). The result is
        keyed by the requested string, in request order, each requested string once; a string the
        server does not know is absent (no error). A duplicate is sent once and returned once; the
        comparison is exact, so two spellings of one UUID are both sent and both returned, and the
        server decides. A state matches a key when the key is UUID-shaped and equals the state's
        `id` without regard to case, or equals the state's `custom_id` exactly. Chunking is applied
        after the deduplication. The server returns rows for deals where the caller is the buyer
        only.
        """
        requested = list(dict.fromkeys(ids))
        states: list[DealState] = []
        for start in range(0, len(requested), MAX_STATUS_IDS):
            chunk = requested[start : start + MAX_STATUS_IDS]
            answer = await self._generated.deal_buyer_statuses(chunk)
            states.extend(
                map_list(answer.deal_buyer_statuses, map_deal_state, ("deal_buyer_statuses",))
            )
        return _match_requested(requested, states)

    async def list_as_buyer(
        self,
        statuses_with: Sequence[DealStatus] | None = None,
        statuses_without: Sequence[DealStatus] | None = None,
    ) -> list[Deal]:
        """Deals in progress where the caller is the buyer (`deal_buyer_list`).

        `statuses_with` keeps only these statuses, `statuses_without` drops these (`QUEUED` is
        allowed like any other). Raises `ValueError` for a status the API schema does not accept.
        """
        answer = await self._generated.deal_buyer_list(
            _status_filter(statuses_with), _status_filter(statuses_without)
        )
        return map_list(answer.deal_buyer_list, map_deal, ("deal_buyer_list",))

    async def list_as_seller(
        self,
        statuses_with: Sequence[DealStatus] | None = None,
        statuses_without: Sequence[DealStatus] | None = None,
    ) -> list[Deal]:
        """Deals in progress where the caller is the seller (`deal_seller_list`); the filters are
        those of `list_as_buyer`."""
        answer = await self._generated.deal_seller_list(
            _status_filter(statuses_with), _status_filter(statuses_without)
        )
        return map_list(answer.deal_seller_list, map_deal, ("deal_seller_list",))

    async def history(
        self,
        filter: DealHistoryFilter | MarkerDealHistorySearchInput | None = None,
        page: PageRequest | None = None,
    ) -> Page[Deal]:
        """One page of archived deals (`deal_history`).

        Pass `PageRequest(after=previous.end_cursor)` for the next page while
        `previous.has_next_page` is true, or use `iterate_history()`. A raw
        `MarkerDealHistorySearchInput` is sent as is. The server's defaults apply to what `page`
        leaves out.
        """
        answer = await self._generated.deal_history(
            forward_pagination=forward_pagination(page),
            search=search_argument(filter, MarkerDealHistorySearchInput, deal_history_search_input),
        )
        return map_page(answer.deal_history, map_archived_deal, ("deal_history",))

    def iterate_history(
        self,
        filter: DealHistoryFilter | MarkerDealHistorySearchInput | None = None,
        page_size: int | None = None,
    ) -> AsyncIterator[Deal]:
        """Every archived deal that matches, page after page; a page is requested only when the
        previous one is consumed. `page_size` is the items per request (the server's default when
        None). Raises what `history()` raises, at the point of the iteration that reads the
        failing page, and `DecodeError` when the server reports a next page without a new cursor.
        """
        return iterate_pages(partial(self.history, filter), page_size, ("deal_history",))

    async def request_cancel(self, id: str) -> Deal:
        """Ask to cancel a deal as the buyer (`deal_request_cancel`), a mutation: sent once, never
        retried.

        Allowed only for the buyer and only after the seller has not sent the offer for 30
        minutes: check `Deal.is_cancel_by_buyer_supported` and `Deal.cancel_by_buyer_need_wait`
        first. `id` is the deal id (a UUID); a custom id is not accepted. Raises `ValueError`,
        before anything is sent, when `id` is not a UUID.
        """
        if not is_uuid(id):
            raise ValueError(
                "id must be a deal id (UUID); a custom_id is not accepted by deal_request_cancel"
            )
        answer = await self._generated.deal_request_cancel(id)
        return map_deal(answer.deal_request_cancel, ("deal_request_cancel",))

    async def report_offer_sent(self, id_or_custom_id: str, offer_id: str) -> Deal:
        """Report the Steam trade offer the seller sent (`deal_steam_offer_sent`; seller, MANUAL
        delivery). A mutation: sent once, never retried.

        A reference that is not UUID-shaped is sent as the custom id. A UUID-shaped one could be
        the id or a UUID custom id, and the mutation must not be sent twice to find out, so it is
        resolved with `get()` first and the mutation is sent once with the id found; a
        `NotFoundError` from that resolution means nothing was sent. When the deal found is not the
        one referenced (its id differs, and so does its custom id) a `DecodeError` is raised and
        nothing is sent. `offer_id` is the Steam trade offer id.
        """
        id, custom_id = await self._mutation_target(id_or_custom_id)
        answer = await self._generated.deal_steam_offer_sent(offer_id, custom_id=custom_id, id=id)
        return map_deal(answer.deal_steam_offer_sent, ("deal_steam_offer_sent",))

    async def cancel_sending_offer(
        self, id_or_custom_id: str, reason: OfferCancelReason, comment: str
    ) -> Deal:
        """The seller cancels sending the Steam offer (`deal_cancel_sending_offer`; seller, MANUAL
        delivery) and gets the archived deal. Give the true reason: a wrong one can lead to
        sanctions. A mutation: sent once, never retried; the reference is resolved as in
        `report_offer_sent()`.

        `comment` is at most 255 characters of `a-z A-Z 0-9 space _ -`. Raises `ValueError`,
        before anything is sent, for a comment that breaks that rule, an empty reference, or a
        `reason` the API schema does not accept.
        """
        _check_comment(comment)
        wire_reason = wire_enum(MarketDealExternalCancelReason, reason)
        id, custom_id = await self._mutation_target(id_or_custom_id)
        answer = await self._generated.deal_cancel_sending_offer(
            comment, wire_reason, custom_id=custom_id, id=id
        )
        return map_archived_deal(answer.deal_cancel_sending_offer, ("deal_cancel_sending_offer",))

    async def hold_balance(self, currency: Currency) -> Money:
        """The balance held in deals in one currency (`deal_balance_hold`)."""
        answer = await self._generated.deal_balance_hold(wire_enum(Currency, currency))
        return money(answer.deal_balance_hold, ("deal_balance_hold",))

    async def hold_balances(self) -> list[Money]:
        """The balances held in deals, one entry per currency (`deal_balances_hold`)."""
        answer = await self._generated.deal_balances_hold()
        return map_list(answer.deal_balances_hold, money, ("deal_balances_hold",))

    async def wait_for(
        self,
        id_or_custom_id: str,
        until: DealPredicate,
        *,
        timeout: float | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        live: AsyncLiveSession | None = None,
    ) -> DealState:
        """Poll the status until `until` accepts it and return that state. Ready-made conditions:
        `whitemarket.deals.Until`.

        The first poll is immediate; between polls the call sleeps `poll_interval` seconds, or
        less when the timeout ends sooner (then it polls once more at the deadline). `timeout` is
        in seconds of elapsed time (a monotonic clock: a change of the system clock does not move
        the deadline), `None` waits without limit and `0` polls exactly once.
        `ValueError` is raised, before any request, for an empty reference, a `poll_interval` that
        is not finite and above 0, or a `timeout` that is neither `None` nor finite and 0 or more.
        `DealWaitTimeoutError` (with the last state seen) is raised when the timeout elapses first.

        Works for buyer and seller deals: `deal_buyer_statuses` answers for purchases only, so
        when it does not report the deal the wait reads it with `get()` (`deal_item`, then the
        archive) and keeps doing so, one request per poll. A deal the server does not report yet (a
        new deal may need a moment to become visible) counts as "not yet", and so does a state
        `until` rejects, including one with an unknown status. Every `Until` predicate also matches
        a final status, so a wait never outlives a failed or reversed deal; check the status of the
        returned state.

        With `live` (a live session whose personal channel is subscribed; the caller owns it) the
        call does not sleep between polls: it waits in `live.wait_for_deal_event` instead and polls
        early when a deal event of the waited deal arrives (an event is a hint, never the state),
        yet two polls begin at least `MIN_EVENT_POLL_GAP` (1 s) apart: a burst of events is one
        poll per second at most.
        A session that is already closed returns at once and the rest of the interval is slept. An
        exception from a live handler or a terminal live failure propagates. The timeout works as
        without `live`.

        The timeout bounds the waiting between polls; a poll already in flight (its query retries
        per SDK_SPEC 1.4 and the request timeout) may finish after it, so the call can return or
        raise up to one poll's duration after the timeout.
        """
        _check_wait_args(id_or_custom_id, poll_interval, timeout)

        start = self._clock()
        via_get = False
        last: DealState | None = None  # the last state seen, kept for the timeout error
        while True:
            polled_at = self._clock()
            seen, via_get = await self._read_state(id_or_custom_id, via_get)
            if seen is not None:
                last = seen
                if until(seen):
                    return seen
            pause = poll_interval
            if timeout is not None:
                remaining = timeout - (self._clock() - start)
                if remaining <= 0:
                    raise DealWaitTimeoutError(id_or_custom_id, last, timeout)
                pause = min(poll_interval, remaining)
            if live is None:
                await self._sleeper(pause)
            else:
                await self._wait_live(live, pause, _event_deal_id(id_or_custom_id, last), polled_at)

    async def _read_state(
        self, id_or_custom_id: str, via_get: bool
    ) -> tuple[DealState | None, bool]:
        """One poll of `wait_for`: the state seen (None: not visible yet) and whether the next poll
        reads with `get()`. `deal_buyer_statuses` goes first until it fails to report the deal; the
        deal is then read with `get()` from then on."""
        seen: DealState | None = None
        if not via_get:
            seen = next(iter((await self.statuses([id_or_custom_id])).values()), None)
            via_get = seen is None
        if via_get:
            with contextlib.suppress(NotFoundError):  # not visible yet: keep polling
                seen = deal_state_of(await self.get(id_or_custom_id))
        return seen, via_get

    async def _wait_live(
        self, live: AsyncLiveSession, seconds: float, deal_id: str, polled_at: float
    ) -> None:
        """Wait up to `seconds` for a deal event of `deal_id` and return when it comes, but not
        before `MIN_EVENT_POLL_GAP` seconds have passed since the poll began (`polled_at`) and
        never past the `seconds`.

        Without an event the session returns `None` after the full wait, or at once when it is
        closed: the rest of the interval is slept then, instead of spinning."""
        end = self._clock() + seconds
        if await live.wait_for_deal_event(deal_id, seconds) is not None:
            now = self._clock()
            hold = min(polled_at + MIN_EVENT_POLL_GAP, end) - now
            if hold > 0:
                await self._sleeper(hold)
            return
        left = end - self._clock()
        if left > 0:
            await self._sleeper(left)

    async def _mutation_target(
        self, id_or_custom_id: str
    ) -> tuple[str | UnsetType, str | UnsetType]:
        """`(id, custom_id)` a mutation is sent with, one of them `UNSET`: the custom id of a plain
        reference, the id found by `get()` for a UUID-shaped one."""
        _require_reference(id_or_custom_id)
        if not is_uuid(id_or_custom_id):
            return UNSET, id_or_custom_id
        deal = await self.get(id_or_custom_id)
        if deal.id.lower() != id_or_custom_id.lower() and deal.custom_id != id_or_custom_id:
            raise DecodeError(
                "the server returned a different deal than the one requested", ("deal_item", "id")
            )
        return deal.id, UNSET

    async def _lookup(self, *, id: str | None = None, custom_id: str | None = None) -> Deal:
        """`deal_item`, then `deal_history_item` on not-found, under one key."""
        key_id = unset_if_none(id)
        key_custom = unset_if_none(custom_id)
        try:
            return await find_live_deal(self._generated, custom_id=key_custom, id=key_id)
        except NotFoundError:
            pass  # Not a deal in progress: the archive is next.
        return await find_archived_deal(self._generated, custom_id=key_custom, id=key_id)


def _match_requested(requested: Sequence[str], states: Sequence[DealState]) -> dict[str, DealState]:
    """The states keyed by the requested string (see `statuses()` for the matching rules)."""
    by_id: dict[str, DealState] = {}
    by_folded_id: dict[str, DealState] = {}
    by_custom_id: dict[str, DealState] = {}
    for state in states:
        by_id[state.id] = state
        if is_uuid(state.id):
            by_folded_id[state.id.lower()] = state
        if state.custom_id is not None:
            by_custom_id[state.custom_id] = state
    found: dict[str, DealState] = {}
    for key in requested:
        by_key = by_folded_id.get(key.lower()) if is_uuid(key) else by_id.get(key)
        match = by_custom_id.get(key) if by_key is None else by_key
        if match is not None:
            found[key] = match
    return found


def _check_wait_args(id_or_custom_id: str, poll_interval: float, timeout: float | None) -> None:
    _require_reference(id_or_custom_id)
    if not (math.isfinite(poll_interval) and poll_interval > 0):
        raise ValueError("poll_interval must be a finite number of seconds above 0")
    if timeout is not None and not (math.isfinite(timeout) and timeout >= 0):
        raise ValueError("timeout must be None or a finite number of seconds, 0 or more")


def _event_deal_id(reference: str, last: DealState | None) -> str:
    """The deal id live events are matched to: the server's spelling once a state was seen, else
    the reference (lower-cased when it is UUID-shaped, the usual spelling)."""
    if last is not None:
        return last.id
    return reference.lower() if is_uuid(reference) else reference


def _require_reference(id_or_custom_id: str) -> None:
    require_text(id_or_custom_id, "the deal id or custom_id", non_empty=True)


def _status_filter(statuses: Sequence[DealStatus] | None) -> list[MarketDealStatus] | UnsetType:
    """No variable at all (not `null`) when no filter is given."""
    return UNSET if statuses is None else wire_enums(MarketDealStatus, statuses) or []


def _check_comment(comment: str) -> None:
    if len(comment) > MAX_COMMENT_LENGTH:
        raise ValueError(f"the cancel comment is longer than {MAX_COMMENT_LENGTH} characters")
    if _COMMENT.fullmatch(comment) is None:
        raise ValueError(
            'the cancel comment may contain only the characters a-z, A-Z, 0-9, space, "_" and "-"'
        )
