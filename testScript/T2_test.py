"""
Boodschappen Agent v4 — zonder SupermarktConnector

Nieuw t.o.v. v3 (T_Test.py):
  1. Eigen AH-client direct op de AH mobile API (api.ah.nl):
     - anonieme token via /mobile-auth/v1/auth/token/anonymous (clientId=appie)
     - zoeken via /mobile-services/product/search/v2
     - token wordt automatisch ververst bij een 401
     De oude SupermarktConnector (2020) is hiermee volledig vervangen;
     de ah.nl website-API is geen optie (Akamai bot-detectie → 403).
  2. Jumbo blijft via de GraphQL API van jumbo.com (zelfde als v3)
  3. max_tokens hoog genoeg voor lange boodschappenlijsten (400 kapte de JSON af)

.env (zelfde map als dit script):
    LM_STUDIO_BASE_URL=http://localhost:1234/v1
    LM_STUDIO_MODEL=google/gemma-4-e4b
    GOOGLE_MAPS_API_KEY=AIza...
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
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
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import googlemaps

# .env naast dit script laden, ongeacht vanuit welke map je het start
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------- 0. Config ----------
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")
GMAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
KETENS = ["Albert Heijn", "Jumbo", "Lidl", "Hoogvliet"]

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
            # Token verlopen → één keer verversen en opnieuw proberen
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

llm = ChatOpenAI(
    base_url=LM_STUDIO_BASE_URL,
    api_key="lm-studio",
    model=LM_STUDIO_MODEL,
    temperature=0.1,
    timeout=120,
    max_tokens=2000,  # genoeg voor lange lijsten; 400 kapte de JSON af bij ~20 items
)


# ---------- 1. Pydantic Schemas ----------
GELDIGE_EENHEDEN = {"stuks", "gram", "kg", "ml", "liter"}

# Alias → standaardeenheid. Onbekende of verpakkingswoorden vallen terug op "stuks".
EENHEID_ALIASSEN = {
    "g": "gram", "gr": "gram", "gram": "gram", "gewicht": "gram",
    "kg": "kg", "kilo": "kg", "kilogram": "kg",
    "ml": "ml", "milliliter": "ml",
    "l": "liter", "liter": "liter", "ltr": "liter",
    # verpakkingswoorden die het model soms als eenheid invult → tellen als stuks
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
        """Mapt aliassen/verpakkingswoorden naar een geldige eenheid; rest → stuks."""
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
    geocode: Optional[dict]          # {lat, lon, formatted_address, bron}
    winkels: Optional[dict]          # {keten: {naam, adres, afstand_km} | None}
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


def _beste_match(producten: list[dict], query: str) -> Optional[dict]:
    """Kies het product waarvan de titel de meeste woorden uit de zoekterm bevat.
    Zoek-APIs zetten soms een irrelevant (gesponsord) product bovenaan."""
    if not producten:
        return None
    woorden = query.lower().split()
    def score(p: dict) -> int:
        titel = (p.get("title") or "").lower()
        return sum(1 for w in woorden if w in titel)
    best = max(producten, key=score)
    return best if score(best) > 0 else producten[0]


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _ah_search(query: str) -> Optional[dict]:
    producten = ah.search_products(query=query, size=5, page=0)
    return _beste_match(producten, query)


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
        return _beste_match(producten[:10], query)
    except (KeyError, IndexError, TypeError):
        return None


def _safe_ah_price(product: Optional[dict]) -> tuple[float, bool]:
    """currentPrice is de (bonus)prijs van nu; priceBeforeBonus de normale prijs."""
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
        # GraphQL geeft centen als integer; promoPrice gaat voor als die er is
        amount = prices.get("promoPrice") or prices.get("price")
        prijs = round(int(amount) / 100.0, 2)
        logger.debug(f"Jumbo match '{product.get('title')}' → €{prijs:.2f}")
        return prijs, prijs > 0
    except (KeyError, TypeError, ValueError) as e:
        logger.debug(f"Jumbo price parse mislukt: {e} | raw: {product}")
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
    """Places matcht keywords losjes (zoekt 'Jumbo' → vindt soms AH). Check de naam."""
    pn = plek_naam.lower()
    if keten == "Albert Heijn":
        return "albert heijn" in pn or pn.startswith("ah ") or pn == "ah"
    return keten.lower() in pn


def _dichtstbijzijnde_filiaal(keten: str, lat: float, lon: float) -> Optional[dict]:
    """Zoek het dichtstbijzijnde filiaal van een keten (geen afstandslimiet)."""
    try:
        # rank_by="distance" sorteert op afstand zonder straal-limiet.
        # Geen type="supermarket": dat filtert Albert Heijn er soms uit.
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
         "- Verwijder hoeveelheidswoorden uit de naam ('een', 'pak', 'fles', 'blik', 'pot', 'zak', 'tros', 'bakje', 'netje', 'doos')\n"
         "- locatie is null als er geen plaatsnaam wordt genoemd\n\n"
         "Voorbeeld input: \"13 bananen, 500 gram gehakt en 6 redbull in Delft\"\n"
         "Voorbeeld output: {{\"locatie\": \"Delft\", \"items\": ["
         "{{\"naam\": \"banaan\", \"aantal\": 13, \"eenheid\": \"stuks\"}}, "
         "{{\"naam\": \"gehakt\", \"aantal\": 500, \"eenheid\": \"gram\"}}, "
         "{{\"naam\": \"Red Bull\", \"aantal\": 6, \"eenheid\": \"stuks\"}}]}}"),
        ("user", "{input}"),
    ])

    try:
        response = (prompt | llm).invoke({"input": text})
        raw = response.content.strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            # Geen volledige JSON → waarschijnlijk afgekapt (max_tokens te laag)
            raise ValueError(
                f"Geen volledige JSON in LLM-output (mogelijk afgekapt). "
                f"Laatste 120 tekens: ...{raw[-120:]!r}"
            )
        data = json.loads(json_match.group(0))
        resultaat = ExtractieResultaat(**data)

        # Eerst de boodschappenlijst tonen
        print("\n📋 Dit heb ik begrepen:")
        for item in resultaat.items:
            print(f"   • {item.label()}")
        if resultaat.locatie:
            print(f"   📍 Locatie genoemd: {resultaat.locatie}")
        print()

        logger.success(f"Extractie OK: locatie={resultaat.locatie}, items={[i.label() for i in resultaat.items]}")
        return {"extractie": resultaat.model_dump()}
    except Exception as e:
        logger.error(f"LLM parsing faalde: {e}")
        return {"extractie": {"locatie": None, "items": []}}


def node_locatie(state: AgentState) -> AgentState:
    """Locatie uit tekst geocoderen, anders automatisch bepalen via Geolocation API."""
    if not gmaps:
        logger.warning("Geen GOOGLE_MAPS_API_KEY — locatiebepaling overgeslagen")
        return {"geocode": None}

    locatie = state["extractie"].get("locatie")
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
        # Bij gewicht (500 g gehakt) rekenen we 1 verpakking; alleen stuks vermenigvuldigen
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
        logger.debug(f"{item.label()}: AH €{ah_prijs:.2f} ({'✓' if ah_ok else '✗'}) | "
                     f"Jumbo €{jumbo_prijs:.2f} ({'✓' if jumbo_ok else '✗'})")

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

    # Prijzen (alleen AH en Jumbo hebben prijsdata)
    if ah_tot > 0 or jumbo_tot > 0:
        regels.append("💶 Prijsvergelijking (AH vs Jumbo):")
        for d in prijzen["details"]:
            ah_str = f"€{d['ah_prijs']:.2f}" if d["ah_beschikbaar"] else "—"
            jb_str = f"€{d['jumbo_prijs']:.2f}" if d["jumbo_beschikbaar"] else "—"
            opm = "  (prijs per verpakking)" if d["is_gewicht"] else ""
            regels.append(f"  • {d['label']:28s} AH {ah_str:>8s}  |  Jumbo {jb_str:>8s}{opm}")
        regels.append(f"  Totaal: AH €{ah_tot:.2f}  |  Jumbo €{jumbo_tot:.2f}")
    else:
        regels.append("⚠️ Geen prijzen gevonden bij AH of Jumbo.")
    regels.append("")

    # Dichtstbijzijnde winkels
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

    # Advies: goedkoopste + dichtstbijzijnde
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
    # Locatie is niet verplicht: die bepalen we automatisch
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


if __name__ == "__main__":
    print("=== Supermarkt Vergelijker v4 (eigen AH-client) ===")
    print(f"LM Studio: {LM_STUDIO_BASE_URL} ({LM_STUDIO_MODEL})")
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
