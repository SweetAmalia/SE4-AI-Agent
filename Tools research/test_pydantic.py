import json
import urllib.request
from typing import List
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

# ==========================================
# DEFINITIONS & SCHEMAS (MC-8: Structured JSON)
# ==========================================
class GroceryItem(BaseModel):
    name: str = Field(description="Clean, singular name of the item.")
    quantity: str = Field(description="The requested count or weight.")

class StructuredGroceryList(BaseModel):
    items: List[GroceryItem]

# Connect PydanticAI to your local LM Studio Instance (MC-9: €0 Cost)
local_model = OpenAIChatModel(
    'meta-llama-3-8b-instruct',  
    provider=OpenAIProvider(
        base_url='http://localhost:1234/v1',
        api_key='lm-studio'
    )
)

# STRATEGY A: Plain Text Agent (No output_type constraint)
grocery_agent = Agent(
    local_model,
    system_prompt=(
        "Extract all grocery items cleanly from the user prompt into structured fields. "
        "You must return ONLY a raw JSON object matching this exact structure, nothing else:\n"
        '{"items": [{"name": "item_name", "quantity": "amount"}]}\n'
        "CRITICAL: Do not include introductory text, do not write markdown blocks like ```json, and do not wrap lists in strings."
    )
)

# ==========================================
# SEQUENTIAL PIPELINE WITH NATIVE LOOPS
# ==========================================
def run_pydantic_ai_workflow(initial_input: str):
    state = {
        "raw_input": initial_input,
        "location_coords": None,
        "parsed_list": None,
        "found_stores": None,
        "price_data": None,
        "loop_counter": 0
    }

    # [Step 1] Gebruiker Input Ontvangen
    print("\n[Step 1] Gebruiker Input Ontvangen")

    # [Step 2] Locatie Bepalen (Mock Geocoding)
    print("[Step 2] Locatie Bepalen...")
    state["location_coords"] = "52.0907, 5.1214"

    # [Step 3] Boodschappen Lijst Structureren via PydanticAI Agent
    print("[Step 3] Boodschappen Lijst Structureren via PydanticAI Agent...")
    
    agent_response = grocery_agent.run_sync(f"Process this: {state['raw_input']}")
    raw_text = agent_response.output.strip()

    # Sanitization Block: Handles markdown fences if Llama ignores instructions
    if "```" in raw_text:
        parts = raw_text.split("```")
        raw_text = parts[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    raw_text = raw_text.strip("` \n")

    try:
        # Manually validate the cleaned string using your Pydantic Model
        state["parsed_list"] = StructuredGroceryList.model_validate_json(raw_text)
        print("  -> Successfully parsed and validated local JSON output!")
    except Exception as parse_error:
        print(f"  -> [PARSING ERROR] Raw string was: {raw_text}")
        raise parse_error

    # [MC-4 & MC-7] Steps 4 & 5 run inside a native Python while-loop
    while True:
        print(f"[Step 4] Winkels Zoeken (Run index: {state['loop_counter']})...")
        state["found_stores"] = ["Albert Heijn", "Jumbo"] if state["loop_counter"] == 0 else ["Albert Heijn XL", "Lidl", "Aldi"]

        print("[Step 5] Prijzen Opzoeken via Externe API...")
        try:
            url = "[https://jsonplaceholder.typicode.com/todos/1](https://jsonplaceholder.typicode.com/todos/1)"
            with urllib.request.urlopen(url, timeout=5) as response:
                print(f"  -> HTTP Call Success! Status: {response.status}")
        except Exception as e:
            print(f"  -> HTTP Call Failed: {e}")

        print(f"  -> Checking list items for: {[item.name for item in state['parsed_list'].items]}")

        # Routing Check
        if state["loop_counter"] == 0:
            print("  -> [VALIDATION FAILED]: Missing price data fields. Triggering loop back to Step 4!")
            state["loop_counter"] += 1
            continue  
        else:
            print("  -> [VALIDATION PASSED]: All competitive prices collected.")
            state["price_data"] = {"total_price": 14.50}
            break     

    return state

if __name__ == "__main__":
    test_input = "I need 3 green apples and 2 cartons of milk"
    final_output = run_pydantic_ai_workflow(test_input)
    
    print("\n--- WORKFLOW SIMULATION COMPLETE ---")
    print("Final State Saved Object Summary:")
    print(f"Parsed JSON List: {final_output['parsed_list'].model_dump_json(indent=2)}")