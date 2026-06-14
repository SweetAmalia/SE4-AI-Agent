"""
Boodschappen Agent v7 — T7_test.py: vector database + LangGraph feedbackloop

Bouwt voort op T4_test.py (semantisch zoeken in ChromaDB + live API fallback)
en voegt een ECHTE LangGraph-cyclus toe voor validatie & feedback:

  vergelijk_prijzen ──► [valideer_prijzen?] ──► advies
        ▲                       │
        │                       ▼ (onvindbare producten)
        └──────────────── verfijn_query

  Na het vergelijken controleert de router `valideer_prijzen` of er producten
  zijn die bij ZOWEL AH als Jumbo geen match opleverden. Zo ja, dan gaat de
  flow naar `verfijn_query`, die de zoekterm versimpelt (het meest linkse,
  beschrijvende woord eraf — "vegetarische balletjes" → "balletjes") en
  vervolgens TERUG-lust naar `vergelijk_prijzen`. Een teller (match_poging)
  begrenst de loop op MAX_VERFIJN_POGINGEN, zodat hij altijd termineert.

Dit demonstreert voor Sprint 3:
  - embeddings + vectordatabase (overgenomen uit T4)
  - validatie en feedbackloops (de cyclus hierboven)
  - logging & traceerbaarheid (elke iteratie wordt gelogd)

Eerst draaien:
    py testScript/build_index.py

.env.local (zelfde map):
    LM_STUDIO_BASE_URL=http://localhost:1234/v1
    LM_STUDIO_MODEL=google/gemma-4-e4b
    LM_STUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5
    GOOGLE_MAPS_API_KEY=AIza...
"""

from __future__ import annotations

import json, re
from json import JSONDecodeError
import math
import os
import re
import sys
import uuid
import requests
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

from winkel_clients import AHClient, jumbo_search_products, ah_prijs, jumbo_prijs, lidl_search_products, lidl_prijs
from vector_store import zoek_producten

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.env.local"))

# ---------- 0. Config ----------
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")
GMAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
KETENS = ["Albert Heijn", "Jumbo", "Lidl", "Hoogvliet"]

# True  → kies de goedkoopste geldige match; False → beste similarity
KIES_GOEDKOOPSTE = False

# Vector-matches onder deze similarity vertrouwen we niet → live API fallback
SIM_DREMPEL = 0.55

# Ruispenalty: elk titelwoord dat geen querywoord is, verlaagt de score licht.
# Bewust mild gehouden: de similarity blijft dominant, ruis breekt alleen
# bijna-gelijke scores (zo wint "AH Banaan" net van "Bolletje ... banaan",
# zonder een terecht beschreven product als "goudse belegen kaas" te kelderen).
NOISE_PENALTY = 0.05
# Bij KIES_GOEDKOOPSTE: alleen kandidaten binnen deze score-marge van de beste
# tellen mee voor de prijsvergelijking (anders pikt hij goedkope ruis).
SCORE_MARGE = 0.07

# Feedbackloop: hoe vaak mag de agent een onvindbaar product opnieuw proberen
# met een versimpelde zoekterm voordat hij opgeeft?
MAX_VERFIJN_POGINGEN = 2

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
    # Feedbackloop-kanalen:
    zoek_queries: Optional[dict]   # originele itemnaam → huidige (verfijnde) zoekterm
    match_poging: int              # aantal uitgevoerde verfijnrondes
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


def _verfijn_zoekterm(query: str) -> Optional[str]:
    """Versimpel een zoekterm voor de feedbackloop door het meest linkse
    (meestal beschrijvende) woord weg te laten. In het Nederlands staat de
    kern-zelfstandignaamwoord rechts: 'vegetarische balletjes' → 'balletjes',
    'magere yoghurt' → 'yoghurt'.

    Returns de kortere term, of None als er niets meer te versimpelen valt
    (één woord) — dan stopt de loop voor dit product.
    """
    woorden = query.split()
    if len(woorden) <= 1:
        return None
    return " ".join(woorden[1:])


# ---- Lexicale matching (woordgrens + Nederlands meervoud/verkleinwoord) ----
_STOPWOORDEN = {"met", "van", "het", "een", "de", "en", "in", "op", "voor", "zonder"}
_EENHEDEN = {"gram", "gr", "kg", "kilo", "ml", "ltr", "liter", "cl", "mg",
             "stuks", "stuk", "pak", "stuk", "fles", "blik", "pot", "zak"}
