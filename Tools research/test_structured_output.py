import os
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

load_dotenv()

class GroceryItem(BaseModel):
    name: str = Field(description="The clean, singular name of the grocery item.")
    quantity: str = Field(description="The amount or count requested (e.g., '3', '1 carton', 'some').")
    category: Optional[str] = Field(description="E.g., fruit, dairy, meat, bakery if clear.")

class StructuredGroceryList(BaseModel):
    """The final structured JSON representation of the user's shopping list."""
    items: List[GroceryItem]

class WorkflowState(dict):
    raw_input: str
    parsed_list: Optional[StructuredGroceryList]



llm = ChatOpenAI(
    base_url="http://localhost:1234/v1",  # LM Studio's default local address
    api_key="lm-studio",                  # LM Studio doesn't care what string you put here
    model="llama-3.2-3b-instruct",     # Put the exact name of the model loaded in LM Studio
    temperature=0
)

structured_llm = llm.with_structured_output(
    StructuredGroceryList,
    method="json_schema"  # Swapping to json_mode forces the prompt to instruct the local model
)


# 5. Define the Node Functions
def parse_shopping_list_node(state: WorkflowState):
    """The node responsible for converting raw input into structural data."""
    print("--- Running Node: Parsing Shopping List ---")
    
    # Extract data from state
    user_text = state.get("raw_input")
    
    # Invoke the structured LLM model
    structured_result = structured_llm.invoke(
        f"Extract the grocery items from this list: {user_text}"
    )
    
    # Return the updated dictionary to modify the graph state
    return {"parsed_list": structured_result}


# 6. Assemble and Compile the LangGraph
workflow = StateGraph(WorkflowState)

# Add our node to the graph
workflow.add_node("parser_node", parse_shopping_list_node)

# Define the flow (Edges)
workflow.add_edge(START, "parser_node")
workflow.add_edge("parser_node", END)

# Compile the graph into an executable agent application
app = workflow.compile()


# 7. Execute the Test Invocations
if __name__ == "__main__":
    # Simulate step 1/2 raw input
    test_input = "Hoi, Ik wil 2 appels, 1 liter melk, en een volkoren brood kopen."
    
    print(f"User Input text: '{test_input}'\n")
    
    # Run the graph
    final_output = app.invoke({"raw_input": test_input})
    
    print("\n--- Final Graph Results ---")
    parsed_data = final_output.get("parsed_list")
    
    if parsed_data:
        # It is now a fully validated Python Pydantic object!
        print("Success! Data is structured and validated against your Pydantic schema:")
        print(parsed_data.model_dump_json(indent=2))
        
        # You can access elements using standard object dot notation:
        print(f"\nFirst item category: {parsed_data.items[0].category}")
    else:
        print("Failed to structure data.")