from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from google import genai
from google.genai import types

from mcp_client import MCPStataClient
from terminal_client import TerminalStataClient

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")

MODEL_NAME = "gemini-3-flash-preview"


class BenchmarkHarness:
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self.results = []
        self.run_id = f"run_{uuid.uuid4().hex[:10]}"
        self.created_at = datetime.now(timezone.utc).isoformat()

    async def run_sanity_check(self):
        prompt = 'Respond with exactly this sentence and nothing else: "The quick brown fox jumps over the lazy dog."'
        response = self.client.models.generate_content(model=self.model_name, contents=prompt)
        return response.usage_metadata

    async def run_task(self, approach: str, task: Dict[str, Any], max_turns: int = 15):
        if approach == "mcp":
            async with MCPStataClient(".") as client:
                tools = await client.get_tools()
                gemini_tools = self._convert_tools_to_gemini(tools)
                return await self._run_loop(approach, task, gemini_tools, client, max_turns)

        work_dir = os.path.join("results", "work", self.run_id, task["id"])
        client = TerminalStataClient(work_dir)
        tools = client.get_tools()
        gemini_tools = self._convert_tools_to_gemini(tools)
        return await self._run_loop(approach, task, gemini_tools, client, max_turns)

    async def _run_loop(self, approach, task, tools, client, max_turns):
        history = []
        total_input = 0
        total_output = 0
        turn_count = 0

        history.append(types.Content(role="user", parts=[types.Part(text=task["prompt"])]))

        response = None
        while turn_count < max_turns:
            turn_count += 1

            config = None
            if tools:
                config = types.GenerateContentConfig(tools=[types.Tool(function_declarations=tools)])

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=history,
                config=config,
            )

            usage = response.usage_metadata
            total_input += usage.prompt_token_count
            total_output += usage.candidates_token_count

            model_content = response.candidates[0].content
            history.append(model_content)

            tool_calls = [part.function_call for part in model_content.parts if part.function_call]
            if not tool_calls:
                break

            function_responses = []
            for fc in tool_calls:
                name = fc.name
                args = fc.args

                if approach == "mcp":
                    result = await client.call_tool(name, args)
                else:
                    result = client.execute_bash(args["command"])

                function_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=name,
                            response={"result": result},
                        )
                    )
                )

            history.append(types.Content(role="user", parts=function_responses))

        return {
            "run_id": self.run_id,
            "model_name": self.model_name,
            "created_at": self.created_at,
            "approach": approach,
            "task_id": task["id"],
            "input_tokens": total_input,
            "output_tokens": total_output,
            "turns": turn_count,
            "final_response": response.text if response and response.text else "(Tool Call Only)",
        }

    def _convert_tools_to_gemini(self, mcp_tools):
        gemini_tools = []
        for tool in mcp_tools:
            gemini_tools.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=tool["input_schema"],
                )
            )
        return gemini_tools


async def main():
    harness = BenchmarkHarness()
    await harness.run_sanity_check()

    with open("tasks.json", "r", encoding="utf-8") as f:
        tasks_data = json.load(f)

    all_results = []
    os.makedirs("results", exist_ok=True)

    for group in ["T1", "T2"]:
        for task in tasks_data[group]:
            mcp_res = await harness.run_task("mcp", task)
            term_res = await harness.run_task("terminal", task)
            all_results.append(mcp_res)
            all_results.append(term_res)

    # Write a per-run snapshot (do not overwrite prior runs)
    out_path = f"results/{harness.run_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())

