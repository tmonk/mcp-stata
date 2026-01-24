from __future__ import annotations
import os
import sys
import threading
import logging
import json
import traceback
from typing import Any, Dict, Optional
from multiprocessing.connection import Connection
import asyncio

# Ensure the parent directory is in sys.path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_stata.stata_client import StataClient

logger = logging.getLogger("mcp_stata.worker")

class StataWorker:
    def __init__(self, conn: Connection):
        self.conn = conn
        self.client: Optional[StataClient] = None
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def run(self):
        """Main loop for the worker process."""
        try:
            # Initialize Stata in this process
            self.client = StataClient()
            # StataClient.init() will be called on first command if not already done,
            # but we can do it here explicitly.
            self.client.init()
            
            logger.info("StataWorker initialized and ready.")
            self.conn.send({"event": "ready", "pid": os.getpid()})

            while True:
                if self.conn.poll(0.1):
                    msg = self.conn.recv()
                    if msg.get("type") == "stop":
                        break
                    
                    # Handle command
                    self.loop.run_until_complete(self.handle_message(msg))
        except Exception as e:
            logger.error(f"Worker process failed: {e}")
            self.conn.send({"event": "error", "message": str(e), "traceback": traceback.format_exc()})
        finally:
            logger.info("Worker process exiting.")
            self.conn.close()

    async def handle_message(self, msg: Dict[str, Any]):
        msg_type = msg.get("type")
        msg_id = msg.get("id")
        args = msg.get("args", {})

        async def notify_log(text: str):
            self.conn.send({"event": "log", "id": msg_id, "text": text})

        async def notify_progress(progress: float, total: Optional[float], message: Optional[str]):
            self.conn.send({"event": "progress", "id": msg_id, "progress": progress, "total": total, "message": message})

        try:
            if msg_type == "run_command":
                result = await self.client.run_command_streaming(
                    args["code"],
                    notify_log=notify_log,
                    notify_progress=notify_progress,
                    **args.get("options", {})
                )
                self.conn.send({"event": "result", "id": msg_id, "result": result.model_dump()})
            
            elif msg_type == "run_do_file":
                result = await self.client.run_do_file_streaming(
                    args["path"],
                    notify_log=notify_log,
                    notify_progress=notify_progress,
                    **args.get("options", {})
                )
                self.conn.send({"event": "result", "id": msg_id, "result": result.model_dump()})

            elif msg_type == "get_data":
                data = self.client.get_data(args.get("start", 0), args.get("count", 50))
                self.conn.send({"event": "result", "id": msg_id, "result": data})

            elif msg_type == "list_graphs":
                graphs = self.client.list_graphs_structured()
                self.conn.send({"event": "result", "id": msg_id, "result": graphs.model_dump()})

            elif msg_type == "export_graph":
                path = self.client.export_graph(args.get("graph_name"), format=args.get("format", "pdf"))
                self.conn.send({"event": "result", "id": msg_id, "result": path})

            elif msg_type == "get_help":
                help_text = self.client.get_help(args["topic"], plain_text=args.get("plain_text", False))
                self.conn.send({"event": "result", "id": msg_id, "result": help_text})

            elif msg_type == "run_command_structured":
                result = self.client.run_command_structured(args["code"], **args.get("options", {}))
                self.conn.send({"event": "result", "id": msg_id, "result": result.model_dump()})

            elif msg_type == "load_data":
                result = self.client.load_data(args["source"], **args.get("options", {}))
                self.conn.send({"event": "result", "id": msg_id, "result": result.model_dump()})

            elif msg_type == "codebook":
                result = self.client.codebook(args["variable"], **args.get("options", {}))
                self.conn.send({"event": "result", "id": msg_id, "result": result.model_dump()})

            elif msg_type == "get_dataset_state":
                state = self.client.get_dataset_state()
                self.conn.send({"event": "result", "id": msg_id, "result": state})

            elif msg_type == "get_arrow_stream":
                # StataClient.get_arrow_stream supports offset, limit, vars, etc.
                arrow_bytes = self.client.get_arrow_stream(**args)
                self.conn.send({"event": "result", "id": msg_id, "result": arrow_bytes})

            elif msg_type == "list_variables_rich":
                variables = self.client.list_variables_rich()
                self.conn.send({"event": "result", "id": msg_id, "result": variables})

            elif msg_type == "compute_view_indices":
                indices = self.client.compute_view_indices(args["filter_expr"])
                self.conn.send({"event": "result", "id": msg_id, "result": indices})

            elif msg_type == "validate_filter_expr":
                self.client.validate_filter_expr(args["filter_expr"])
                self.conn.send({"event": "result", "id": msg_id, "result": None})

            elif msg_type == "get_page":
                page = self.client.get_page(**args)
                self.conn.send({"event": "result", "id": msg_id, "result": page})

            elif msg_type == "list_variables_structured":
                variables = self.client.list_variables_structured()
                self.conn.send({"event": "result", "id": msg_id, "result": variables.model_dump()})

            elif msg_type == "export_graphs_all":
                exports = self.client.export_graphs_all()
                self.conn.send({"event": "result", "id": msg_id, "result": exports.model_dump()})

            elif msg_type == "get_stored_results":
                results = self.client.get_stored_results()
                self.conn.send({"event": "result", "id": msg_id, "result": results})

            else:
                self.conn.send({"event": "error", "id": msg_id, "message": f"Unknown message type: {msg_type}"})

        except Exception as e:
            logger.error(f"Error handling message {msg_type}: {e}")
            self.conn.send({
                "event": "error", 
                "id": msg_id, 
                "message": str(e), 
                "traceback": traceback.format_exc()
            })

def main(conn):
    worker = StataWorker(conn)
    worker.run()

if __name__ == "__main__":
    # This entry point is used when the process is started via multiprocessing
    # But usually we'll pass the connection object from the parent.
    pass
