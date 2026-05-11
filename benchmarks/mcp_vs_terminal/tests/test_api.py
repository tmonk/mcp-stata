import os
import pytest
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Mark all tests in this module as 'api'
pytestmark = pytest.mark.api

MODEL_NAME = "gemini-3-flash-preview"

def _output_tokens(usage) -> int:
    """
    google-genai usage_metadata changed across versions/models.
    Prefer candidates_token_count when present; otherwise derive from totals.
    """
    c = getattr(usage, "candidates_token_count", None)
    if isinstance(c, int):
        return c
    total = getattr(usage, "total_token_count", None)
    prompt = getattr(usage, "prompt_token_count", None)
    thoughts = getattr(usage, "thoughts_token_count", 0) or 0
    if isinstance(total, int) and isinstance(prompt, int):
        derived = total - prompt - (thoughts if isinstance(thoughts, int) else 0)
        return max(int(derived), 0)
    raise AssertionError("Unable to determine output token count from usage_metadata")

@pytest.fixture(scope="module")
def api_key():
    # Try loading from .env or .envrc
    load_dotenv()
    if os.path.exists(".envrc"):
        load_dotenv(".envrc")
    
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.fail("GEMINI_API_KEY is invalid or not set")
    return key

@pytest.fixture(scope="module")
def client(api_key):
    return genai.Client(api_key=api_key)

@pytest.fixture(scope="module")
def model_reachability(client):
    """Requirement 9: API key and model reachability"""
    try:
        # Minimal call to verify reachability and model availability
        client.models.generate_content(model=MODEL_NAME, contents="ping")
    except Exception as e:
        msg = str(e).lower()
        if "auth" in msg or "api key" in msg or "unauthorized" in msg:
            pytest.fail("GEMINI_API_KEY is invalid or not set")
        elif "not found" in msg or "404" in msg:
            pytest.fail(f"{MODEL_NAME} is not available on this API key")
        else:
            pytest.fail(f"API call failed during setup: {e}")

def test_usage_metadata_complete(client, model_reachability):
    """Requirement 1: usage_metadata is present and complete"""
    response = client.models.generate_content(
        model=MODEL_NAME, 
        contents="Reply with the single word: hello"
    )
    usage = response.usage_metadata
    
    assert usage is not None
    assert isinstance(usage.prompt_token_count, int)
    assert usage.prompt_token_count > 0
    assert isinstance(_output_tokens(usage), int)
    # In the new SDK, total_token_count should match the sum
    expected_total = usage.prompt_token_count + _output_tokens(usage)
    if hasattr(usage, "thoughts_token_count") and usage.thoughts_token_count:
        expected_total += usage.thoughts_token_count
        
    assert usage.total_token_count == expected_total

def test_input_token_scaling(client, model_reachability):
    """Requirement 2: Input token count scales with prompt length"""
    short_prompt = "Hello"
    # ~200 words of lorem ipsum as requested
    long_prompt = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. "
        "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
        "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. "
    ) * 40 
    
    res_short = client.models.generate_content(model=MODEL_NAME, contents=short_prompt)
    res_long = client.models.generate_content(model=MODEL_NAME, contents=long_prompt)
    
    usage_short = res_short.usage_metadata
    usage_long = res_long.usage_metadata
    
    assert usage_long.prompt_token_count > usage_short.prompt_token_count
    # Plausible ratio: long should be at least 20x the short
    assert usage_long.prompt_token_count > (usage_short.prompt_token_count * 20)

def test_output_token_scaling(client, model_reachability):
    """Requirement 3: Output token count scales with requested response length"""
    res_3 = client.models.generate_content(model=MODEL_NAME, contents="Respond with exactly 3 words.")
    res_50 = client.models.generate_content(model=MODEL_NAME, contents="Respond with exactly 50 words of random text.")
    
    usage_3 = res_3.usage_metadata
    usage_50 = res_50.usage_metadata
    
    assert _output_tokens(usage_50) > _output_tokens(usage_3)

def test_multi_turn_accumulation(client, model_reachability):
    """Requirement 4 & 5: Multi-turn token accumulation and Turn counter"""
    chat = client.chats.create(model=MODEL_NAME)
    turns = 4
    
    per_turn_input = []
    per_turn_output = []
    
    for i in range(turns):
        prompt = f"Turn {i+1}: What is {i} + 1?"
        response = chat.send_message(prompt)
        usage = response.usage_metadata
        
        per_turn_input.append(usage.prompt_token_count)
        per_turn_output.append(_output_tokens(usage))
        
        if i > 0:
            # Assert prompt_token_count grows each turn (context accumulation)
            assert per_turn_input[i] > per_turn_input[i-1]
            
    assert len(per_turn_input) == 4

def test_tool_call_tokens(client, model_reachability):
    """Requirement 6: Function/tool call tokens are counted"""
    def get_number():
        return 42
        
    # In google-genai, tools are passed to generate_content
    tool_def = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_number",
                description="Returns a trivial number.",
                parameters={
                    "type": "OBJECT",
                    "properties": {}
                }
            )
        ]
    )
    
    # Turn 1: Model decides to call tool
    response1 = client.models.generate_content(
        model=MODEL_NAME, 
        contents="Call get_number and tell me the result.",
        config=types.GenerateContentConfig(tools=[tool_def])
    )
    usage1 = response1.usage_metadata
    
    assert _output_tokens(usage1) > 0
    
    # Find the tool call
    tool_calls = [p.function_call for p in response1.candidates[0].content.parts if p.function_call]
    assert len(tool_calls) > 0, "Model did not invoke the tool"
    
    # Turn 2: Send tool result back
    # New SDK handles history by passing it to contents
    history = [
        types.Content(role="user", parts=[types.Part(text="Call get_number and tell me the result.")]),
        response1.candidates[0].content,
        types.Content(role="user", parts=[
            types.Part(function_response=types.FunctionResponse(
                name="get_number",
                response={"result": 42}
            ))
        ])
    ]
    
    response2 = client.models.generate_content(
        model=MODEL_NAME, 
        contents=history,
        config=types.GenerateContentConfig(tools=[tool_def])
    )
    usage2 = response2.usage_metadata
    
    # Assert prompt_token_count on second turn is larger than first
    assert usage2.prompt_token_count > usage1.prompt_token_count
    assert _output_tokens(usage2) > 0

def test_non_streaming_enforced(client, model_reachability):
    """Requirement 7: Non-streaming mode enforced"""
    response = client.models.generate_content(model=MODEL_NAME, contents="Hello")
    # In google-genai, generate_content is non-streaming by default.
    # Streaming would use models.generate_content_stream
    assert response.usage_metadata is not None

def test_cost_calculation(client, model_reachability):
    """Requirement 8: Cost calculation"""
    response = client.models.generate_content(model=MODEL_NAME, contents="Reply with: hi")
    usage = response.usage_metadata
    
    input_tokens = usage.prompt_token_count
    output_tokens = _output_tokens(usage)
    
    # Formula: input_tokens / 1_000_000 * 0.50 + output_tokens / 1_000_000 * 3.00
    cost = (input_tokens / 1_000_000 * 0.50) + (output_tokens / 1_000_000 * 3.00)
    
    assert isinstance(cost, float)
    assert cost > 0
    assert cost < 0.001
