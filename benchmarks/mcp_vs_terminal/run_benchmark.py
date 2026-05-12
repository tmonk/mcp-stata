#!/usr/bin/env python3
"""
run_benchmark.py – Run MCP-only benchmark and compare against baseline.

Usage:
    python run_benchmark.py --local     # uses local dev mcp-stata
    python run_benchmark.py             # uses installed release

The terminal baseline must exist before running this. If no baseline is found,
the script will exit with an error telling you to run run_baseline.py first.
"""

import asyncio
import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from mcp_client import MCPStataClient
from tabulate import tabulate

from db import init_db, create_run, save_result, save_artifact, get_run_results, get_default_baseline

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


class BenchmarkRunner:
    def __init__(self, model_name: str = MODEL_NAME, use_local: bool = False):
        self.model_name = model_name
        self.use_local = use_local
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
        async with MCPStataClient(".", use_local=self.use_local) as client:
            tools = await client.get_tools()
            gemini_tools = self._convert_tools_to_gemini(tools)
            return await self._run_loop(task, tools, gemini_tools, client, max_turns)

    async def _run_loop(self, task, mcp_tools, gemini_tools, client, max_turns):
        history = []
        total_input = 0
        total_output = 0
        turn_count = 0
        response = None

        history.append(types.Content(role="user", parts=[types.Part(text=task["prompt"])]))
        self._log(f"Task {task['id']} start approach=mcp")
        self._log(f"User prompt:\n{task['prompt']}")

        while turn_count < max_turns:
            turn_count += 1
            print(f"  Turn {turn_count}...")
            self._log(f"Turn {turn_count} begin")

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
                result = await client.call_tool(name, args)
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
            "approach": "mcp",
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
    parser = argparse.ArgumentParser(description="Run MCP benchmark")
    parser.add_argument("--local", action="store_true", help="Use local development mcp-stata")
    args = parser.parse_args()

    init_db()

    baseline = get_default_baseline()
    if not baseline:
        print("ERROR: No baseline found. Please run 'python run_baseline.py' first.")
        print("The terminal baseline must be established before running MCP benchmarks.")
        import sys
        sys.exit(1)

    print(f"Using baseline: {baseline['run_id']} (created {baseline['created_at'][:16].replace('T', ' ')})")

    version_str = _get_local_version() if args.local else None
    run_notes = f"CLI run" + (f" [LOCAL: {version_str}]" if args.local else "")

    runner = BenchmarkRunner(use_local=args.local)
    runner.run_id = create_run(
        model_name=MODEL_NAME,
        notes=run_notes,
        source="live",
        is_baseline=False,
        mcp_version=version_str,
    )
    print(f"MCP run ID: {runner.run_id}")
    if args.local:
        print(f"Using LOCAL mcp-stata: {version_str}")

    Path("results").mkdir(exist_ok=True)
    runner._run_log_path = Path("results") / f"{runner.run_id}.log"
    runner._run_log_fh = runner._run_log_path.open("w", encoding="utf-8")

    try:
        with open("tasks.json") as f:
            tasks_data = json.load(f)

        all_results = []
        baseline_results = {r["task_id"]: r for r in get_run_results(baseline["run_id"])}

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
        print("\n--- MCP Benchmark Summary ---")
        print(tabulate(df[["task_id", "input_tokens", "output_tokens", "turns"]], headers="keys", tablefmt="grid"))

        baseline_df = pd.DataFrame(list(baseline_results.values()))
        merged = df.merge(baseline_df[["task_id", "input_tokens", "output_tokens"]],
                          on="task_id", suffixes=("_mcp", "_baseline"))
        merged["input_delta"] = merged["input_tokens_mcp"] - merged["input_tokens_baseline"]
        merged["output_delta"] = merged["output_tokens_mcp"] - merged["output_tokens_baseline"]
        merged["total_delta"] = (merged["input_tokens_mcp"] + merged["output_tokens_mcp"]) - \
                                (merged["input_tokens_baseline"] + merged["output_tokens_baseline"])

        print("\n--- Comparison vs Baseline ---")
        print(tabulate(merged[["task_id", "input_tokens_baseline", "input_tokens_mcp", "input_delta",
                               "output_tokens_baseline", "output_tokens_mcp", "output_delta"]],
                       headers="keys", tablefmt="grid"))

        total_mcp = df["input_tokens"].sum() + df["output_tokens"].sum()
        total_baseline = baseline_df["input_tokens"].sum() + baseline_df["output_tokens"].sum()
        print(f"\nBaseline total: {total_baseline:,} tokens")
        print(f"MCP total:      {total_mcp:,} tokens")
        print(f"Delta:          {total_mcp - total_baseline:+,} tokens ({((total_mcp/total_baseline)-1)*100:+.1f}%)")
        print(f"\nMCP run ID: {runner.run_id}")
    finally:
        runner.close()


if __name__ == "__main__":
    asyncio.run(main())