_MEERVOUD = ("en", "s", "eren", "tjes", "tje", "jes", "je", "n")
_WOORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)


def _matcht_querywoord(titel_woord: str, query_woord: str) -> bool:
    """Matcht een titelwoord met een querywoord, tolerant voor Nederlands
    meervoud/verkleinwoord — óók voor korte woorden als 'ei'→'eieren',
    'ui'→'uien', 'vis'→'vissen' — maar zonder ruime substring-matches die
    'appel'→'appelmoes' of 'ei'→'energy' zouden toelaten.
    """
    if titel_woord == query_woord:
        return True
    # bekende meervoud-/verkleinwoordvormen (beide richtingen)
    for korte, lange in ((query_woord, titel_woord), (titel_woord, query_woord)):
        if lange.startswith(korte) and len(lange) > len(korte):
            rest = lange[len(korte):]
            if rest in _MEERVOUD:
                return True
            # medeklinker-verdubbeling: vis→vissen, bus→bussen
            if len(korte) >= 3 and rest[:1] == korte[-1] and rest[1:] in _MEERVOUD:
                return True
    # samenstelling: titelwoord eindigt op een (meervouds)vorm van het querywoord
    # — 'scharreleieren'→'ei', 'rundergehakt'→'gehakt'. Alleen meervoudssuffixen
    # (geen verkleinwoorden, die geven valse matches als 'fluitje'→'ui').
    for suf in ("", "en", "eren", "s", "n"):
        vorm = query_woord + suf
        if len(vorm) >= 4 and len(titel_woord) > len(vorm) and titel_woord.endswith(vorm):
            return True
    # ruimere tolerantie alleen voor langere woorden (samenstellingen)
    if len(query_woord) >= 5 and len(titel_woord) >= 5:
        if titel_woord.startswith(query_woord) and len(titel_woord) - len(query_woord) <= 3:
            return True
        if query_woord.startswith(titel_woord) and len(query_woord) - len(titel_woord) <= 3:
            return True
    return False


def _query_woorden(query: str) -> list[str]:
    """Betekenisdragende woorden uit de query (≥2 tekens, geen stopwoord)."""
    return [w for w in _WOORD_RE.findall(query.lower())
            if len(w) >= 2 and w not in _STOPWOORDEN]


def _titel_woorden(titel: str) -> list[str]:
    """Inhoudswoorden uit een titel (≥4 tekens, geen eenheid/maat)."""
    return [w for w in _WOORD_RE.findall(titel.lower())
            if len(w) >= 4 and w not in _EENHEDEN]


def _titel_relevant(titel: str, query: str) -> bool:
    """Minimaal één querywoord moet (meervoud-tolerant) in de titel staan.
    Voorkomt volledig irrelevante matches ('kidneybonen' bij 'hummus',
    'appelmoes' bij 'appel', 'E Energy drink' bij 'ei')."""
    qw = _query_woorden(query)
    if not qw:
        return True  # niets om op te filteren
    titelwoorden = _WOORD_RE.findall(titel.lower())
    return any(_matcht_querywoord(tw, q) for q in qw for tw in titelwoorden)


def _ruis_aantal(titel: str, query: str) -> int:
    """Aantal inhoudswoorden in de titel dat geen enkel querywoord matcht —
    een maat voor hoe 'vervuild' de titel is t.o.v. de zoekvraag."""
    qw = _query_woorden(query)
    return sum(1 for tw in _titel_woorden(titel)
               if not any(_matcht_querywoord(tw, q) for q in qw))


