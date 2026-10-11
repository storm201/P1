from fastapi import APIRouter
from app.api.v1.search import router as search_router
from app.api.v1.apps import router as apps_router
from app.api.v1.categories import router as categories_router
from app.api.v1.releases import router as releases_router
from app.api.v1.corrections import router as corrections_router
from app.api.v1.ops import router as ops_router
from app.api.v1.health import router as health_router

api_v1_router = APIRouter()
api_v1_router.include_router(search_router, tags=["search"])
api_v1_router.include_router(apps_router, tags=["apps"])
api_v1_router.include_router(categories_router, tags=["categories"])
api_v1_router.include_router(releases_router, tags=["releases"])
api_v1_router.include_router(corrections_router, tags=["corrections"])
api_v1_router.include_router(ops_router, tags=["ops"])
api_v1_router.include_router(health_router, tags=["health"])
