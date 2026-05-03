from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.PROJECT_NAME} is running"}
