"""Odoo XML-RPC connection management."""

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
                self.config.db, self.config.username, self.config.password, {}
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

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
    ) -> Any:
        """Call execute_kw on the Odoo object endpoint."""
        if self._object is None or self._uid is None:
            raise OdooConnectionError("Not connected. Call connect() first.")
        try:
            return self._object.execute_kw(
                self.config.db,
                self._uid,
                self.config.password,
                model,
                method,
                args,
                kwargs or {},
            )
        except xmlrpc.client.Fault as exc:
            raise OdooConnectionError(
                f"RPC fault on {model}.{method}: {exc.faultString}"
            ) from exc
        except TimeoutError as exc:
            raise OdooConnectionError(f"Timeout calling {model}.{method}") from exc
        except Exception as exc:
            raise OdooConnectionError(f"Error calling {model}.{method}: {exc}") from exc

    # -- convenience helpers used by tools --------------------------------

    def search_read(
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
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def search_count(self, model: str, domain: list) -> int:
        return self.execute_kw(model, "search_count", [domain])

    def read_group(
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
        return self.execute_kw(model, "read_group", [domain, fields, groupby], kwargs)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute_kw(model, "read", [ids], kwargs)

    def create(self, model: str, values: dict) -> int:
        return self.execute_kw(model, "create", [values])

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        return self.execute_kw(model, "write", [ids, values])

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.execute_kw(model, "unlink", [ids])

    def copy(self, model: str, record_id: int, default: dict | None = None) -> int:
        kwargs = {"default": default} if default else {}
        return self.execute_kw(model, "copy", [record_id], kwargs)

    def fields_get(
        self,
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        kwargs = {}
        if attributes:
            kwargs["attributes"] = attributes
        return self.execute_kw(model, "fields_get", [], kwargs)
