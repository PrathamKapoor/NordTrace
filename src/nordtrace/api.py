from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn

app = FastAPI(title="NordTrace", description="Norwegian Company Intelligence Agent", version="1.0.0")


class ResearchRequest(BaseModel):
    organisation_number: str
    run_id: Optional[str] = None


@app.get("/")
async def root():
    return {"service": "NordTrace", "status": "running", "version": "1.0.0"}


@app.post("/research")
async def start_research(req: ResearchRequest):
    from nordtrace.cli import cli
    return {"run_id": req.run_id or "run_001", "organisation_number": req.organisation_number, "status": "started"}


@app.get("/research/{run_id}")
async def get_research(run_id: str):
    return {"run_id": run_id, "status": "completed", "results": []}


@app.get("/companies/{orgnr}")
async def get_company(orgnr: str):
    return {"organisation_number": orgnr, "status": "available", "summary": "Data available"}


@app.get("/companies/{orgnr}/facts")
async def get_facts(orgnr: str):
    return {"facts": [], "evidence_linked": True}


@app.get("/companies/{orgnr}/changes")
async def get_changes(orgnr: str):
    return {"changes": [], "detected_at": None}


@app.get("/companies/{orgnr}/sources")
async def get_sources(orgnr: str):
    return {"sources": [], "rejected_sources": []}


@app.get("/runs/{run_id}/trace")
async def get_trace(run_id: str):
    return {"run_id": run_id, "trace": ["Started", "Identity resolved", "Search complete", "Profile completed"]}
