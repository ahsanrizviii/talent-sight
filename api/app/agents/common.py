from typing import TypedDict

class AgentState(TypedDict, total=False):
    error: str  

def has_error(state: AgentState) -> bool:
    return bool(state.get("error"))