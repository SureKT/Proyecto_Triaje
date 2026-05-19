"""
services/ml_predictor/router.py
Endpoint POST /predecir — punto de entrada Fase 2.
Acepta fichero .txt o texto directo.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional
from ml_predictor.service import predict

router = APIRouter()


@router.post("/")
async def predecir(
    file: Optional[UploadFile] = File(None),
    texto: Optional[str] = Form(None),
):
    """
    Acepta:
      - file: fichero .txt con la transcripción
      - texto: texto plano directamente en el form

    curl -X POST http://localhost:8000/predecir -F "file=@entrevista.txt"
    """
    if file is not None:
        contenido = (await file.read()).decode("utf-8", errors="replace")
    elif texto:
        contenido = texto
    else:
        raise HTTPException(status_code=422,
                            detail="Se requiere 'file' o 'texto'.")

    if not contenido.strip():
        raise HTTPException(status_code=422, detail="El texto está vacío.")

    try:
        return predict(contenido)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
