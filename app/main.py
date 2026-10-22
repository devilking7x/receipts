"""FastAPI compliance layer: programmatic access for judges.

- GET /health: liveness plus the active mode.
- POST /run: JSON in, structured report JSON out. No interactive
  input, no UI needed. Failures return a useful message, never a
  stack trace and never a hang.

Example judge test:
    curl -X POST http://localhost:8000/run \
      -H "Content-Type: application/json" \
      -d @input_examples/01_helios.json
"""

import asyncio
import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.pipeline import VendorNotFoundError, orchestrate
from config import load_config
from data_layer.zetaris_client import ZetarisDataLayerUnavailableError

app = FastAPI(title="Receipts", version="1.0.0")


class RunRequest(BaseModel):
    vendor_name: str
    procurement_context: str = ""
    sample_mode: Optional[bool] = None


@app.get("/health")
def health():
    config = load_config()
    return {
        "status": "ok",
        "service": "receipts",
        "sample_mode": config.sample_mode,
        "version": "1.0.0",
    }


@app.post("/run")
async def run_investigation(request: RunRequest):
    overrides = {}
    if request.sample_mode is not None:
        overrides["sample_mode"] = request.sample_mode
    config = load_config(overrides)
    try:
        result = await asyncio.to_thread(
            orchestrate,
            request.vendor_name,
            request.procurement_context,
            config,
            "output",
            "logs/traces.jsonl")
    except VendorNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except ZetarisDataLayerUnavailableError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    except Exception as exc:  # useful message, never a stack trace
        return JSONResponse(status_code=500,
                            content={"detail": "Investigation failed: %s"
                                               % exc})
    return result.report
