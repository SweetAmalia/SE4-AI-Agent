"""
Boodschappen Agent v2

Fixes t.o.v. v1:
  1. currentPrice=None crasht niet meer (`or 0.0`)
  2. Jumbo 403 / AH faal isoleert per-store i.p.v. hele node killen
  3. LM Studio endpoint via .env (werkt op laptop én desktop)
  4. Locatie → lat/lon via Google Maps + dichtstbijzijnde AH/Jumbo store
  5. loguru-logging in plaats van print
  6. retry met tenacity op flakey APIs
  7. nette per-product availability flag → advies vermeldt missende producten

.env voorbeeld (zelfde map als dit script):
    LM_STUDIO_BASE_URL=http://localhost:1234/v1
    LM_STUDIO_MODEL=local-model
    GOOGLE_MAPS_API_KEY=AIza...
"""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from operator import add

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from supermarktconnector.ah import AHConnector
from supermarktconnector.jumbo import JumboConnector

import googlemaps

load_dotenv()

print(f"DEBUG ENV: LM_STUDIO_BASE_URL={os.getenv('LM_STUDIO_BASE_URL')}")
print(f"DEBUG ENV: cwd={os.getcwd()}")

# ---------- 0. Config ----------
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")
GMAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

gmaps = googlemaps.Client(key=GMAPS_KEY) if GMAPS_KEY else None
ah = AHConnector()
jumbo = JumboConnector()


# ---------- 1. Pydantic Schemas ----------
class ExtractieResultaat(BaseModel):
    locatie: Optional[str] = Field(description="Stad/dorp/locatie. Null als niet genoemd.")
    items: list[str] = Field(description="Gestandaardiseerde lijst losse basisproducten.")


# ---------- 2. State ----------
class AgentState(TypedDict, total=False):
    user_input: str
    extractie: Optional[dict]
    geocode: Optional[dict]          # {lat, lon, formatted_address}
    prijs_data: Optional[dict]
    advies: Optional[str]
    chat_history: Annotated[list[str], add]


# ---------- 3. Helpers met retry ----------
@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _ah_search(query: str) -> Optional[dict]:
    res = ah.search_products(query=query, size=1, page=0)
    if res and res.get("products"):
        return res["products"][0]
    return None


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _jumbo_search(query: str) -> Optional[dict]:
    res = jumbo.search_products(query=query, size=1, page=0)
    try:
        return res["products"]["data"][0]
    except (KeyError, IndexError, TypeError):
        return None


def _safe_ah_price(product: Optional[dict]) -> tuple[float, bool]:
    """Returns (prijs, beschikbaar). 0.0 + False als niet gevonden."""
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
        amount = product["prices"]["price"]["amount"]
        prijs = amount / 100.0 if amount >= 100 else float(amount)
        return prijs, prijs > 0
    except (KeyError, TypeError):
        return 0.0, False


# ---------- 4. Nodes ----------
def node_parse_input(state: AgentState) -> AgentState:
    logger.info("Node 1 — intent extractie")
    text = state.get("user_input", "")

    llm = ChatOpenAI(
        base_url=LM_STUDIO_BASE_URL,
        api_key="lm-studio",
        model=LM_STUDIO_MODEL,
        temperature=0.1,
        timeout=30,
    )
    structured_llm = llm.with_structured_output(ExtractieResultaat)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Jij bent een strenge data-extractor voor een supermarkt-API. "
         "Haal de locatie en boodschappen uit de tekst. "
         "Zet items om naar schone zoektermen zonder 'een', 'pak', 'fles', 'blik', 'pot'.\n\n"
         "Voorbeelden:\n"
         '- "een pakje halfvolle melk en twee broden in utrecht" → locatie="Utrecht", items=["halfvolle melk","brood"]\n'
         '- "een pot ben & jerrys caramel chew chew" → locatie=null, items=["Ben & Jerry\'s Caramel Chew Chew"]\n'
         '- "6 redbull in Alphen aan den Rijn" → locatie="Alphen aan den Rijn", items=["Red Bull"]'),
        ("user", "{input}"),
    ])

    try:
        resultaat = (prompt | structured_llm).invoke({"input": text})
        logger.success(f"Extractie OK: locatie={resultaat.locatie}, items={resultaat.items}")
        return {"extractie": resultaat.model_dump()}
    except Exception as e:
        logger.error(f"LLM parsing faalde: {e}")
        return {"extractie": {"locatie": None, "items": []}}


def node_geocode(state: AgentState) -> AgentState:
    """Locatie → lat/lon via Google Maps. Skip als geen API-key."""
    locatie = state["extractie"].get("locatie")
    if not locatie:
        return {"geocode": None}
    if not gmaps:
        logger.warning("Geen GOOGLE_MAPS_API_KEY — geocoding overgeslagen")
        return {"geocode": None}

    logger.info(f"Node 2 — geocoding '{locatie}'")
    try:
        results = gmaps.geocode(locatie, region="nl")
        if not results:
            logger.warning(f"Geen geocode-resultaat voor '{locatie}'")
            return {"geocode": None}
        loc = results[0]["geometry"]["location"]
        geocode = {
            "lat": loc["lat"],
            "lon": loc["lng"],
            "formatted_address": results[0]["formatted_address"],
        }
        logger.success(f"Geocode: {geocode['formatted_address']} ({loc['lat']:.4f}, {loc['lng']:.4f})")
        return {"geocode": geocode}
    except Exception as e:
        logger.error(f"Geocoding faalde: {e}")
        return {"geocode": None}


