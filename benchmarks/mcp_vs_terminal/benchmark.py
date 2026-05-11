import asyncio
import os
import json
import time
import pandas as pd
from typing import Any, Dict, List, Optional
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv
from mcp_client import MCPStataClient
from terminal_client import TerminalStataClient
from tabulate import tabulate

from db import init_db, create_run, save_result, save_artifact, get_run_results

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("Warning: GEMINI_API_KEY not found in environment.")

MODEL_NAME = "gemini-3-flash-preview"


class BenchmarkHarness:
    def __init__(self, model_name: str = MODEL_NAME, notes: str = None):
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self.results = []

        # Initialise DB and create a stamped run for this session
        init_db()
        self.run_id = create_run(model_name=self.model_name, notes=notes)
        print(f"Benchmark run ID: {self.run_id}")

        # Ensure we persist a full run log to disk (and DB) for later ingestion/debugging.
        Path("results").mkdir(exist_ok=True)
        self._run_log_path = Path("results") / f"{self.run_id}.log"
        self._run_log_fh = self._run_log_path.open("w", encoding="utf-8")

    def _log(self, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._run_log_fh.write(line)
        self._run_log_fh.flush()

    async def run_sanity_check(self):
        print("\n--- Running Step 0: Token Counting Sanity Check ---")
        prompt = (
            'Respond with exactly this sentence and nothing else: '
            '"The quick brown fox jumps over the lazy dog."'
        )
        response = self.client.models.generate_content(
            model=self.model_name, contents=prompt
        )
        usage = response.usage_metadata
        print(f"Input tokens:  {usage.prompt_token_count}")
        print(f"Output tokens: {usage.candidates_token_count}")
        print(f"Response: {response.text}")
        self._log("Sanity check completed.")
        return usage

    async def run_task(self, approach: str, task: Dict[str, Any], max_turns: int = 15):
        print(f"\n--- Running Task {task['id']} ({approach}) ---")

        if approach == "mcp":
            async with MCPStataClient(".") as client:
                tools = await client.get_tools()
                gemini_tools = self._convert_tools_to_gemini(tools)
                return await self._run_loop(approach, task, gemini_tools, client, max_turns)
        else:
            work_dir = Path("results") / "work" / self.run_id / task["id"]
            client = TerminalStataClient(str(work_dir))
            tools = client.get_tools()
            gemini_tools = self._convert_tools_to_gemini(tools)
            return await self._run_loop(approach, task, gemini_tools, client, max_turns)

    async def _run_loop(self, approach, task, tools, client, max_turns):
        history = []
        total_input = 0
        total_output = 0
        turn_count = 0
        response = None

        history.append(types.Content(role="user", parts=[types.Part(text=task["prompt"])]))
        self._log(f"Task {task['id']} start approach={approach}")
        self._log(f"User prompt:\n{task['prompt']}")

        while turn_count < max_turns:
            turn_count += 1
            print(f"  Turn {turn_count}...")
            self._log(f"Turn {turn_count} begin")

            try:
                config = None
                if tools:
                    config = types.GenerateContentConfig(
                        tools=[types.Tool(function_declarations=tools)]
                    )
                response = self.client.models.generate_content(
                    model=self.model_name, contents=history, config=config
                )
            except Exception as e:
                print(f"    Error calling Gemini: {e}")
                break

            usage = response.usage_metadata
            total_input += usage.prompt_token_count
            total_output += usage.candidates_token_count
            self._log(
                f"Usage: +in={usage.prompt_token_count} +out={usage.candidates_token_count}"
            )

            model_content = response.candidates[0].content
            history.append(model_content)

            tool_calls = [
                part.function_call
                for part in model_content.parts
                if part.function_call
            ]

            if not tool_calls:
                print("    Model finished (no more tool calls).")
                if response and response.text:
                    self._log(f"Model final response:\n{response.text}")
                break

            function_responses = []
            for fc in tool_calls:
                name = fc.name
                args = fc.args
                print(f"    Calling tool: {name}({args})")
                self._log(f"Tool call: {name}({args})")

                if approach == "mcp":
                    result = await client.call_tool(name, args)
                else:
                    result = client.execute_bash(args["command"])

                log_result = (result[:100] + "...") if len(result) > 100 else result
                print(f"    Result: {log_result}")
                self._log(f"Tool result (truncated to 4k):\n{result[:4000]}")

                function_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=name, response={"result": result}
                        )
                    )
                )

            history.append(types.Content(role="user", parts=function_responses))

        result = {
            "run_id": self.run_id,
            "approach": approach,
            "task_id": task["id"],
            "input_tokens": total_input,
            "output_tokens": total_output,
            "turns": turn_count,
            "final_response": (
                response.text if response and response.text else "(Tool Call Only)"
            ),
        }

        # Persist to SQLite immediately after each task
        save_result(self.run_id, result)
        self._log(
            f"Task {task['id']} end approach={approach} turns={turn_count} "
            f"input_tokens={total_input} output_tokens={total_output}"
        )
        return result

    def close(self):
        try:
            self._run_log_fh.close()
        finally:
            # Also store the run log into the DB so it is always linked to the run_id.
            text = self._run_log_path.read_text(errors="replace")
            save_artifact(
                self.run_id,
                kind="run_log",
                filename=self._run_log_path.name,
                content_text=text,
                bytes=self._run_log_path.stat().st_size,
            )

    def _convert_tools_to_gemini(self, mcp_tools):
        return [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=tool["input_schema"],
            )
            for tool in mcp_tools
        ]


async def main():
    harness = BenchmarkHarness(notes="CLI run")

    try:
        await harness.run_sanity_check()

        with open("tasks.json") as f:
            tasks_data = json.load(f)

        all_results = []
        os.makedirs("results", exist_ok=True)

        for group in ["T1", "T2"]:
            for task in tasks_data[group]:
                mcp_res = await harness.run_task("mcp", task)
                term_res = await harness.run_task("terminal", task)
                all_results.append(mcp_res)
                all_results.append(term_res)

        # Also write a per-run JSON snapshot alongside the DB
        out_path = f"results/{harness.run_id}.json"
        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nResults snapshot: {out_path}")

        # Summary table
        df = pd.DataFrame(all_results)
        summary = df.pivot(
            index="task_id",
            columns="approach",
            values=["input_tokens", "output_tokens", "turns"],
        )
        print("\n--- Benchmark Summary ---")
        print(tabulate(summary, headers="keys", tablefmt="grid"))
        print(f"\nRun ID: {harness.run_id}  (stored in benchmarks.db)")
    finally:
        harness.close()


if __name__ == "__main__":
    asyncio.run(main())
