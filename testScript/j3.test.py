import uuid
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from operator import add

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from supermarktconnector.ah import AHConnector
from supermarktconnector.jumbo import JumboConnector

# ---------- 1. Pydantic Schemas ----------
class ExtractieResultaat(BaseModel):
    locatie: Optional[str] = Field(description="De stad, het dorp of de locatie. Leeg/null als het niet is genoemd.")
    items: list[str] = Field(description="Een gestandaardiseerde lijst met losse basisproducten.")

# ---------- 2. State ----------
class AgentState(TypedDict, total=False):
    user_input: str
    extractie: Optional[dict]  # GEWIJZIGD: Nu een standaard dict om de msgpack warning te voorkomen!
    prijs_data: Optional[dict]
    advies: Optional[str]
    chat_history: Annotated[list[str], add]

# ---------- 3. Nodes ----------

def node_parse_input(state: AgentState) -> AgentState:
    print("[Agent]: Boodschappenlijst en locatie extraheren...")
    text = state.get("user_input", "")
    
    llm = ChatOpenAI(
        base_url="http://localhost:1234/v1", 
        api_key="lm-studio", 
        model="local-model", 
        temperature=0.1
    )
    
    structured_llm = llm.with_structured_output(ExtractieResultaat)
    
    # HIER ZIT DE FEW-SHOT PROMPT
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Jij bent een strenge data-extractor voor een supermarkt API.
        Haal de locatie en de boodschappen uit de tekst.
        Zet de items om naar schone, merkgerichte of algemene zoektermen zonder overbodige woorden zoals 'een', 'pak', 'fles', 'blik' of 'pot'.
        
        Voorbeelden:
        - Input: "een pakje halfvolle melk en twee broden in utrecht"
          Output: locatie: "Utrecht", items: ["halfvolle melk", "brood"]
        - Input: "een pot ben & jerrys caramel chew chew"
          Output: locatie: null, items: ["Ben & Jerry's Caramel Chew Chew"]
        - Input: "6 redbull in Alphen aan den Rijn"
          Output: locatie: "Alphen aan den Rijn", items: ["Red Bull"]
        """),
        ("user", "{input}")
    ])
    
    chain = prompt | structured_llm
    
    try:
        resultaat = chain.invoke({"input": text})
        # .model_dump() zet het Pydantic object om naar een veilige dict voor LangGraph
        return {"extractie": resultaat.model_dump()} 
    except Exception as e:
        print(f"[Fout] LLM parsing faalde: {e}")
        return {"extractie": {"locatie": None, "items": []}}

def node_vraag_verduidelijking(state: AgentState) -> AgentState:
    extractie = state.get("extractie", {})
    ontbreekt = []
    
    if not extractie.get("locatie"):
        ontbreekt.append("een locatie")
    if not extractie.get("items"):
        ontbreekt.append("welke boodschappen je nodig hebt")
        
    vraag = f"Ik mis nog wat informatie. Zou je {', en '.join(ontbreekt)} kunnen noemen in je antwoord?"
    return {"advies": vraag, "chat_history": [f"Agent: {vraag}"]}

def node_vergelijk_prijzen(state: AgentState) -> AgentState:
    print("[Agent]: Live prijzen ophalen via SupermarktConnector...")
    items = state["extractie"]["items"]
    
    ah = AHConnector()
    jumbo = JumboConnector()
    
    ah_totaal = 0.0
    jumbo_totaal = 0.0
    details = []
    
    for item in items:
        ah_prijs = 0.0
        jumbo_prijs = 0.0
        
        # --- 1. AH Prijs ---
        print(f"  [Debug] Start AH zoekopdracht voor: '{item}'...")
        try:
            ah_results = ah.search_products(query=item, size=1, page=0)
            if ah_results and ah_results.get('products') and len(ah_results['products']) > 0:
                ah_prijs = ah_results['products'][0].get('currentPrice', 0.0) 
            print(f"  [Debug] AH succesvol voor: '{item}'")
        except Exception as e:
            print(f"  [Waarschuwing] AH API faalde voor '{item}': {e}")

        # --- 2. Jumbo Prijs ---
        print(f"  [Debug] Start Jumbo zoekopdracht voor: '{item}'...")
        try:
            jumbo_results = jumbo.search_products(query=item, size=1, page=0)
            if jumbo_results and 'products' in jumbo_results and 'data' in jumbo_results['products'] and len(jumbo_results['products']['data']) > 0:
                p_data = jumbo_results['products']['data'][0]['prices']['price']['amount']
                jumbo_prijs = p_data / 100.0 if p_data >= 100 else float(p_data)
            print(f"  [Debug] Jumbo succesvol voor: '{item}'")
        except Exception as e:
            print(f"  [Waarschuwing] Jumbo API faalde voor '{item}': {e}")
            
        ah_totaal += ah_prijs
        jumbo_totaal += jumbo_prijs
        
        details.append({
            "product": item,
            "ah_prijs": ah_prijs,
            "jumbo_prijs": jumbo_prijs
        })
        
    return {
        "prijs_data": {
            "ah_totaal": ah_totaal,
            "jumbo_totaal": jumbo_totaal,
            "details": details
        }
    }

def node_advies(state: AgentState) -> AgentState:
    locatie = state["extractie"]["locatie"]
    items = state["extractie"]["items"]
    prijzen = state["prijs_data"]
    
    ah_tot = prijzen["ah_totaal"]
    jumbo_tot = prijzen["jumbo_totaal"]
    
    # Check of we überhaupt prijzen hebben gevonden
    if ah_tot == 0 and jumbo_tot == 0:
        advies = "Ik kon de prijzen voor deze producten niet vinden in de systemen van AH en Jumbo. Misschien zijn de producten te specifiek?"
        return {"advies": advies, "chat_history": [f"Agent: {advies}"]}

    verschil = abs(ah_tot - jumbo_tot)
    goedkoopste = "Jumbo" if jumbo_tot < ah_tot else "Albert Heijn"
    
    advies_regels = [f"📍 Locatie: {locatie.capitalize()}"]
    advies_regels.append(f"🛒 Ik heb gezocht naar: {', '.join(items)}.\n")
    
    for detail in prijzen["details"]:
        advies_regels.append(f"   - {detail['product']}: AH €{detail['ah_prijs']:.2f} | Jumbo €{detail['jumbo_prijs']:.2f}")
        
    advies_regels.append(f"\n💶 Totaal AH: €{ah_tot:.2f} | 🟡 Totaal Jumbo: €{jumbo_tot:.2f}")
    
    if verschil > 0:
        advies_regels.append(f"🏆 Advies: Ga naar de {goedkoopste}, dat scheelt je €{verschil:.2f}.")
    else:
        advies_regels.append("⚖️ Advies: Beide supermarkten zijn exact even duur voor deze lijst.")
              
    advies = "\n".join(advies_regels)
    return {"advies": advies, "chat_history": [f"Agent: {advies}"]}

# ---------- 4. Validatie ----------
def valideer_extractie(state: AgentState) -> Literal["compleet", "incompleet"]:
    extractie = state.get("extractie", {})
    if extractie.get("locatie") and extractie.get("items"):
        return "compleet"
    return "incompleet"

# ---------- 5. Graph Compositie ----------
def build_graph():
    g = StateGraph(AgentState)

    g.add_node("parse_input", node_parse_input)
    g.add_node("vraag_verduidelijking", node_vraag_verduidelijking)
    g.add_node("vergelijk_prijzen", node_vergelijk_prijzen)
    g.add_node("advies", node_advies)

    g.add_edge(START, "parse_input")
    g.add_conditional_edges(
        "parse_input",
        valideer_extractie,
        {
            "compleet": "vergelijk_prijzen",
            "incompleet": "vraag_verduidelijking",
        },
    )
    g.add_edge("vergelijk_prijzen", "advies")
    g.add_edge("vraag_verduidelijking", END)
    g.add_edge("advies", END)

    memory = MemorySaver()
    return g.compile(checkpointer=memory)

if __name__ == "__main__":
    app = build_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("=== Supermarkt Vergelijker (Echte API Editie) ===")
    print("Typ 'stop' om af te sluiten.\n")

    while True:
        user_input = input("Jij: ")
        if user_input.lower() in ['stop', 'quit', 'exit']:
            break

        result = app.invoke({"user_input": user_input}, config)
        print(f"\n{result.get('advies')}\n")