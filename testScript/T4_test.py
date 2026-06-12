"""
Boodschappen Agent v6 — T4_test.py: vector database editie

Nieuw t.o.v. v5 (T3_test.py):
  - Productmatching via semantisch zoeken in ChromaDB (zie vector_store.py)
    in plaats van woord-overlap op live API-resultaten.
  - De catalogus wordt vooraf geïndexeerd met build_index.py; embeddings
    komen van LM Studio (zelfde server als de chat-LLM).
  - Live API blijft als fallback wanneer de vector-match onder de
    similarity-drempel zit (product niet in de index).

Eerst draaien:
    py testScript/build_index.py

.env.local (zelfde map):
    LM_STUDIO_BASE_URL=http://localhost:1234/v1
    LM_STUDIO_MODEL=google/gemma-4-e4b
    LM_STUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5
    GOOGLE_MAPS_API_KEY=AIza...
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
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

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import googlemaps

from winkel_clients import AHClient, jumbo_search_products, ah_prijs, jumbo_prijs
from vector_store import zoek_producten

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local"))

# ---------- 0. Config ----------
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")
GMAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
KETENS = ["Albert Heijn", "Jumbo", "Lidl", "Hoogvliet"]

# True  → kies de goedkoopste geldige match; False → beste similarity
KIES_GOEDKOOPSTE = True

# Vector-matches onder deze similarity vertrouwen we niet → live API fallback
SIM_DREMPEL = 0.55

gmaps = googlemaps.Client(key=GMAPS_KEY) if GMAPS_KEY else None
ah = AHClient()

llm = ChatOpenAI(
    base_url=LM_STUDIO_BASE_URL,
    api_key="lm-studio",
    model=LM_STUDIO_MODEL,
    temperature=0.1,
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


# Multipack-patronen: "2x 12-pack", "12-pack", "4x250ml", "7+1", "24x", "multipack", "tray"
# Query noemt nooit een verpakkingsgrootte → zulke titels worden uitgesloten.
_MULTIPACK_RE = re.compile(
    r"\b\d+[\s\-]?pack\b"
    r"|\bmultipack\b"
    r"|\btray\b"
    r"|\b\d+\s*\+\s*\d+\b"             # 7+1, 5 + 1 (bonusverpakking)
    r"|\b(?:[2-9]|\d{2,})\s*x(?!\w)"   # 2x, 24x, 15 x (maar niet "1x" of "extra")
    r"|\b(?:[2-9]|\d{2,})\s*x\d",      # 4x250ml (x direct gevolgd door cijfer)
    re.IGNORECASE,
)


def _vector_match(query: str, winkel: str) -> Optional[dict]:
    """Beste product uit de vector-index: semantisch dichtbij, geen multipack,
    en bij KIES_GOEDKOOPSTE de laagste prijs binnen de geldige kandidaten.

    Returns {title, prijs, similarity} of None als niets boven de drempel komt.
    """
    kandidaten = zoek_producten(query, winkel, n=8)
    if not kandidaten:
        return None

    logger.debug(
        f"Vector '{query}' @ {winkel} → "
        f"{[(k['title'], k['similarity']) for k in kandidaten[:5]]}"
    )

    query_heeft_multipack = bool(_MULTIPACK_RE.search(query))
    geldig = [
        k for k in kandidaten
        if k["similarity"] >= SIM_DREMPEL
        and k.get("prijs")
        and (query_heeft_multipack or not _MULTIPACK_RE.search(k["title"]))
    ]
    if not geldig:
        return None

    if KIES_GOEDKOOPSTE:
        return min(geldig, key=lambda k: k["prijs"])
    return geldig[0]  # hoogste similarity


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _live_fallback(query: str, winkel: str) -> Optional[dict]:
    """Live API-zoektocht als de vector-index geen goede match heeft.
    Pakt het goedkoopste niet-multipack resultaat."""
    if winkel == "Albert Heijn":
        ruwe = ah.search_products(query, size=10)
        prijs_fn = ah_prijs
    else:
        ruwe = jumbo_search_products(query)[:10]
        prijs_fn = jumbo_prijs

    logger.debug(f"Live fallback '{query}' @ {winkel} → {[p.get('title') for p in ruwe[:5]]}")

    query_heeft_multipack = bool(_MULTIPACK_RE.search(query))
    geldig = [
        {"title": p["title"], "prijs": prijs_fn(p), "similarity": None}
        for p in ruwe
        if p.get("title") and prijs_fn(p)
        and (query_heeft_multipack or not _MULTIPACK_RE.search(p["title"]))
    ]
    if not geldig:
        return None
    if KIES_GOEDKOOPSTE:
        return min(geldig, key=lambda k: k["prijs"])
    return geldig[0]


def _zoek_product(query: str, winkel: str) -> tuple[Optional[dict], str]:
    """Vector-index eerst; live API als fallback. Returns (match, bron)."""
    try:
        match = _vector_match(query, winkel)
        if match:
            return match, "vector"
    except Exception as e:
        logger.warning(f"Vector search faalde voor '{query}' @ {winkel}: {e}")

    try:
        match = _live_fallback(query, winkel)
        if match:
            return match, "live"
    except Exception as e:
        logger.warning(f"Live fallback faalde voor '{query}' @ {winkel}: {e}")
    return None, "geen"


def _zoek_beide_winkels(naam: str) -> tuple[tuple[Optional[dict], str], tuple[Optional[dict], str]]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        ah_future = pool.submit(_zoek_product, naam, "Albert Heijn")
        jumbo_future = pool.submit(_zoek_product, naam, "Jumbo")
        return ah_future.result(), jumbo_future.result()


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
    logger.info("Node 4 — prijzen vergelijken (vector-index + live fallback)")
    items = [BoodschapItem(**i) for i in state["extractie"]["items"]]

    ah_totaal = 0.0
    jumbo_totaal = 0.0
    details = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        zoekresultaten = list(pool.map(lambda i: _zoek_beide_winkels(i.naam), items))

    for item, ((ah_match, ah_bron), (jumbo_match, jumbo_bron)) in zip(items, zoekresultaten):
        multiplier = item.aantal if item.eenheid == "stuks" else 1

        ah_stuk = (ah_match or {}).get("prijs") or 0.0
        ah_ok = ah_stuk > 0
        ah_prijs_tot = round(ah_stuk * multiplier, 2)

        jumbo_stuk = (jumbo_match or {}).get("prijs") or 0.0
        jumbo_ok = jumbo_stuk > 0
        jumbo_prijs_tot = round(jumbo_stuk * multiplier, 2)

        ah_totaal += ah_prijs_tot
        jumbo_totaal += jumbo_prijs_tot

        details.append({
            "label": item.label(),
            "is_gewicht": item.is_gewicht,
            "ah_prijs": ah_prijs_tot,
            "ah_beschikbaar": ah_ok,
            "ah_match": (ah_match or {}).get("title"),
            "jumbo_prijs": jumbo_prijs_tot,
            "jumbo_beschikbaar": jumbo_ok,
            "jumbo_match": (jumbo_match or {}).get("title"),
        })
        ah_titel = (ah_match or {}).get("title", "geen match")
        jumbo_titel = (jumbo_match or {}).get("title", "geen match")
        ah_sim = (ah_match or {}).get("similarity")
        jumbo_sim = (jumbo_match or {}).get("similarity")
        ah_sim_str = f", sim={ah_sim}" if ah_sim is not None else ""
        jumbo_sim_str = f", sim={jumbo_sim}" if jumbo_sim is not None else ""
        logger.debug(f"{item.label()}: AH €{ah_prijs_tot:.2f} ({'✓' if ah_ok else '✗'}, {ah_bron}{ah_sim_str}) → {ah_titel}")
        logger.debug(f"{item.label()}: Jumbo €{jumbo_prijs_tot:.2f} ({'✓' if jumbo_ok else '✗'}, {jumbo_bron}{jumbo_sim_str}) → {jumbo_titel}")

    return {"prijs_data": {
        "ah_totaal": round(ah_totaal, 2),
        "jumbo_totaal": round(jumbo_totaal, 2),
        "details": details,
    }}


def node_advies(state: AgentState) -> AgentState:
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


def test_vector_match():
    """Test de vector-matching op een paar lastige queries (vereist gevulde index)."""
    print("\n=== TEST: vector matching ===\n")
    for query in ["Red Bull Tropical", "pinda", "vegetarische balletjes", "watermeloen"]:
        for winkel in ("Albert Heijn", "Jumbo"):
            match, bron = _zoek_product(query, winkel)
            if match:
                sim = f" (sim={match['similarity']})" if match.get("similarity") is not None else ""
                print(f"  '{query}' @ {winkel:13s} [{bron}]{sim} → {match['title']} €{match['prijs']:.2f}")
            else:
                print(f"  '{query}' @ {winkel:13s} [geen match]")
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_vector_match()
        sys.exit(0)

    from vector_store import get_collectie
    aantal = get_collectie().count()

    print("=== Supermarkt Vergelijker v6 (T4, vector database) ===")
    print(f"LM Studio: {LM_STUDIO_BASE_URL} ({LM_STUDIO_MODEL})")
    print(f"Vector-index: {aantal} producten" + (" ⚠️ LEEG — draai build_index.py!" if aantal == 0 else ""))
    print(f"Google Maps: {'✓' if gmaps else '✗ (geen key)'}")
    print("Typ 'stop' om af te sluiten.\n")

    while True:
        try:
            user_input = input("Jij: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("stop", "quit", "exit"):
            break
        vraag(user_input)
