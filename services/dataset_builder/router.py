from fastapi import APIRouter, HTTPException
from dataset_builder.service import build_dataset

router = APIRouter()

@router.post("/")
def build_dataset_endpoint():
    try:
        url = build_dataset()
        return {"status": "ok", "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
