import json
import urllib.request  # Built-in Python library for HTTP calls (MC-5)
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

# ==========================================
# DEFINITIONS & SCHEMAS (MC-8: Structured JSON)
# ==========================================
class GroceryItem(BaseModel):
    name: str
    quantity: str

class StructuredGroceryList(BaseModel):
    items: List[GroceryItem]

# MC-3: Define the Shared Graph State (Preserved across all steps)
class WorkflowState(dict):
    raw_input: str                  # Filled in Step 1
    location_coords: Optional[str]  # Filled in Step 2
    parsed_list: Optional[StructuredGroceryList] # Filled in Step 3
    found_stores: Optional[list]    # Filled in Step 4
    price_data: Optional[dict]      # Filled in Step 5
    loop_counter: int               # Control variable to demonstrate looping

# Initialize local LM Studio reference (MC-6 & MC-9: €0 Cost)
llm = ChatOpenAI(
    base_url="http://localhost:1234/v1",  
    api_key="lm-studio",                  
    model="llama-3.2-3b-instruct",     
    temperature=0
)
structured_llm = llm.with_structured_output(StructuredGroceryList, method="json_schema")


# ==========================================
# SEQUENTIAL WORKFLOW NODES (MC-2: Min 5 Steps)
# ==========================================

def step_1_user_input(state: WorkflowState):
    print("\n[Step 1] Gebruiker Input Ontvangen")
    # State is initialized here
    return {"raw_input": state["raw_input"], "loop_counter": 0}

def step_2_determine_location(state: WorkflowState):
    print("[Step 2] Locatie Bepalen (Mock Geocoding)...")
    # Accessing data from step 1 to prove data preservation
    assert state.get("raw_input") is not None
    return {"location_coords": "52.0907, 5.1214"} # Coordinates for Utrecht

def step_3_parse_shopping_list(state: WorkflowState):
    print("[Step 3] Boodschappen Lijst Structureren via LLM...")
    user_text = state.get("raw_input")
    structured_result = structured_llm.invoke(f"Extract items: {user_text}")
    return {"parsed_list": structured_result}

def step_4_search_stores(state: WorkflowState):
    # This step is target for our loop repair action
    current_count = state.get("loop_counter", 0)
    print(f"[Step 4] Winkels Zoeken op afstand (Run index: {current_count})...")
    
    # Simulate finding different stores if we are inside a loop
    stores = ["Albert Heijn", "Jumbo"] if current_count == 0 else ["Albert Heijn XL", "Lidl", "Aldi"]
    return {"found_stores": stores}

def step_5_lookup_prices(state: WorkflowState):
    print("[Step 5] Prijzen Opzoeken via Externe API...")
    
    # MC-5: Real external HTTP-call demonstration 
    # Using a free public testing API endpoint to simulate your SupermarktConnector
    try:
        url = "https://jsonplaceholder.typicode.com/todos/1" 
        with urllib.request.urlopen(url, timeout=5) as response:
            mock_api_data = json.loads(response.read().decode())
            print(f"  -> HTTP Call Success! SupermarktConnector status code: {response.status}")
    except Exception as e:
        print(f"  -> HTTP Call Failed: {e}")

    # Accessing data preserved from Step 1 & Step 3 to prove MC-3
    print(f"  -> Checking list items for: {[i.name for i in state['parsed_list'].items]}")
    
    # Simulate a validation checkpoint logic
    # If it's our first pass, we force a "Failed validation" to test our loop rule
    if state["loop_counter"] == 0:
        print("  -> [VALIDATION FAILED]: Missing price indices for discount brands. Triggering loop!")
        return {"price_data": None, "loop_counter": state["loop_counter"] + 1}
    else:
        print("  -> [VALIDATION PASSED]: All competitive prices collected.")
        return {"price_data": {"total_price": 14.50}}


# ==========================================
# MC-7: CONDITIONAL ROUTING ROUTER
# ==========================================
def validation_router(state: WorkflowState):
    """Evaluates the state to route forward or loop backward."""
    if state.get("price_data") is None:
        return "loop_to_store_search"
    return "continue_to_end"


# ==========================================
# GRAPH ASSEMBLY
# ==========================================
workflow = StateGraph(WorkflowState)

# Register our 5 sequential nodes
workflow.add_node("step_1", step_1_user_input)
workflow.add_node("step_2", step_2_determine_location)
workflow.add_node("step_3", step_3_parse_shopping_list)
workflow.add_node("step_4", step_4_search_stores)
workflow.add_node("step_5", step_5_lookup_prices)

# Layout connections
workflow.add_edge(START, "step_1")
workflow.add_edge("step_1", "step_2")
workflow.add_edge("step_2", "step_3")
workflow.add_edge("step_3", "step_4")
workflow.add_edge("step_4", "step_5")

# MC-4 & MC-7: Conditional loop logic configuration
workflow.add_conditional_edges(
    "step_5",
    validation_router,
    {
        "loop_to_store_search": "step_4",  # Loops back to step 4 execution branch
        "continue_to_end": END
    }
)

app = workflow.compile()

# ==========================================
# RUNNING THE SIMULATION
# ==========================================
if __name__ == "__main__":
    input_payload = {"raw_input": "3 apples, 2 milk"}
    final_state = app.invoke(input_payload)
    print("\n--- WORKFLOW SIMULATION COMPLETE ---")
    print(f"Final State saved loop count: {final_state['loop_counter']}")
    print(f"Final State found stores list: {final_state['found_stores']}")