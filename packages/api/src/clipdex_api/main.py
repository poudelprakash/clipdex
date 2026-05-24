from fastapi import FastAPI

from clipdex_api.guests import router as guests_router
from clipdex_api.questions import router as questions_router
from clipdex_api.search import router as search_router

app = FastAPI(title="clipdex", version="0.1.0")
app.include_router(search_router)
app.include_router(guests_router)
app.include_router(questions_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
