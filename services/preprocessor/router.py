from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from preprocessor.service import preprocess

router = APIRouter()

class PreprocessRequest(BaseModel):
    guid: str
    texto: str

@router.post("/")
def preprocess_endpoint(req: PreprocessRequest):
    try:
        return preprocess(req.guid, req.texto)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