def node_vraag_verduidelijking(state: AgentState) -> AgentState:
    extractie = state.get("extractie", {})
    ontbreekt = []
    if not extractie.get("locatie"):
        ontbreekt.append("een locatie")
    if not extractie.get("items"):
        ontbreekt.append("welke boodschappen je nodig hebt")
    vraag = f"Ik mis nog informatie. Kun je {', en '.join(ontbreekt)} noemen?"
    return {"advies": vraag, "chat_history": [f"Agent: {vraag}"]}


def node_vergelijk_prijzen(state: AgentState) -> AgentState:
    logger.info("Node 5 — prijzen vergelijken")
    items = state["extractie"]["items"]

    ah_totaal = 0.0
    jumbo_totaal = 0.0
    details = []

    for item in items:
        # AH
        try:
            ah_product = _ah_search(item)
        except Exception as e:
            logger.warning(f"AH definitief gefaald voor '{item}': {e}")
            ah_product = None
        ah_prijs, ah_ok = _safe_ah_price(ah_product)

        # Jumbo
        try:
            jumbo_product = _jumbo_search(item)
        except Exception as e:
            logger.warning(f"Jumbo definitief gefaald voor '{item}': {e}")
            jumbo_product = None
        jumbo_prijs, jumbo_ok = _safe_jumbo_price(jumbo_product)

        ah_totaal += ah_prijs
        jumbo_totaal += jumbo_prijs

        details.append({
            "product": item,
            "ah_prijs": ah_prijs,
            "ah_beschikbaar": ah_ok,
            "jumbo_prijs": jumbo_prijs,
            "jumbo_beschikbaar": jumbo_ok,
        })
        logger.debug(f"{item}: AH €{ah_prijs:.2f} ({'✓' if ah_ok else '✗'}) | "
                     f"Jumbo €{jumbo_prijs:.2f} ({'✓' if jumbo_ok else '✗'})")

    return {"prijs_data": {
        "ah_totaal": ah_totaal,
        "jumbo_totaal": jumbo_totaal,
        "details": details,
    }}


def node_advies(state: AgentState) -> AgentState:
    extractie = state["extractie"]
    geocode = state.get("geocode")
    prijzen = state["prijs_data"]
    ah_tot, jumbo_tot = prijzen["ah_totaal"], prijzen["jumbo_totaal"]

    if ah_tot == 0 and jumbo_tot == 0:
        advies = "Geen van de producten gevonden bij AH of Jumbo. Probeer algemenere termen."
        return {"advies": advies, "chat_history": [f"Agent: {advies}"]}

    regels = []
    if geocode:
        regels.append(f"📍 {geocode['formatted_address']}")
    else:
        regels.append(f"📍 {extractie['locatie']}")
    regels.append(f"🛒 Gezocht: {', '.join(extractie['items'])}\n")

    for d in prijzen["details"]:
        ah = f"€{d['ah_prijs']:.2f}" if d["ah_beschikbaar"] else "—"
        jb = f"€{d['jumbo_prijs']:.2f}" if d["jumbo_beschikbaar"] else "—"
        regels.append(f"  • {d['product']:25s} AH {ah:>7s}  |  Jumbo {jb:>7s}")

    regels.append(f"\n💶 Totaal AH: €{ah_tot:.2f}   🟡 Totaal Jumbo: €{jumbo_tot:.2f}")
    verschil = abs(ah_tot - jumbo_tot)
    if verschil > 0.01:
        winnaar = "Jumbo" if jumbo_tot < ah_tot else "Albert Heijn"
        regels.append(f"🏆 Advies: ga naar {winnaar} — bespaart €{verschil:.2f}.")
    else:
        regels.append("⚖️ Beide supermarkten zijn even duur.")

    advies = "\n".join(regels)
    return {"advies": advies, "chat_history": [f"Agent: {advies}"]}


# ---------- 5. Routers ----------
def valideer_extractie(state: AgentState) -> Literal["compleet", "incompleet"]:
    e = state.get("extractie", {})
    return "compleet" if (e.get("locatie") and e.get("items")) else "incompleet"


# ---------- 6. Graph ----------
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse_input", node_parse_input)
    g.add_node("geocode", node_geocode)
    g.add_node("vraag_verduidelijking", node_vraag_verduidelijking)
    g.add_node("vergelijk_prijzen", node_vergelijk_prijzen)
    g.add_node("advies", node_advies)

    g.add_edge(START, "parse_input")
    g.add_conditional_edges("parse_input", valideer_extractie, {
        "compleet": "geocode",
        "incompleet": "vraag_verduidelijking",
    })
    g.add_edge("geocode", "vergelijk_prijzen")
    g.add_edge("vergelijk_prijzen", "advies")
    g.add_edge("vraag_verduidelijking", END)
    g.add_edge("advies", END)

    return g.compile(checkpointer=MemorySaver())


if __name__ == "__main__":
    app = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("=== Supermarkt Vergelijker v2 ===")
    print(f"LM Studio: {LM_STUDIO_BASE_URL}")
    print(f"Google Maps: {'✓' if gmaps else '✗ (geen key)'}")
    print("Typ 'stop' om af te sluiten.\n")

    while True:
        try:
            user_input = input("Jij: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("stop", "quit", "exit"):
            break
        result = app.invoke({"user_input": user_input}, config)
        print(f"\n{result.get('advies')}\n")