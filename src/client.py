from __future__ import annotations

from typing import Any

import httpx

from models import RawProduct
from settings import Settings


class SimpleShopError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class SimpleShopClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = str(settings.simpleshop_base_url).rstrip("/") + "/"
        self._client = self._make_client()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._client.request(
            method,
            path.lstrip("/"),
            params=params,
            json=json,
        )
        return self._parse_response(response)

    async def download_url(self, url: str) -> tuple[bytes, str | None]:
        response = await self._client.get(url, follow_redirects=True)
        return self._parse_download_response(response)

    def _make_client(self) -> httpx.AsyncClient:
        auth = httpx.BasicAuth(
            self._settings.simpleshop_login,
            self._settings.simpleshop_api_key.get_secret_value(),
        )
        timeout = httpx.Timeout(self._settings.simpleshop_timeout_seconds)
        return httpx.AsyncClient(
            base_url=self._base_url,
            auth=auth,
            timeout=timeout,
            follow_redirects=False,
        )

    def _parse_download_response(self, response: httpx.Response) -> tuple[bytes, str | None]:
        if response.status_code >= 400:
            raise SimpleShopError(
                "SimpleShop file download failed",
                status_code=response.status_code,
                payload=response.text,
            )
        return response.content, response.headers.get("content-type")

    def _parse_response(self, response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        payload: Any
        if "application/json" in content_type:
            try:
                payload = response.json()
            except ValueError as exc:
                raise SimpleShopError(
                    "SimpleShop returned invalid JSON",
                    status_code=response.status_code,
                ) from exc
        else:
            payload = response.text

        if response.status_code >= 400:
            message = "SimpleShop API request failed"
            if isinstance(payload, dict):
                message = str(payload.get("message") or message)
            raise SimpleShopError(message, status_code=response.status_code, payload=payload)
        return payload

    async def health_check(self) -> dict[str, Any]:
        return await self.request("GET", "test/")

    async def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        return await self.request("GET", f"invoice/{invoice_id}/")

    async def search_invoices(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        payload = await self.request("GET", "invoice/", params=_clean_params(params))
        if not isinstance(payload, list):
            raise SimpleShopError(
                "SimpleShop invoice search did not return a list",
                payload=payload,
            )
        return payload

    async def list_products(self) -> list[RawProduct]:
        payload = await self.request("GET", "product/")
        return [RawProduct.model_validate(product) for product in _expect_list(payload, "products")]

    async def get_product(self, product_id: int) -> RawProduct:
        payload = await self.request("GET", f"product/{product_id}/")
        if not isinstance(payload, dict):
            raise SimpleShopError(
                "SimpleShop product detail endpoint did not return an object",
                payload=payload,
            )
        return RawProduct.model_validate(payload)

    async def who_bought_product(
        self,
        product_id: int,
        strict: int | None = None,
    ) -> dict[str, Any]:
        params = {"strict": strict} if strict is not None else None
        payload = await self.request(
            "GET",
            f"export/who-bought/product/{product_id}/",
            params=params,
        )
        if not isinstance(payload, dict) or "csv" not in payload:
            raise SimpleShopError(
                "SimpleShop buyer export did not return a CSV payload",
                payload=payload,
            )
        return payload

    async def payment_methods(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "settings/payment-method/")
        return _expect_list(payload, "payment methods")

    async def number_series(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "settings/number-series/")
        return _expect_list(payload, "number series")

    async def tags(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "settings/tags/")
        return _expect_list(payload, "tags")


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


def _expect_list(payload: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise SimpleShopError(f"SimpleShop {label} endpoint did not return a list", payload=payload)
    return payload
