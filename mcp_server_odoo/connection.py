"""Odoo XML-RPC connection management."""

import asyncio
import logging
import xmlrpc.client
from typing import Any

from .config import OdooConfig

logger = logging.getLogger(__name__)


class OdooConnectionError(Exception):
    """Connection or RPC failure."""


class OdooConnection:
    """Manages XML-RPC connection to Odoo."""

    def __init__(self, config: OdooConfig):
        self.config = config
        self._uid: int | None = None
        self._object: xmlrpc.client.ServerProxy | None = None
        self._common: xmlrpc.client.ServerProxy | None = None

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        """Create XML-RPC proxies and authenticate."""
        base = self.config.url
        self._common = xmlrpc.client.ServerProxy(
            f"{base}/xmlrpc/2/common", allow_none=True
        )
        self._object = xmlrpc.client.ServerProxy(
            f"{base}/xmlrpc/2/object", allow_none=True
        )
        # authenticate
        try:
            uid = self._common.authenticate(
                self.config.db,
                self.config.username,
                self.config.password,
                {"interactive": False},
            )
        except Exception as exc:
            raise OdooConnectionError(f"Authentication failed: {exc}") from exc
        if not uid:
            raise OdooConnectionError("Authentication failed: invalid credentials")
        self._uid = uid
        logger.info("Connected to Odoo as uid=%d on %s", uid, self.config.url)

    def disconnect(self) -> None:
        self._object = None
        self._common = None
        self._uid = None

    @property
    def uid(self) -> int:
        if self._uid is None:
            raise OdooConnectionError("Not connected")
        return self._uid

    # -- generic execute_kw wrapper ---------------------------------------

    def _rpc_call(self, model: str, method: str, args: list, kwargs: dict) -> Any:
        """Low-level XML-RPC call (no retry)."""
        return self._object.execute_kw(
            self.config.db,
            self._uid,
            self.config.password,
            model,
            method,
            args,
            kwargs,
        )

    def _execute_kw_sync(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ) -> Any:
        """Synchronous XML-RPC call with auto-reconnect on transport errors."""
        if self._object is None or self._uid is None:
            raise OdooConnectionError("Not connected. Call connect() first.")
        kw = kwargs or {}
        try:
            return self._rpc_call(model, method, args, kw)
        except xmlrpc.client.Fault as exc:
            # Application error from Odoo — no point reconnecting
            raise OdooConnectionError(
                f"RPC fault on {model}.{method}: {exc.faultString}"
            ) from exc
        except Exception:
            # Transport error — try reconnecting once
            pass
        try:
            logger.warning("Connection lost, reconnecting to Odoo...")
            self.connect()
            return self._rpc_call(model, method, args, kw)
        except xmlrpc.client.Fault as exc:
            raise OdooConnectionError(
                f"RPC fault on {model}.{method}: {exc.faultString}"
            ) from exc
        except TimeoutError as exc:
            raise OdooConnectionError(f"Timeout calling {model}.{method}") from exc
        except Exception as exc:
            raise OdooConnectionError(f"Error calling {model}.{method}: {exc}") from exc

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ) -> Any:
        """Call execute_kw without blocking the event loop."""
        return await asyncio.to_thread(
            self._execute_kw_sync, model, method, args, kwargs
        )

    # -- convenience helpers used by tools --------------------------------

    async def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if fields:
            kwargs["fields"] = fields
        if order:
            kwargs["order"] = order
        return await self.execute_kw(model, "search_read", [domain], kwargs)

    async def search_count(self, model: str, domain: list) -> int:
        return await self.execute_kw(model, "search_count", [domain])

    async def read_group(
        self,
        model: str,
        domain: list,
        fields: list[str],
        groupby: list[str],
        offset: int = 0,
        limit: int | None = None,
        orderby: str | None = None,
        lazy: bool = True,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"lazy": lazy, "offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if orderby:
            kwargs["orderby"] = orderby
        return await self.execute_kw(
            model, "read_group", [domain, fields, groupby], kwargs
        )

    async def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        return await self.execute_kw(model, "read", [ids], kwargs)

    async def create(self, model: str, values: dict) -> int:
        return await self.execute_kw(model, "create", [values])

    async def write(self, model: str, ids: list[int], values: dict) -> bool:
        return await self.execute_kw(model, "write", [ids, values])

    async def unlink(self, model: str, ids: list[int]) -> bool:
        return await self.execute_kw(model, "unlink", [ids])

    async def copy(
        self, model: str, record_id: int, default: dict | None = None
    ) -> int:
        kwargs = {"default": default} if default else {}
        return await self.execute_kw(model, "copy", [record_id], kwargs)

    async def fields_get(
        self,
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        kwargs = {}
        if attributes:
            kwargs["attributes"] = attributes
        return await self.execute_kw(model, "fields_get", [], kwargs)