def _kies_beste(kandidaten: list[dict], query: str) -> Optional[dict]:
    """Gedeelde selectie voor vector- én live-kandidaten.

    Hard filter: titel moet relevant zijn (querywoord erin). Daarna score =
    similarity − ruispenalty; bij KIES_GOEDKOOPSTE de goedkoopste binnen de
    score-marge van de beste, anders simpelweg de hoogste score.

    Elke kandidaat is {title, prijs, similarity}; similarity mag None zijn
    (live fallback) — dan telt alleen de ruispenalty.
    """
    gescoord = []
    for k in kandidaten:
        if not _titel_relevant(k["title"], query):
            continue
        basis = k["similarity"] if k.get("similarity") is not None else 1.0
        ruis = _ruis_aantal(k["title"], query)
        gescoord.append({**k, "score": round(basis - NOISE_PENALTY * ruis, 3), "ruis": ruis})

    if not gescoord:
        return None

    gescoord.sort(key=lambda k: k["score"], reverse=True)
    if KIES_GOEDKOOPSTE:
        beste_score = gescoord[0]["score"]
        tier = [k for k in gescoord if k["score"] >= beste_score - SCORE_MARGE]
        return min(tier, key=lambda k: k["prijs"])
    return gescoord[0]


def _vector_match(query: str, winkel: str) -> Optional[dict]:
    """Beste product uit de vector-index: semantisch boven de drempel, geen
    multipack, lexicaal relevant, en met de minste titel-ruis. Bij
    KIES_GOEDKOOPSTE de goedkoopste binnen de top-scorende kandidaten.

    Returns {title, prijs, similarity} of None als niets door de filters komt.
    """
    kandidaten = zoek_producten(query, winkel, n=15)
    if not kandidaten:
        return None

    logger.debug(
        f"Vector '{query}' @ {winkel} → "
        f"{[(k['title'], k['similarity']) for k in kandidaten[:5]]}"
    )

    query_heeft_multipack = bool(_MULTIPACK_RE.search(query))
    boven_drempel = [
        k for k in kandidaten
        if k["similarity"] >= SIM_DREMPEL
        and k.get("prijs")
        and (query_heeft_multipack or not _MULTIPACK_RE.search(k["title"]))
    ]
    return _kies_beste(boven_drempel, query)



