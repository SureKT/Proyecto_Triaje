"""
services/llm_enrichment/router.py
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from llm_enrichment.service import enrich

router = APIRouter()

class EnrichRequest(BaseModel):
    guid: str
    texto: str

@router.post("/")
def enrich_endpoint(req: EnrichRequest):
    try:
        resultado = enrich(req.guid, req.texto)
        return {"guid": req.guid, "resultado": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
