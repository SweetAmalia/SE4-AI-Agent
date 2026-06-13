"""
Boodschappen Agent v6 — T6_test.py

Gelijk aan T5_test.py, maar gebruikt Google Gemini (gratis tier via
Google AI Studio) voor de intent-extractie in plaats van een lokaal
LM Studio-model. Gemini heeft een echte gratis API-laag, ideaal voor dit
project. De rest van de pijplijn (matching, prijsvergelijking, locatie,
advies) is identiek aan T5.

Gratis API-key halen: https://aistudio.google.com/app/apikey
(let op: dit is een ANDERE key dan je Google Maps-key)

Onderliggende verbeteringen (uit T3/T5):
  A. Betere _beste_match (woordgrens-match, meervoud-tolerantie, ruispenalty)
  B. Betere extractie-prompt (beschrijvende woorden behouden)
  C. Gematchte producten onder de prijsvergelijking
  D. Locatie-hallucinatie afgevangen (alleen vertrouwen als plaats in invoer staat)

.env.local (zelfde map als dit script):
    GOOGLE_GENAI_API_KEY=AIza...      (gratis, via AI Studio)
    GEMINI_MODEL=gemini-2.0-flash-lite (optioneel; standaard gemini-2.0-flash-lite)
    GOOGLE_MAPS_API_KEY=AIza...       (aparte key voor Maps)
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
import uuid
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from operator import add
from concurrent.futures import ThreadPoolExecutor

# Windows-console gebruikt standaard cp1252 en crasht op emoji's in het advies
if (hasattr(sys.stdout, "reconfigure")
        and sys.stdout.encoding
        and sys.stdout.encoding.lower() not in ("utf-8", "utf8")):
    sys.stdout.reconfigure(encoding="utf-8")

import requests
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

import googlemaps

# .env.local naast dit script laden, ongeacht vanuit welke map je het start
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local"))

# ---------- 0. Config ----------
GENAI_API_KEY = os.getenv("GOOGLE_GENAI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
GMAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
KETENS = ["Albert Heijn", "Jumbo", "Lidl", "Hoogvliet"]

# True  → kies de goedkoopste geldige match uit de zoekresultaten
# False → kies de beste titelovereenkomst (origineel gedrag)
KIES_GOEDKOOPSTE = True

gmaps = googlemaps.Client(key=GMAPS_KEY) if GMAPS_KEY else None


# ---------- 0a. Eigen AH-client (vervangt SupermarktConnector) ----------
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


ah = AHClient()

# Jumbo: het oude mobileapi.jumbo.com (SupermarktConnector) is geblokkeerd.
# We gebruiken de GraphQL API van de website; de apollographql-headers zijn verplicht.
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
jumbo_session = requests.Session()
jumbo_session.headers.update(JUMBO_HEADERS)

if not GENAI_API_KEY:
    raise RuntimeError(
        "GOOGLE_GENAI_API_KEY ontbreekt in .env.local — "
        "haal een gratis key via https://aistudio.google.com/app/apikey"
    )

llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    google_api_key=GENAI_API_KEY,
    temperature=0,
    timeout=120,
    max_tokens=2000,
)


# ---------- 1. Pydantic Schemas ----------
GELDIGE_EENHEDEN = {"stuks", "gram", "kg", "ml", "liter"}

EENHEID_ALIASSEN = {
    "g": "gram", "gr": "gram", "gram": "gram", "gewicht": "gram",
    "kg": "kg", "kilo": "kg", "kilogram": "kg",
    "ml": "ml", "milliliter": "ml",
    "l": "liter", "liter": "liter", "ltr": "liter",
    "stuks": "stuks", "stuk": "stuks", "st": "stuks",
    "pak": "stuks", "pakje": "stuks", "fles": "stuks", "blik": "stuks",
    "pot": "stuks", "zak": "stuks", "tros": "stuks", "bakje": "stuks",
    "netje": "stuks", "doos": "stuks", "bos": "stuks", "rol": "stuks",
}


class BoodschapItem(BaseModel):
    naam: str = Field(description="Productnaam zonder hoeveelheidswoorden.")
    aantal: float = Field(default=1, description="Numerieke hoeveelheid (13, 500, 1.5).")
    eenheid: str = Field(default="stuks", description="Eenheid: stuks, gram, kg, ml of liter.")

    @field_validator("eenheid", mode="before")
    @classmethod
    def _normaliseer_eenheid(cls, v) -> str:
        if not isinstance(v, str):
            return "stuks"
        return EENHEID_ALIASSEN.get(v.strip().lower(), "stuks")

    @property
    def is_gewicht(self) -> bool:
        return self.eenheid != "stuks"

    def label(self) -> str:
        if self.eenheid == "stuks":
            return f"{int(self.aantal)}x {self.naam}"
        return f"{self.aantal:g} {self.eenheid} {self.naam}"


class ExtractieResultaat(BaseModel):
    locatie: Optional[str] = Field(default=None, description="Stad/dorp/locatie. Null als niet genoemd.")
    items: list[BoodschapItem] = Field(description="Lijst producten met hoeveelheid en eenheid.")


# ---------- 2. State ----------
class AgentState(TypedDict, total=False):
    user_input: str
    extractie: Optional[dict]
    geocode: Optional[dict]
    winkels: Optional[dict]
    prijs_data: Optional[dict]
    advies: Optional[str]
    chat_history: Annotated[list[str], add]


# ---------- 3. Helpers ----------
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# [A] Verbeterd: woordgrens-match met tolerantie voor Nederlandse meervouden/verkleinwoorden.
# Voorkomt dat "pinda" matcht op "pindakaas" (4 extra tekens > drempel van 3).
_STOPWOORDEN = {
    "de", "het", "een", "van", "en", "in", "op", "met", "voor",
    "g", "kg", "ml", "l", "st", "x", "ca", "per",
}

# Multipack-patronen: "2x 12-pack", "12-pack", "4x250ml", "7+1", "24x", "multipack", "tray"
# Query noemt nooit een verpakkingsgrootte → zware penalty als titel er wél een heeft.
_MULTIPACK_RE = re.compile(
    r"\b\d+[\s\-]?pack\b"          # 12-pack, 4 pack, 24pack
    r"|\bmultipack\b"
    r"|\btray\b"
    r"|\b\d+\s*\+\s*\d+\b"         # 7+1, 5 + 1 (bonusverpakking)
    r"|\b(?:[2-9]|\d{2,})\s*x(?!\w)"   # 2x, 24x, 15 x (maar niet "1x" of "extra")
    r"|\b(?:[2-9]|\d{2,})\s*x\d",      # 4x250ml (x direct gevolgd door cijfer)
    re.IGNORECASE,
)


def _woord_match(query_woord: str, titel_woord: str) -> bool:
    """Geeft True als twee woorden als hetzelfde product-woord beschouwd worden.

    Tolerantie van ≤3 tekens aan het einde dekt:
      - meervoud:        balletje  ↔ balletjes   (+2)
      - verkleinwoord:   brood     ↔ broodje      (+2)
    Maar NIET:
      - pinda ↔ pindakaas (+4) → False
      - melk  ↔ melkpoeder (+6) → False
    """
    if query_woord == titel_woord:
        return True
    if titel_woord.startswith(query_woord) and len(titel_woord) - len(query_woord) <= 3:
        return True
    if query_woord.startswith(titel_woord) and len(query_woord) - len(titel_woord) <= 3:
        return True
    return False


def _beste_match(producten: list[dict], query: str, prijs_fn=None) -> Optional[dict]:
    """Kies het best passende product.

    Scoring per product:
      +1  per query-woord dat als heel woord in de titel voorkomt
      -0.2 per titel-woord dat niet overeenkomt met een query-woord (ruis)
      -5  als de titel een multipack-indicator bevat (bijv. "2x 12-pack")
          en de query dat niet doet — voorkomt dat "13x Red Bull" een
          24-blikjes-pack pakt in plaats van een los blikje.
    """
    if not producten:
        return None

    query_woorden = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    query_heeft_multipack = bool(_MULTIPACK_RE.search(query))

    def score(p: dict) -> float:
        titel = (p.get("title") or "")
        titel_woorden = re.findall(r"\w+", titel.lower())

        hits = sum(
            1 for qw in query_woorden
            if any(_woord_match(qw, tw) for tw in titel_woorden)
        )
        ruis = sum(
            1 for tw in titel_woorden
            if tw not in _STOPWOORDEN
            and len(tw) > 2
            and not any(_woord_match(qw, tw) for qw in query_woorden)
        )
        multipack_penalty = (
            0 if query_heeft_multipack
            else (-5 if _MULTIPACK_RE.search(titel) else 0)
        )
        return hits - ruis * 0.2 + multipack_penalty

    sco = [(score(p), i, p) for i, p in enumerate(producten)]
    sco.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    best_score = sco[0][0]

    if best_score <= 0:
        # Geen enkel product matcht goed; pak dan het minst slechte
        # (sco is gesorteerd, dus multipack-penalties tellen nog steeds mee)
        return sco[0][2]

    kandidaten = [p for s, _, p in sco if s > 0]

    if KIES_GOEDKOOPSTE and prijs_fn is not None:
        return min(kandidaten, key=lambda p: prijs_fn(p) or float("inf"))
    return kandidaten[0]


def _ah_prijs(p: dict) -> float:
    try:
        return float(p.get("currentPrice") or p.get("priceBeforeBonus") or 0)
    except (TypeError, ValueError):
        return float("inf")


def _jumbo_prijs(p: dict) -> float:
    try:
        prices = p["prices"]
        amount = prices.get("promoPrice") or prices.get("price")
        return int(amount) / 100.0
    except (KeyError, TypeError, ValueError):
        return float("inf")


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _ah_search(query: str) -> Optional[dict]:
    producten = ah.search_products(query=query, size=5, page=0)
    return _beste_match(producten, query, prijs_fn=_ah_prijs)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _jumbo_search(query: str) -> Optional[dict]:
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
    res = jumbo_session.post(JUMBO_GRAPHQL_URL, json=payload, timeout=15)
    res.raise_for_status()
    try:
        producten = res.json()["data"]["searchProducts"]["products"]
        return _beste_match(producten[:10], query, prijs_fn=_jumbo_prijs)
    except (KeyError, IndexError, TypeError):
        return None


def _safe_ah_price(product: Optional[dict]) -> tuple[float, bool]:
    if not product:
        return 0.0, False
    prijs = product.get("currentPrice") or product.get("priceBeforeBonus") or 0.0
    try:
        prijs = float(prijs)
    except (TypeError, ValueError):
        return 0.0, False
    return prijs, prijs > 0


def _safe_jumbo_price(product: Optional[dict]) -> tuple[float, bool]:
    if not product:
        return 0.0, False
    try:
        prices = product["prices"]
        amount = prices.get("promoPrice") or prices.get("price")
        prijs = round(int(amount) / 100.0, 2)
        return prijs, prijs > 0
    except (KeyError, TypeError, ValueError):
        return 0.0, False


def _zoek_beide_winkels(naam: str) -> tuple[Optional[dict], Optional[dict]]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        ah_future = pool.submit(_ah_search, naam)
        jumbo_future = pool.submit(_jumbo_search, naam)
        try:
            ah_product = ah_future.result()
        except Exception as e:
            logger.warning(f"AH definitief gefaald voor '{naam}': {e}")
            ah_product = None
        try:
            jumbo_product = jumbo_future.result()
        except Exception as e:
            logger.warning(f"Jumbo definitief gefaald voor '{naam}': {e}")
            jumbo_product = None
    return ah_product, jumbo_product


def _hoort_bij_keten(plek_naam: str, keten: str) -> bool:
    pn = plek_naam.lower()
    if keten == "Albert Heijn":
        return "albert heijn" in pn or pn.startswith("ah ") or pn == "ah"
    return keten.lower() in pn


def _dichtstbijzijnde_filiaal(keten: str, lat: float, lon: float) -> Optional[dict]:
    try:
        res = gmaps.places_nearby(location=(lat, lon), keyword=keten, rank_by="distance")
        for plek in res.get("results", []):
            if not _hoort_bij_keten(plek["name"], keten):
                continue
            loc = plek["geometry"]["location"]
            return {
                "naam": plek["name"],
                "adres": plek.get("vicinity", "?"),
                "afstand_km": round(_haversine_km(lat, lon, loc["lat"], loc["lng"]), 1),
            }
        return None
    except Exception as e:
        logger.warning(f"Places faalde voor '{keten}': {e}")
        return None


# ---------- 4. Nodes ----------
def node_parse_input(state: AgentState) -> AgentState:
    logger.info("Node 1 — intent extractie")
    text = state.get("user_input", "")

    # [B] Verbeterde prompt: beschrijvende woorden expliciet bewaard,
    # alleen verpakkings-/containerwoorden worden verwijderd.
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Jij bent een strenge data-extractor voor een supermarkt-API. "
         "Geef ALLEEN een geldig JSON-object terug, zonder uitleg of markdown. "
         "Maak het JSON-object af, ook bij lange lijsten.\n\n"
         "Formaat: {{\"locatie\": \"stad of null\", \"items\": [{{\"naam\": \"productnaam\", \"aantal\": 1, \"eenheid\": \"stuks\"}}]}}\n\n"
         "Regels:\n"
         "- 'eenheid' is een van: stuks, gram, kg, ml, liter\n"
         "- Telbare producten (bananen, broden, blikjes): eenheid=stuks, aantal=hoeveel stuks\n"
         "- Gewicht/volume (500 gram gehakt, 1.5 liter melk): aantal=hoeveelheid, eenheid=gewichtseenheid\n"
         "- Verwijder ALLEEN verpakkings- en containerwoorden uit de naam: "
         "'pak', 'pakje', 'fles', 'blik', 'blikje', 'pot', 'zak', 'tros', 'bakje', 'netje', 'doos', 'bos', 'rol', 'flesje', 'potje'\n"
         "- Behoud ALTIJD beschrijvende woorden zoals: vegetarisch, biologisch, mager, halfvol, "
         "volkoren, light, naturel, gerookt, vers, diepvries, zout, ongezouten, wit, bruin, "
         "of andere eigenschappen die het product beschrijven\n"
         "- Schrijf productnamen in enkelvoud TENZIJ het merk of product altijd meervoud gebruikt\n"
         "- locatie is null als er geen plaatsnaam wordt genoemd\n\n"
         "Voorbeeld input: \"13 bananen, 500 gram gehakt, 6 redbull en een zak vegetarische balletjes in Delft\"\n"
         "Voorbeeld output: {{\"locatie\": \"Delft\", \"items\": ["
         "{{\"naam\": \"banaan\", \"aantal\": 13, \"eenheid\": \"stuks\"}}, "
         "{{\"naam\": \"gehakt\", \"aantal\": 500, \"eenheid\": \"gram\"}}, "
         "{{\"naam\": \"Red Bull\", \"aantal\": 6, \"eenheid\": \"stuks\"}}, "
         "{{\"naam\": \"vegetarische balletjes\", \"aantal\": 1, \"eenheid\": \"stuks\"}}]}}"),
        ("user", "{input}"),
    ])

    max_pogingen = 5
    for poging in range(1, max_pogingen + 1):
        try:
            response = (prompt | llm).invoke({"input": text})
            raw = response.content.strip()
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                raise ValueError(
                    f"Geen volledige JSON in LLM-output (mogelijk afgekapt). "
                    f"Laatste 120 tekens: ...{raw[-120:]!r}"
                )
            data = json.loads(json_match.group(0))
            resultaat = ExtractieResultaat(**data)

            print("\n📋 Dit heb ik begrepen:")
            for item in resultaat.items:
                print(f"   • {item.label()}")
            if resultaat.locatie:
                print(f"   📍 Locatie genoemd: {resultaat.locatie}")
            print()

            logger.success(f"Extractie OK: locatie={resultaat.locatie}, items={[i.label() for i in resultaat.items]}")
            return {"extractie": resultaat.model_dump()}
        except Exception as e:
            fout = str(e)
            is_quota = "RESOURCE_EXHAUSTED" in fout or "429" in fout
            if is_quota and poging < max_pogingen:
                wacht = 2 ** poging  # 2, 4, 8, 16 seconden
                logger.warning(f"Quota overschreden (poging {poging}/{max_pogingen}), wacht {wacht}s...")
                time.sleep(wacht)
            else:
                logger.error(f"LLM parsing faalde na {poging} poging(en): {e}")
                return {"extractie": {"locatie": None, "items": []}}


def node_locatie(state: AgentState) -> AgentState:
    """Locatie uit tekst geocoderen, anders automatisch bepalen via Geolocation API."""
    if not gmaps:
        logger.warning("Geen GOOGLE_MAPS_API_KEY — locatiebepaling overgeslagen")
        return {"geocode": None}

    locatie = state["extractie"].get("locatie")
    user_text = state.get("user_input", "")

    # Bescherm tegen een gehallucineerde locatie: een zwak LLM echoot soms de
    # 'Delft' uit het prompt-voorbeeld, ook als de gebruiker geen plaats noemt.
    # Vertrouw een locatie alleen als die ook echt in de invoer voorkomt;
    # anders → automatische bepaling via de Geolocation API.
    if locatie and locatie.lower() not in user_text.lower():
        logger.warning(
            f"Locatie '{locatie}' komt niet voor in de invoer — waarschijnlijk "
            f"gehallucineerd; val terug op automatische locatiebepaling"
        )
        locatie = None

    try:
        if locatie:
            logger.info(f"Node 2 — geocoding '{locatie}'")
            results = gmaps.geocode(locatie, region="nl")
            if not results:
                logger.warning(f"Geen geocode-resultaat voor '{locatie}'")
                return {"geocode": None}
            loc = results[0]["geometry"]["location"]
            geocode = {
                "lat": loc["lat"], "lon": loc["lng"],
                "formatted_address": results[0]["formatted_address"],
                "bron": "tekst",
            }
        else:
            logger.info("Node 2 — automatische locatiebepaling (Geolocation API)")
            geo = gmaps.geolocate()
            lat, lon = geo["location"]["lat"], geo["location"]["lng"]
            adres = "onbekend adres"
            try:
                rev = gmaps.reverse_geocode((lat, lon))
                if rev:
                    adres = rev[0]["formatted_address"]
            except Exception as e:
                logger.warning(f"Reverse geocode faalde: {e}")
            geocode = {"lat": lat, "lon": lon, "formatted_address": adres, "bron": "automatisch"}

        logger.success(f"Locatie ({geocode['bron']}): {geocode['formatted_address']}")
        return {"geocode": geocode}
    except Exception as e:
        logger.error(f"Locatiebepaling faalde: {e}")
        return {"geocode": None}


def node_winkels(state: AgentState) -> AgentState:
    """Dichtstbijzijnde filiaal per keten (parallel, geen afstandslimiet)."""
    geocode = state.get("geocode")
    if not geocode:
        logger.warning("Geen locatie — winkels zoeken overgeslagen")
        return {"winkels": None}

    logger.info("Node 3 — dichtstbijzijnde supermarkten zoeken")
    lat, lon = geocode["lat"], geocode["lon"]

    with ThreadPoolExecutor(max_workers=len(KETENS)) as pool:
        resultaten = list(pool.map(lambda k: _dichtstbijzijnde_filiaal(k, lat, lon), KETENS))

    winkels = dict(zip(KETENS, resultaten))
    for keten, w in winkels.items():
        if w:
            logger.success(f"{keten}: {w['naam']} op {w['afstand_km']} km ({w['adres']})")
        else:
            logger.warning(f"{keten}: geen filiaal gevonden")
    return {"winkels": winkels}


def node_vraag_verduidelijking(state: AgentState) -> AgentState:
    vraag = "Ik heb geen boodschappen herkend. Kun je opnieuw zeggen welke producten je nodig hebt?"
    return {"advies": vraag, "chat_history": [f"Agent: {vraag}"]}


def node_vergelijk_prijzen(state: AgentState) -> AgentState:
    logger.info("Node 4 — prijzen vergelijken (AH + Jumbo)")
    items = [BoodschapItem(**i) for i in state["extractie"]["items"]]

    ah_totaal = 0.0
    jumbo_totaal = 0.0
    details = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        zoekresultaten = list(pool.map(lambda i: _zoek_beide_winkels(i.naam), items))

    for item, (ah_product, jumbo_product) in zip(items, zoekresultaten):
        multiplier = item.aantal if item.eenheid == "stuks" else 1

        ah_stuk, ah_ok = _safe_ah_price(ah_product)
        ah_prijs = round(ah_stuk * multiplier, 2)

        jumbo_stuk, jumbo_ok = _safe_jumbo_price(jumbo_product)
        jumbo_prijs = round(jumbo_stuk * multiplier, 2)

        ah_totaal += ah_prijs
        jumbo_totaal += jumbo_prijs

        details.append({
            "label": item.label(),
            "is_gewicht": item.is_gewicht,
            "ah_prijs": ah_prijs,
            "ah_beschikbaar": ah_ok,
            "ah_match": (ah_product or {}).get("title"),
            "jumbo_prijs": jumbo_prijs,
            "jumbo_beschikbaar": jumbo_ok,
            "jumbo_match": (jumbo_product or {}).get("title"),
        })
        ah_match_title = (ah_product or {}).get("title", "geen match")
        jumbo_match_title = (jumbo_product or {}).get("title", "geen match")
        logger.debug(f"{item.label()}: AH €{ah_prijs:.2f} ({'✓' if ah_ok else '✗'}) → {ah_match_title}")
        logger.debug(f"{item.label()}: Jumbo €{jumbo_prijs:.2f} ({'✓' if jumbo_ok else '✗'}) → {jumbo_match_title}")

    return {"prijs_data": {
        "ah_totaal": round(ah_totaal, 2),
        "jumbo_totaal": round(jumbo_totaal, 2),
        "details": details,
    }}


def node_advies(state: AgentState) -> AgentState:
    extractie = state["extractie"]
    geocode = state.get("geocode")
    winkels = state.get("winkels") or {}
    prijzen = state["prijs_data"]
    ah_tot, jumbo_tot = prijzen["ah_totaal"], prijzen["jumbo_totaal"]

    regels = []
    if geocode:
        bron = "automatisch bepaald" if geocode["bron"] == "automatisch" else "uit je bericht"
        regels.append(f"📍 Locatie ({bron}): {geocode['formatted_address']}")
    regels.append("")

    if ah_tot > 0 or jumbo_tot > 0:
        regels.append("💶 Prijsvergelijking (AH vs Jumbo):")
        for d in prijzen["details"]:
            ah_str = f"€{d['ah_prijs']:.2f}" if d["ah_beschikbaar"] else "—"
            jb_str = f"€{d['jumbo_prijs']:.2f}" if d["jumbo_beschikbaar"] else "—"
            opm = "  (prijs per verpakking)" if d["is_gewicht"] else ""
            regels.append(f"  • {d['label']:28s} AH {ah_str:>8s}  |  Jumbo {jb_str:>8s}{opm}")
            regels.append(f"      AH:    {d['ah_match'] or 'geen match'}")
            regels.append(f"      Jumbo: {d['jumbo_match'] or 'geen match'}")
        regels.append(f"  Totaal: AH €{ah_tot:.2f}  |  Jumbo €{jumbo_tot:.2f}")
    else:
        regels.append("⚠️ Geen prijzen gevonden bij AH of Jumbo.")
    regels.append("")

    regels.append("🏪 Dichtstbijzijnde supermarkten:")
    gevonden = {k: w for k, w in winkels.items() if w}
    for keten, w in winkels.items():
        if w:
            prijs_info = ""
            if keten == "Albert Heijn" and ah_tot > 0:
                prijs_info = f" — lijst: €{ah_tot:.2f}"
            elif keten == "Jumbo" and jumbo_tot > 0:
                prijs_info = f" — lijst: €{jumbo_tot:.2f}"
            elif keten in ("Lidl", "Hoogvliet"):
                prijs_info = " — geen prijsdata beschikbaar"
            regels.append(f"  • {keten:13s} {w['afstand_km']:4.1f} km — {w['adres']}{prijs_info}")
        else:
            regels.append(f"  • {keten:13s} geen filiaal gevonden")
    regels.append("")

    adviezen = []
    if ah_tot > 0 and jumbo_tot > 0:
        goedkoopste = "Jumbo" if jumbo_tot < ah_tot else "Albert Heijn"
        verschil = abs(ah_tot - jumbo_tot)
        if verschil > 0.01:
            w = gevonden.get(goedkoopste)
            afstand = f" ({w['afstand_km']} km)" if w else " (geen filiaal gevonden)"
            adviezen.append(f"🏆 Goedkoopste: {goedkoopste}{afstand} — bespaart €{verschil:.2f}")
        else:
            adviezen.append("⚖️ AH en Jumbo zijn even duur voor deze lijst")
    if gevonden:
        dichtstbij = min(gevonden.items(), key=lambda kw: kw[1]["afstand_km"])
        adviezen.append(f"📏 Dichtstbijzijnde: {dichtstbij[0]} op {dichtstbij[1]['afstand_km']} km")
    regels.extend(adviezen)

    advies = "\n".join(regels)
    return {"advies": advies, "chat_history": [f"Agent: {advies}"]}


# ---------- 5. Routers ----------
def valideer_extractie(state: AgentState) -> Literal["compleet", "incompleet"]:
    e = state.get("extractie", {})
    return "compleet" if e.get("items") else "incompleet"


# ---------- 6. Graph ----------
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse_input", node_parse_input)
    g.add_node("locatie", node_locatie)
    g.add_node("winkels", node_winkels)
    g.add_node("vraag_verduidelijking", node_vraag_verduidelijking)
    g.add_node("vergelijk_prijzen", node_vergelijk_prijzen)
    g.add_node("advies", node_advies)

    g.add_edge(START, "parse_input")
    g.add_conditional_edges("parse_input", valideer_extractie, {
        "compleet": "locatie",
        "incompleet": "vraag_verduidelijking",
    })
    g.add_edge("locatie", "winkels")
    g.add_edge("winkels", "vergelijk_prijzen")
    g.add_edge("vergelijk_prijzen", "advies")
    g.add_edge("vraag_verduidelijking", END)
    g.add_edge("advies", END)

    return g.compile(checkpointer=MemorySaver())


app = build_graph()
config = {"configurable": {"thread_id": str(uuid.uuid4())}}


def vraag(tekst: str) -> None:
    """Stuur één bericht naar de agent en print het advies."""
    result = app.invoke({"user_input": tekst}, config)
    print(f"\n{result.get('advies')}\n")


def test_goedkoopste():
    """Test KIES_GOEDKOOPSTE op een paar representatieve gevallen."""
    print("\n=== TEST: _beste_match met KIES_GOEDKOOPSTE ===\n")

    ah_mock = [
        {"title": "Red Bull Energy Drink 250 ml",         "currentPrice": 1.49},
        {"title": "Red Bull Energy Drink 4-pack 4x250ml", "currentPrice": 4.79},
        {"title": "Red Bull The Tropical Edition 250 ml", "currentPrice": 1.59},
    ]
    jumbo_mock = [
        {"title": "Red Bull Energy Drink 250 ml",   "prices": {"price": 159, "promoPrice": None}},
        {"title": "Red Bull Tropical 250 ml",        "prices": {"price": 149, "promoPrice": None}},
        {"title": "Red Bull 24x 250 ml multipack",   "prices": {"price": 2999, "promoPrice": None}},
    ]

    cases = [
        ("Red Bull Tropical", ah_mock, _ah_prijs),
        ("Red Bull Tropical", jumbo_mock, _jumbo_prijs),
        ("Red Bull",          ah_mock,   _ah_prijs),
    ]

    for query, producten, prijs_fn in cases:
        resultaat = _beste_match(producten, query, prijs_fn=prijs_fn)
        titel = (resultaat or {}).get("title", "geen match")
        print(f"  query='{query}' → '{titel}'")

    print()


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "test":
        test_goedkoopste()
        _sys.exit(0)

    print("=== Supermarkt Vergelijker v6 (T6, Gemini) ===")
    print(f"LLM: Google {GEMINI_MODEL}")
    print(f"Google Maps: {'✓' if gmaps else '✗ (geen key)'}")
    print("Locatie wordt automatisch bepaald; noem een plaats om te overschrijven.")
    print("Typ 'stop' om af te sluiten.\n")

    while True:
        try:
            user_input = input("Jij: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("stop", "quit", "exit"):
            break
        vraag(user_input)
