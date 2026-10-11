from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import models # ensure models are registered
from app.api.v1 import api_v1_router
from app.services.taxonomy import seed_taxonomy, seed_catalog

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Natural-language open-source software discovery platform MVP"
)

# CORS middleware for local frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_populate():
    # Ensure all tables exist
    Base.metadata.create_all(bind=engine)
    # Auto-seed taxonomy and catalog if database is fresh
    db = SessionLocal()
    try:
        from app.models.models import App
        app_count = db.query(App).count()
        if app_count == 0:
            seed_taxonomy(db)
            seed_catalog(db)
    finally:
        db.close()


app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "docs": "/docs",
        "api_v1": settings.API_V1_PREFIX,
        "status": "online"
    }
