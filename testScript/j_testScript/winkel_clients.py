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

# ---------- HOOGVLIET CONFIGURATIE & CLIENT ----------

HOOGVLIET_SEARCH_URL = "https://api.hoogvliet.com/v1/search"
HOOGVLIET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "Origin": "https://www.hoogvliet.com",
    "Referer": "https://www.hoogvliet.com/webshop",
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

_hoogvliet_session = requests.Session()
_hoogvliet_session.headers.update(HOOGVLIET_HEADERS)


def hoogvliet_search_products(query: str, size: int = 20) -> list[dict]:
    """Zoekt producten via het lichtere GET-endpoint van Hoogvliet."""
    # We sturen de parameters nu mee in de URL in plaats van een zware POST-payload
    url = f"https://api.hoogvliet.com/v1/search/products"
    params = {
        "searchTerm": query,
        "page": 0,
        "pageSize": size
    }
    
    try:
        res = _hoogvliet_session.get(url, params=params, timeout=15)
        res.raise_for_status()
        
        data = res.json()
        return data.get("products", []) or data.get("results", []) or []
    except Exception as e:
        logger.warning(f"Hoogvliet API-call faalde voor '{query}': {e}")
        return []


def hoogvliet_prijs(product: dict) -> Optional[float]:
    """Haalt de actuele prijs uit een Hoogvliet product-dict."""
    try:
        # Hoogvliet levert prijzen vaak direct als float of binnen een 'price' object
        price_data = product.get("price") or {}
        
        # Soms staat het direct in de root, soms in een genest object
        amount = product.get("currentPrice") or price_data.get("now") or product.get("salesPrice")
        
        if amount is not None:
            prijs = float(amount)
            return prijs if prijs > 0 else None
        return None
    except (TypeError, ValueError, KeyError):
        return None


# ---------- UNIFORME DATA WRAPPER (S3 BONUS) ----------

def normaliseer_api_resultaat(product: dict, winkel: str) -> Optional[dict]:
    """
    Mapt de unieke JSON-outputs van AH, Jumbo en Hoogvliet naar één 
    universeel formaat. Dit maakt je jbuild_index.py code veel schoner!
    """
    if winkel == "Albert Heijn":
        titel = product.get("title")
        prijs = ah_prijs(product)
        prod_id = f"ah:{product.get('webshopId')}"
    elif winkel == "Jumbo":
        titel = product.get("title")
        prijs = jumbo_prijs(product)
        # Jumbo heeft niet altijd direct een ID in deze specifieke query, 
        # genereer een hash op basis van de titel als fallback
        prod_id = f"jumbo:{hash(titel)}" if titel else None
    elif winkel == "Hoogvliet":
        titel = product.get("name") or product.get("title")
        prijs = hoogvliet_prijs(product)
        prod_id = f"hoogvliet:{product.get('id') or product.get('sku')}"
    elif winkel == "Lidl":
        titel = product.get("title") or product.get("name")
        prijs = lidl_prijs(product)
        prod_id = f"lidl:{product.get('id') or hash(titel)}"
    else:
        return None

    if not titel or not prijs:
        return None

    return {
        "id": prod_id,
        "winkel": winkel,
        "naam": titel,
        "prijs": prijs
    }

LIDL_SEARCH_URL = "https://www.lidl.nl/p/api/search"
LIDL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def lidl_search_products(query: str, size: int = 15) -> list[dict]:
    """Zoekt producten via de publieke API van Lidl NL."""
    params = {"q": query, "size": size}
    try:
        res = requests.get(LIDL_SEARCH_URL, params=params, headers=LIDL_HEADERS, timeout=10)
        res.raise_for_status()
        # Lidl nest de producten vaak onder een 'items' of 'products' key
        return res.json().get("items", []) or []
    except Exception as e:
        logger.warning(f"Lidl API faalde voor '{query}': {e}")
        return []

def lidl_prijs(product: dict) -> Optional[float]:
    """Haalt de prijs op uit het prijs-object van Lidl."""
    try:
        # Lidl API structuur maakt gebruik van een 'price' dict met een 'value' of 'amount'
        price_data = product.get("price", {})
        amount = price_data.get("value") or product.get("priceBeforeBonus")
        if amount:
            return float(amount)
        return None
    except (TypeError, ValueError):
        return None