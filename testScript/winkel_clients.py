"""
Gedeelde winkel-clients voor AH en Jumbo.

Gebruikt door build_index.py (catalogus scrapen) en T4_test.py (live fallback).
Zelfde API-aanpak als T2/T3: AH mobile API met anonieme token, Jumbo GraphQL.
"""

from __future__ import annotations

import threading
from typing import Optional

import requests
from loguru import logger


class AHClient:
    """Praat direct met de AH mobile API met een anonieme token.

    De token verloopt na een paar uur; bij een 401 halen we automatisch
    een nieuwe op. Thread-safe zodat parallelle zoekopdrachten kunnen.
    """

    TOKEN_URL = "https://api.ah.nl/mobile-auth/v1/auth/token/anonymous"
    SEARCH_URL = "https://api.ah.nl/mobile-services/product/search/v2"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Appie/8.60.1",
            "Content-Type": "application/json",
            "X-Application": "AHWEBSHOP",
        })
        self._lock = threading.Lock()
        self._authenticate()

    def _authenticate(self) -> None:
        res = self._session.post(self.TOKEN_URL, json={"clientId": "appie"}, timeout=10)
        res.raise_for_status()
        token = res.json()["access_token"]
        self._session.headers["Authorization"] = f"Bearer {token}"
        logger.debug("AH: nieuwe anonieme token opgehaald")

    def search_products(self, query: str, size: int = 5, page: int = 0) -> list[dict]:
        params = {"query": query, "size": size, "page": page, "sortOn": "RELEVANCE"}
        res = self._session.get(self.SEARCH_URL, params=params, timeout=15)
        if res.status_code == 401:
            with self._lock:
                self._authenticate()
            res = self._session.get(self.SEARCH_URL, params=params, timeout=15)
        res.raise_for_status()
        return res.json().get("products", [])


JUMBO_GRAPHQL_URL = "https://www.jumbo.com/api/graphql"
JUMBO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.jumbo.com",
    "Referer": "https://www.jumbo.com/producten",
    "apollographql-client-name": "basket-web",
    "apollographql-client-version": "1.0.0",
}
JUMBO_SEARCH_QUERY = """
query SearchProducts($input: ProductSearchInput!) {
  searchProducts(input: $input) {
    products {
      title
      prices: price {
        price
        promoPrice
      }
    }
  }
}
"""

_jumbo_session = requests.Session()
_jumbo_session.headers.update(JUMBO_HEADERS)


def jumbo_search_products(query: str) -> list[dict]:
    payload = {
        "query": JUMBO_SEARCH_QUERY,
        "variables": {"input": {
            "searchTerms": query,
            "searchType": "keyword",
            "offSet": 0,
            "currentUrl": "",
            "previousUrl": "",
            "bloomreachCookieId": "",
        }},
    }
    res = _jumbo_session.post(JUMBO_GRAPHQL_URL, json=payload, timeout=15)
    res.raise_for_status()
    try:
        return res.json()["data"]["searchProducts"]["products"] or []
    except (KeyError, TypeError):
        return []


def ah_prijs(product: dict) -> Optional[float]:
    """Prijs uit een AH-product; None als die ontbreekt."""
    try:
        prijs = float(product.get("currentPrice") or product.get("priceBeforeBonus") or 0)
        return prijs if prijs > 0 else None
    except (TypeError, ValueError):
        return None


def jumbo_prijs(product: dict) -> Optional[float]:
    """Prijs uit een Jumbo-product (GraphQL geeft centen); None als die ontbreekt."""
    try:
        prices = product["prices"]
        amount = prices.get("promoPrice") or prices.get("price")
        prijs = round(int(amount) / 100.0, 2)
        return prijs if prijs > 0 else None
    except (KeyError, TypeError, ValueError):
        return None
