"""
Synapse Matrix appservice transaction server.

Accepts transaction callbacks from Synapse and forwards events into the bot.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Set

from aiohttp import web

logger = logging.getLogger(__name__)


EventCallback = Callable[[List[Dict[str, Any]]], Awaitable[int]]


class MatrixAppServiceServer:
    """HTTP server for Synapse appservice callbacks."""

    def __init__(
        self,
        host: str,
        port: int,
        hs_token: str,
        as_token: str,
        as_id: str,
        sender_localpart: str,
        event_callback: EventCallback,
    ) -> None:
        self.host = host
        self.port = port
        self.hs_token = hs_token
        self.as_token = as_token
        self.as_id = as_id
        self.sender_localpart = sender_localpart
        self.event_callback = event_callback

        self._processed_txn_ids: Set[str] = set()
        self._processed_txn_order: Deque[str] = deque()
        self._max_stored_txn_ids = 4096

        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._configure_routes()

    def _configure_routes(self) -> None:
        self._app.router.add_get("/healthz", self._handle_health)
        self._app.router.add_get(
            "/_matrix/app/v1/users/{userId}",
            self._handle_user_query,
        )
        self._app.router.add_get(
            "/_matrix/app/v1/rooms/{roomAlias}",
            self._handle_room_query,
        )
        self._app.router.add_put(
            "/_matrix/app/v1/transactions/{txnId}",
            self._handle_transaction,
        )

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
        await self._site.start()
        logger.info(f"Appservice HTTP server listening on {self.host}:{self.port}")

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("Appservice HTTP server stopped")

    def _request_token(self, request: web.Request) -> str:
        access_token = request.query.get("access_token")
        if access_token:
            return access_token

        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization.removeprefix("Bearer ").strip()

        return ""

    def _is_authorized(self, request: web.Request) -> bool:
        return self._request_token(request) == self.hs_token

    def _remember_txn_id(self, txn_id: str) -> None:
        if txn_id in self._processed_txn_ids:
            return

        self._processed_txn_ids.add(txn_id)
        self._processed_txn_order.append(txn_id)
        if len(self._processed_txn_order) > self._max_stored_txn_ids:
            evicted = self._processed_txn_order.popleft()
            self._processed_txn_ids.discard(evicted)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_user_query(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        _user_id = request.match_info["userId"]
        return web.json_response({})

    async def _handle_room_query(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        _room_alias = request.match_info["roomAlias"]
        return web.json_response({})

    async def _handle_transaction(self, request: web.Request) -> web.Response:
        if not self._is_authorized(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        txn_id = request.match_info["txnId"]
        if txn_id in self._processed_txn_ids:
            logger.debug(f"Duplicate transaction ignored: {txn_id}")
            return web.json_response({})

        try:
            payload = await request.json()
        except Exception:
            logger.error(f"Invalid JSON payload in transaction {txn_id}")
            return web.json_response({"error": "Invalid JSON payload"}, status=400)

        events = payload.get("events", [])
        if not isinstance(events, list):
            return web.json_response({"error": "events must be a list"}, status=400)

        processed = await self.event_callback(events)
        self._remember_txn_id(txn_id)
        logger.info(f"Processed transaction {txn_id} with {processed} events")
        return web.json_response({})
