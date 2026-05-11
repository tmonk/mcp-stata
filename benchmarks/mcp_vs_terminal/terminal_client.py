import subprocess
import os
import tempfile
from typing import Dict, Any

class TerminalStataClient:
    """
    Simulates the 'Terminal agent' approach.
    Exposes a single tool: bash(command: str)
    """
    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

    def execute_bash(self, command: str) -> str:
        """
        Executes a shell command and returns stdout + stderr.
        """
        try:
            # We run in the specified work directory
            process = subprocess.run(
                command,
                shell=True,
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            return f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}\nExit Code: {process.returncode}"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 60 seconds."
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def get_tools(self):
        return [
            {
                "name": "bash",
                "description": "Execute a bash command in the terminal. Use this to run Stata via 'stata-se -b do file.do' or 'stata-se -e \"command\"'. You must manage your own files and logs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"}
                    },
                    "required": ["command"]
                }
            }
        ]

if __name__ == "__main__":
    client = TerminalStataClient("./test_terminal")
    print(client.execute_bash("echo 'hello'"))
