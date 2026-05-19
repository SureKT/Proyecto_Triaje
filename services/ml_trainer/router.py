from fastapi import APIRouter, HTTPException
from ml_trainer.service import train

router = APIRouter()

@router.post("/")
def train_endpoint():
    try:
        return train()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