@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _live_fallback(query: str, winkel: str) -> Optional[dict]:
    """Live API-zoektocht als de vector-index geen goede match heeft."""
    try:
        if winkel == "Albert Heijn":
            ruwe = ah.search_products(query, size=10)
            prijs_fn = ah_prijs
        elif winkel == "Jumbo":
            ruwe = jumbo_search_products(query)[:10]
            prijs_fn = jumbo_prijs
        else:
            ruwe = lidl_search_products(query)[:10]
            prijs_fn = lidl_prijs
    except requests.exceptions.HTTPError as e:
        # Vangt 503 (Unavailable) en 403 (Forbidden) op zonder te crashen
        logger.warning(f"Live fallback overgeslagen voor {winkel} wegens server-beperking: {e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"Onverwachte fout in live fallback voor {winkel}: {e}")
        return None

    logger.debug(f"Live fallback '{query}' @ {winkel} → {[p.get('title') for p in ruwe[:5]]}")

    query_heeft_multipack = bool(_MULTIPACK_RE.search(query))
    kandidaten = []
    
    for p in ruwe:
        if not p.get("title") or not prijs_fn(p):
            continue
            
        titel = p["title"]
        if not query_heeft_multipack and _MULTIPACK_RE.search(titel):
            # Als de gebruiker geen multipack vroeg, maar de titel is een pack, 
            # dan proberen we hier alvast de verpakkingsgrootte uit de titel te parsen
            # zodat we dit kunnen doorgeven aan node_vergelijk_prijzen!
            pass 

        # We injecteren de metadata dynamisch op basis van de live titel!
        naam_lower = titel.lower()
        aantal = 1
        match_pk = re.search(r'(\d+)\s*pk', naam_lower)
        match_stubs = re.search(r'(\d+)\s*stuks', naam_lower)
        match_x = re.search(r'(\d+)\s*x\s*\d+', naam_lower)
        
        if match_pk: aantal = int(match_pk.group(1))
        elif match_stubs: aantal = int(match_stubs.group(1))
        elif match_x: aantal = int(match_x.group(1))

        kandidaten.append({
            "title": titel, 
            "prijs": prijs_fn(p), 
            "similarity": None,
            "aantal_in_verpakking": aantal, # <--- DIT MISTE BIJ DE LIVE FALLBACK!
            "eenheid": "zak" if "zak" in naam_lower or "net" in naam_lower else "stuk"
        })
        
    match = _kies_beste(kandidaten, query)
    if not match:
        logger.debug(f"Live fallback '{query}' @ {winkel} → alle resultaten gefilterd als irrelevant")
    return match


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

def _extract_balanced_json(text: str) -> str | None:
    """Vindt het eerste { ... } blok met gebalanceerde accolades.
    Robuster dan r'\\{.*\\}' bij afgekapte/rommelige LLM output."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None  # niet gebalanceerd → afgekapt


def _parse_llm_json(raw: str) -> dict:
    """Probeert in drie lagen: strict → balanced → repair."""
    # 1) direct
    try:
        return json.loads(raw)
    except JSONDecodeError:
        pass
    # 2) balanced extract
    candidate = _extract_balanced_json(raw)
    if candidate:
        try:
            return json.loads(candidate)
        except JSONDecodeError:
            raw = candidate  # geef aan de repair-stap mee
    # 3) json-repair als laatste redmiddel
    if repair_json is not None:
        try:
            fixed = repair_json(raw)
            return json.loads(fixed)
        except Exception as e:
            raise ValueError(f"json-repair faalde: {e}") from e
    raise ValueError("Kon geen valide JSON uit LLM-output halen")


def node_parse_input(state: AgentState) -> AgentState:
    logger.info("Node 1 — intent extractie")
    text = state.get("user_input", "")

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Jij bent een strenge data-extractor voor een supermarkt-API. "
         "Geef ALLEEN een geldig JSON-object terug, zonder uitleg of markdown. "
         "Gebruik dubbele quotes. Maak het JSON-object altijd af.\n\n"
         "Formaat: {{\"locatie\": \"stad of null\", \"items\": [{{\"naam\": \"productnaam\", \"aantal\": 1, \"eenheid\": \"stuks\"}}]}}\n\n"
         "Regels:\n"
         "- 'eenheid' is een van: stuks, gram, kg, ml, liter\n"
         "- Telbare producten (bananen, broden, blikjes): eenheid=stuks\n"
         "- Gewicht/volume: aantal=hoeveelheid, eenheid=gewichtseenheid\n"
         "- Verwijder verpakkingswoorden: pak, pakje, fles, blik, blikje, pot, zak, tros, bakje, netje, doos, bos, rol\n"
         "- Behoud beschrijvende woorden (vegetarisch, biologisch, mager, halfvol, etc.)\n"
         "- locatie = null als er geen plaatsnaam genoemd is (NIET een lege string).\n\n"
         "Voorbeeld input: \"24 blikjes redbull\"\n"
         "Voorbeeld output: {{\"locatie\": null, \"items\": ["
         "{{\"naam\": \"Red Bull\", \"aantal\": 24, \"eenheid\": \"stuks\"}}]}}"),
        ("user", "{input}"),
    ])

    # Standaard reset-payload: zorgt dat oude geocode/winkels van vorige turn
    # NIET blijven hangen.  Dit fixt bug 1.
    reset = {
        "geocode": None,
        "winkels": None,
        "prijs_data": None,
        "advies": None,
        "zoek_queries": {},
        "match_poging": 0,
    }

    def _try_extract(user_text: str) -> dict:
        response = (prompt | llm).invoke({"input": user_text})
        raw = response.content.strip()
        return _parse_llm_json(raw)

    try:
        try:
            data = _try_extract(text)
        except (JSONDecodeError, ValueError) as first_err:
            logger.warning(f"LLM JSON-parse faalde, 1x retry: {first_err}")
            # Retry met een licht aangescherpte hint
            data = _try_extract(text + "\n\n# Geef alleen geldig, compleet JSON terug.")

        resultaat = ExtractieResultaat(**data)

        # Normaliseer lege string -> None  (helpt node_locatie)
        if isinstance(resultaat.locatie, str) and not resultaat.locatie.strip():
            resultaat.locatie = None

        print("\n📋 Dit heb ik begrepen:")
        for item in resultaat.items:
            print(f"   • {item.label()}")
        if resultaat.locatie:
            print(f"   📍 Locatie genoemd: {resultaat.locatie}")
        print()

        logger.success(
            f"Extractie OK: locatie={resultaat.locatie}, "
            f"items={[i.label() for i in resultaat.items]}"
        )
        return {"extractie": resultaat.model_dump(), **reset}

    except Exception as e:
        logger.error(f"LLM parsing faalde definitief: {e}")
        return {"extractie": {"locatie": None, "items": []}, **reset}

# def node_parse_input(state: AgentState) -> AgentState:
#     logger.info("Node 1 — intent extractie")
#     text = state.get("user_input", "")

#     prompt = ChatPromptTemplate.from_messages([
#         ("system",
#          "Jij bent een strenge data-extractor voor een supermarkt-API. "
#          "Geef ALLEEN een geldig JSON-object terug, zonder uitleg of markdown. "
#          "Maak het JSON-object af, ook bij lange lijsten.\n\n"
#          "Formaat: {{\"locatie\": \"stad of null\", \"items\": [{{\"naam\": \"productnaam\", \"aantal\": 1, \"eenheid\": \"stuks\"}}]}}\n\n"
#          "Regels:\n"
#          "- 'eenheid' is een van: stuks, gram, kg, ml, liter\n"
#          "- Telbare producten (bananen, broden, blikjes): eenheid=stuks, aantal=hoeveel stuks\n"
#          "- Gewicht/volume (500 gram gehakt, 1.5 liter melk): aantal=hoeveelheid, eenheid=gewichtseenheid\n"
#          "- Verwijder ALLEEN verpakkings- en containerwoorden uit de naam: "
#          "'pak', 'pakje', 'fles', 'blik', 'blikje', 'pot', 'zak', 'tros', 'bakje', 'netje', 'doos', 'bos', 'rol', 'flesje', 'potje'\n"
#          "- Behoud ALTIJD beschrijvende woorden zoals: vegetarisch, biologisch, mager, halfvol, "
#          "volkoren, light, naturel, gerookt, vers, diepvries, zout, ongezouten, wit, bruin, "
#          "of andere eigenschappen die het product beschrijven\n"
#          "- Schrijf productnamen in enkelvoud TENZIJ het merk of product altijd meervoud gebruikt\n"
#          "- locatie is null als er geen plaatsnaam wordt genoemd\n\n"
#          "Voorbeeld input: \"13 bananen, 500 gram gehakt, 6 redbull en een zak vegetarische balletjes in Delft\"\n"
#          "Voorbeeld output: {{\"locatie\": \"Delft\", \"items\": ["
#          "{{\"naam\": \"banaan\", \"aantal\": 13, \"eenheid\": \"stuks\"}}, "
#          "{{\"naam\": \"gehakt\", \"aantal\": 500, \"eenheid\": \"gram\"}}, "
#          "{{\"naam\": \"Red Bull\", \"aantal\": 6, \"eenheid\": \"stuks\"}}, "
#          "{{\"naam\": \"vegetarische balletjes\", \"aantal\": 1, \"eenheid\": \"stuks\"}}]}}"),
#         ("user", "{input}"),
#     ])

#     try:
#         response = (prompt | llm).invoke({"input": text})
#         raw = response.content.strip()
#         json_match = re.search(r"\{.*\}", raw, re.DOTALL)
#         if not json_match:
#             raise ValueError(
#                 f"Geen volledige JSON in LLM-output (mogelijk afgekapt). "
#                 f"Laatste 120 tekens: ...{raw[-120:]!r}"
#             )
#         data = json.loads(json_match.group(0))
#         resultaat = ExtractieResultaat(**data)

#         print("\n📋 Dit heb ik begrepen:")
#         for item in resultaat.items:
#             print(f"   • {item.label()}")
#         if resultaat.locatie:
#             print(f"   📍 Locatie genoemd: {resultaat.locatie}")
#         print()

#         logger.success(f"Extractie OK: locatie={resultaat.locatie}, items={[i.label() for i in resultaat.items]}")
#         # Feedbackloop-teller resetten bij een nieuwe vraag
#         return {
#             "extractie": resultaat.model_dump(),
#             "zoek_queries": {},
#             "match_poging": 0,
#             # geen oude locaties en adviezen meenemen in een volgende run. (verander voor deployment)
#             "geocode": None,
#             "winkels": None,
#             "prijs_data": None,
#             "advies": None,
#         }
#     except Exception as e:
#         logger.error(f"LLM parsing faalde: {e}")
#         return {"extractie": {"locatie": None, "items": []}, "zoek_queries": {}, "match_poging": 0}

def node_locatie(state: AgentState) -> AgentState:
    # if locatie == lege string > set None
    locatie = state["extractie"].get("locatie")
    if isinstance(locatie, str) and not locatie.strip():
        locatie = None

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
    """Zoekt elk product bij AH + Jumbo via de vector-index (live als fallback).
    
    Berekent prijzen intelligent op basis van losse stuks versus multipacks/verpakkingen.
    """
    poging = state.get("match_poging", 0)
    qmap = dict(state.get("zoek_queries") or {})
    items = [BoodschapItem(**i) for i in state["extractie"]["items"]]

    if poging == 0:
        logger.info("Node 4 — prijzen vergelijken (vector-index + live fallback)")
    else:
        logger.info(f"Node 4 — prijzen vergelijken (feedbackloop iteratie {poging})")

    # Effectieve zoekterm per item
    queries = [qmap.get(item.naam, item.naam) for item in items]

    with ThreadPoolExecutor(max_workers=8) as pool:
        zoekresultaten = list(pool.map(_zoek_beide_winkels, queries))

    ah_totaal = 0.0
    jumbo_totaal = 0.0
    details = []

    def _bereken_slimme_prijs(boodschap_item: BoodschapItem, match: Optional[dict]) -> tuple[float, str]:
        """Berekent de totale prijs op basis van aantal_in_verpakking uit metadata.
        
        Returns: (totale_prijs, opmerking_string)
        """
        if not match or not match.get("prijs"):
            return 0.0, ""
            
        stuksprijs = float(match["prijs"])
        # Haal de verpakkingsgrootte uit de metadata van de match (default naar 1)
        # Note: controleer of jouw vector_store match-dict de metadata direct doorgeeft,
        # zo niet, zorg dat je in vector_store.py de velden uit meta.get(...) doorgeeft.
        aantal_in_verpakking = int(match.get("aantal_in_verpakking", 1))
        
        # Scenario 1: Het is een telbaar product (stuks) en de DB geeft een multipack terug
        if boodschap_item.eenheid == "stuks" and aantal_in_verpakking > 1:
            # Bereken hoeveel hele verpakkingen we minimaal nodig hebben (bijv. 2 / 6 = 1 pack)
            benodigde_verpakkingen = math.ceil(boodschap_item.aantal / aantal_in_verpakking)
            totaal = round(benodigde_verpakkingen * stuksprijs, 2)
            opmerking = f"({benodigde_verpakkingen}x pack van {aantal_in_verpakking})"
            return totaal, opmerking
            
        # Scenario 2: Het is een telbaar product en de DB geeft een los product terug
        elif boodschap_item.eenheid == "stuks":
            totaal = round(boodschap_item.aantal * stuksprijs, 2)
            return totaal, ""
            
        # Scenario 3: Het gaat om gewicht of volume (gram/ml), prijs per verpakking
        else:
            return stuksprijs, "(per verpakking)"

    for item, query, ((ah_match, ah_bron), (jumbo_match, jumbo_bron)) in zip(items, queries, zoekresultaten):
        
        # Bereken de prijzen op basis van de metadata
        ah_prijs_tot, ah_opm = _bereken_slimme_prijs(item, ah_match)
        jumbo_prijs_tot, jumbo_opm = _bereken_slimme_prijs(item, jumbo_match)

        ah_ok = ah_prijs_tot > 0
        jumbo_ok = jumbo_prijs_tot > 0

        ah_totaal += ah_prijs_tot
        jumbo_totaal += jumbo_prijs_tot

        details.append({
            "naam": item.naam,
            "query": query,
            "label": item.label(),
            "is_gewicht": item.is_gewicht,
            "ah_prijs": ah_prijs_tot,
            "ah_beschikbaar": ah_ok,
            "ah_match": (ah_match or {}).get("title"),
            "ah_opm": ah_opm,               # Doorgeven aan node_advies
            "jumbo_prijs": jumbo_prijs_tot,
            "jumbo_beschikbaar": jumbo_ok,
            "jumbo_match": (jumbo_match or {}).get("title"),
            "jumbo_opm": jumbo_opm,         # Doorgeven aan node_advies
        })
        
        ah_titel = (ah_match or {}).get("title", "geen match")
        jumbo_titel = (jumbo_match or {}).get("title", "geen match")
        ah_sim = (ah_match or {}).get("similarity")
        jumbo_sim = (jumbo_match or {}).get("similarity")
        ah_sim_str = f", sim={ah_sim}" if ah_sim is not None else ""
        jumbo_sim_str = f", sim={jumbo_sim}" if jumbo_sim is not None else ""
        zoek_str = "" if query == item.naam else f" [zoekterm: '{query}']"
        
        logger.debug(f"{item.label()}{zoek_str}: AH €{ah_prijs_tot:.2f} ({'✓' if ah_ok else '✗'}, {ah_bron}{ah_sim_str}) {ah_opm} → {ah_titel}")
        logger.debug(f"{item.label()}{zoek_str}: Jumbo €{jumbo_prijs_tot:.2f} ({'✓' if jumbo_ok else '✗'}, {jumbo_bron}{jumbo_sim_str}) {jumbo_opm} → {jumbo_titel}")

    return {"prijs_data": {
        "ah_totaal": round(ah_totaal, 2),
        "jumbo_totaal": round(jumbo_totaal, 2),
        "details": details,
    }}


def node_verfijn_query(state: AgentState) -> AgentState:
    """Feedbackloop-correctie: versimpel de zoekterm van elk product dat bij
    ZOWEL AH als Jumbo niets opleverde, en verhoog de poging-teller. De flow
    lust hierna terug naar `vergelijk_prijzen` om het opnieuw te proberen.
    """
    poging = state.get("match_poging", 0) + 1
    qmap = dict(state.get("zoek_queries") or {})
    details = state["prijs_data"]["details"]

    verfijnd = []
    for d in details:
        if d["ah_beschikbaar"] or d["jumbo_beschikbaar"]:
            continue  # ergens gevonden → niet aanraken
        nieuwe = _verfijn_zoekterm(d["query"])
        if nieuwe:
            qmap[d["naam"]] = nieuwe
            verfijnd.append((d["query"], nieuwe))

    logger.warning(
        f"🔁 Feedbackloop iteratie {poging}: {len(verfijnd)} onvindbaar product(en) "
        f"opnieuw proberen met versimpelde zoekterm — "
        + ", ".join(f"'{oud}' → '{nieuw}'" for oud, nieuw in verfijnd)
    )
    return {"zoek_queries": qmap, "match_poging": poging}


def node_advies(state: AgentState) -> AgentState:
    geocode = state.get("geocode")
    winkels = state.get("winkels") or {}
    prijzen = state["prijs_data"]
    ah_tot, jumbo_tot = prijzen["ah_totaal"], prijzen["jumbo_totaal"]
    poging = state.get("match_poging", 0)

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
            # Toon de verfijnde zoekterm als de feedbackloop die heeft aangepast
            verfijn_opm = "" if d["query"] == d["naam"] else f"  ↻ gezocht op '{d['query']}'"
            regels.append(f"  • {d['label']:28s} AH {ah_str:>8s}  |  Jumbo {jb_str:>8s}{opm}{verfijn_opm}")
            regels.append(f"      AH:    {d['ah_match'] or 'geen match'}")
            regels.append(f"      Jumbo: {d['jumbo_match'] or 'geen match'}")
        regels.append(f"  Totaal: AH €{ah_tot:.2f}  |  Jumbo €{jumbo_tot:.2f}")
    else:
        regels.append("⚠️ Geen prijzen gevonden bij AH of Jumbo.")
    regels.append("")

    # Feedbackloop-traceerbaarheid in het advies
    if poging > 0:
        nog_open = [d["label"] for d in prijzen["details"]
                    if not d["ah_beschikbaar"] and not d["jumbo_beschikbaar"]]
        regels.append(f"🔁 Feedbackloop: {poging} verfijnronde(s) uitgevoerd.")
        if nog_open:
            regels.append(f"   Nog steeds niet gevonden: {', '.join(nog_open)}")
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


def valideer_prijzen(state: AgentState) -> Literal["verfijn", "klaar"]:
    """Feedbackloop-router. Stuur terug naar verfijn_query zolang er producten
    zijn die nergens gematcht zijn, nog te versimpelen vallen, en we onder de
    maximale poging-limiet zitten. Anders: door naar het advies.
    """
    details = state["prijs_data"]["details"]
    poging = state.get("match_poging", 0)

    onvindbaar = [d for d in details
                  if not d["ah_beschikbaar"] and not d["jumbo_beschikbaar"]]
    # Alleen producten waarvan de zoekterm nog korter kan, zijn nog te redden
    verfijnbaar = [d for d in onvindbaar if _verfijn_zoekterm(d["query"])]

    ###################JONATHAN######################
    mismatch_gedetecteerd = False
    for d in details:
        # Als de ene winkel een multipack pakt en de andere een los product, 
        # of als de similarity-marge tussen AH en Jumbo te groot is:
        if d["ah_opm"] != d["jumbo_opm"] and (d["ah_beschikbaar"] and d["jumbo_beschikbaar"]):
            logger.warning(f"Productverschil gedetecteerd voor {d['naam']}: AH gebruikt {d['ah_opm'] or 'los'} en Jumbo gebruikt {d['jumbo_opm'] or 'los'}")
            mismatch_gedetecteerd = True

    if verfijnbaar and poging < MAX_VERFIJN_POGINGEN:
        logger.info(
            f"Validatie: {len(onvindbaar)} onvindbaar, {len(verfijnbaar)} nog te verfijnen "
            f"(poging {poging}/{MAX_VERFIJN_POGINGEN}) → feedbackloop"
        )
        return "verfijn"

    if onvindbaar:
        logger.info(f"Validatie: {len(onvindbaar)} blijven onvindbaar, loop gestopt → advies")
    else:
        logger.success("Validatie: alle producten gematcht → advies")
    return "klaar"


# ---------- 6. Graph ----------
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse_input", node_parse_input)
    g.add_node("locatie", node_locatie)
    g.add_node("winkels", node_winkels)
    g.add_node("vraag_verduidelijking", node_vraag_verduidelijking)
    g.add_node("vergelijk_prijzen", node_vergelijk_prijzen)
    g.add_node("verfijn_query", node_verfijn_query)
    g.add_node("advies", node_advies)

    g.add_edge(START, "parse_input")
    g.add_conditional_edges("parse_input", valideer_extractie, {
        "compleet": "locatie",
        "incompleet": "vraag_verduidelijking",
    })
    g.add_edge("locatie", "winkels")
    g.add_edge("winkels", "vergelijk_prijzen")

    # Feedbackloop: valideer de matches; verfijn-en-herprobeer of door naar advies
    g.add_conditional_edges("vergelijk_prijzen", valideer_prijzen, {
        "verfijn": "verfijn_query",
        "klaar": "advies",
    })
    g.add_edge("verfijn_query", "vergelijk_prijzen")  # <-- de cyclus

    g.add_edge("vraag_verduidelijking", END)
    g.add_edge("advies", END)

    return g.compile(checkpointer=MemorySaver())


app = build_graph()
config = {"configurable": {"thread_id": str(uuid.uuid4())}}


def vraag(tekst: str) -> None:
    """Stuur één bericht naar de agent en print het advies."""
    result = app.invoke({"user_input": tekst}, config)
    print(f"\n{result.get('advies')}\n")


def test_feedbackloop():
    """Test de verfijn-helper los van de graph (geen index/LLM nodig)."""
    print("\n=== TEST: zoekterm-verfijning (feedbackloop-stap) ===\n")
    cases = [
        "vegetarische balletjes",
        "magere biologische yoghurt",
        "Red Bull Tropical",
        "melk",  # één woord → niet verder te verfijnen
    ]
    for q in cases:
        keten = []
        huidig = q
        while huidig:
            keten.append(huidig)
            huidig = _verfijn_zoekterm(huidig)
        print(f"  '{q}'  →  {' → '.join(keten[1:]) or '(niet verder te versimpelen)'}")
    print()


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
        test_feedbackloop()
        test_vector_match()
        sys.exit(0)

    from vector_store import get_collectie
    aantal = get_collectie().count()

    print("=== Supermarkt Vergelijker v7 (T7, vector database + feedbackloop) ===")
    print(f"LM Studio: {LM_STUDIO_BASE_URL} ({LM_STUDIO_MODEL})")
    print(f"Vector-index: {aantal} producten" + (" ⚠️ LEEG — draai build_index.py!" if aantal == 0 else ""))
    print(f"Feedbackloop: max {MAX_VERFIJN_POGINGEN} verfijnrondes")
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
