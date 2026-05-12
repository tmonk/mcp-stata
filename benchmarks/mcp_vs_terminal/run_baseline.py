#!/usr/bin/env python3
"""
run_baseline.py – Run the terminal-only baseline benchmark once, store as baseline.

Usage:
    python run_baseline.py

This creates a new run marked is_baseline=1, runs all T1+T2+T3 tasks via
TerminalStataClient, and persists results. The terminal approach is run exactly
once and stored permanently — it is never re-run for subsequent MCP benchmarks.
"""

import asyncio
import os
import sys
import json
import time
import argparse
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from terminal_client import TerminalStataClient
from tabulate import tabulate

from db import init_db, create_run, save_result, save_artifact, get_run_results

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("Warning: GEMINI_API_KEY not found in environment.")

MODEL_NAME = "gemini-3-flash-preview"


def _get_local_version() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    try:
        dirty = subprocess.run(
            ["git", "describe", "--dirty", "--always"],
            cwd=root, capture_output=True, text=True, timeout=10
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root, capture_output=True, text=True, timeout=10
        ).stdout.strip()
        return f"{dirty} ({branch})" if branch else dirty
    except Exception:
        return "unknown"


class BaselineRunner:
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self.run_id = None
        self._run_log_path = None
        self._run_log_fh = None

    def _log(self, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}\n"
        if self._run_log_fh:
            self._run_log_fh.write(line)
            self._run_log_fh.flush()

    async def run_task(self, task: dict, max_turns: int = 15):
        work_dir = Path("results") / "work" / self.run_id / task["id"]
        client = TerminalStataClient(str(work_dir))

        history = []
        total_input = 0
        total_output = 0
        turn_count = 0
        response = None

        history.append(types.Content(role="user", parts=[types.Part(text=task["prompt"])]))
        self._log(f"Task {task['id']} start approach=baseline")

        while turn_count < max_turns:
            turn_count += 1
            print(f"  Turn {turn_count}...")
            self._log(f"Turn {turn_count} begin")

            tools = client.get_tools()
            gemini_tools = self._convert_tools_to_gemini(tools)

            try:
                config = types.GenerateContentConfig(
                    tools=[types.Tool(function_declarations=gemini_tools)]
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
            self._log(f"Usage: +in={usage.prompt_token_count} +out={usage.candidates_token_count}")

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
            "approach": "baseline",
            "task_id": task["id"],
            "input_tokens": total_input,
            "output_tokens": total_output,
            "turns": turn_count,
            "final_response": (
                response.text if response and response.text else "(Tool Call Only)"
            ),
        }
        save_result(self.run_id, result)
        self._log(f"Task {task['id']} end turns={turn_count} input={total_input} output={total_output}")
        return result

    def _convert_tools_to_gemini(self, mcp_tools):
        return [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=tool["input_schema"],
            )
            for tool in mcp_tools
        ]

    def close(self):
        if self._run_log_fh:
            self._run_log_fh.close()
            text = self._run_log_path.read_text(errors="replace")
            save_artifact(
                self.run_id,
                kind="run_log",
                filename=self._run_log_path.name,
                content_text=text,
                bytes=self._run_log_path.stat().st_size,
            )


async def main():
    import subprocess

    parser = argparse.ArgumentParser(description="Run terminal baseline benchmark")
    args = parser.parse_args()

    init_db()
    runner = BaselineRunner()

    run_notes = "Terminal baseline run"
    runner.run_id = create_run(
        model_name=MODEL_NAME,
        notes=run_notes,
        source="live",
        is_baseline=True,
        mcp_version=None,
    )
    print(f"Baseline run ID: {runner.run_id}")

    Path("results").mkdir(exist_ok=True)
    runner._run_log_path = Path("results") / f"{runner.run_id}.log"
    runner._run_log_fh = runner._run_log_path.open("w", encoding="utf-8")

    try:
        with open("tasks.json") as f:
            tasks_data = json.load(f)

        all_results = []

        for group in ["T1", "T2", "T3"]:
            tasks = tasks_data.get(group, [])
            for task in tasks:
                res = await runner.run_task(task)
                all_results.append(res)

        out_path = f"results/{runner.run_id}.json"
        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nResults snapshot: {out_path}")

        import pandas as pd
        df = pd.DataFrame(all_results)
        summary = df.agg(["sum", "mean"]).T
        summary["tokens"] = summary["input_tokens"] + summary["output_tokens"]
        print("\n--- Baseline Summary ---")
        print(tabulate(df[["task_id", "input_tokens", "output_tokens", "turns"]], headers="keys", tablefmt="grid"))
        print(f"\nTotal input tokens:  {df['input_tokens'].sum():,}")
        print(f"Total output tokens: {df['output_tokens'].sum():,}")
        print(f"Total tokens:        {df['input_tokens'].sum() + df['output_tokens'].sum():,}")
        print(f"Avg turns:           {df['turns'].mean():.1f}")
        print(f"\nBaseline run ID: {runner.run_id}  (stored in benchmarks.db, marked is_baseline=1)")
    finally:
        runner.close()


if __name__ == "__main__":
    asyncio.run(main())