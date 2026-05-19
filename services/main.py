"""
services/main.py
Punto de entrada FastAPI — monta todos los routers de microservicios.
"""
from fastapi import FastAPI
from preprocessor.router   import router as preprocessor_router
from llm_enrichment.router import router as llm_router
from dataset_builder.router import router as dataset_router
from ml_trainer.router     import router as trainer_router
from ml_predictor.router   import router as predictor_router

app = FastAPI(
    title="Triaje IA — API de servicios",
    description="Microservicios del pipeline de triaje clínico",
    version="1.0.0",
)

app.include_router(preprocessor_router,  prefix="/preprocesar",  tags=["Preprocesador"])
app.include_router(llm_router,           prefix="/enriquecer",   tags=["LLM Enrichment"])
app.include_router(dataset_router,       prefix="/dataset",      tags=["Dataset Builder"])
app.include_router(trainer_router,       prefix="/entrenar",     tags=["ML Trainer"])
app.include_router(predictor_router,     prefix="/predecir",     tags=["ML Predictor"])


@app.get("/health")
def health():
    return {"status": "ok"}
