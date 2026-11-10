from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import init_db
from routes.bounty_routes import router as bounty_router
from routes.webhook_routes import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("[STARTUP] SQLite bounties.db initialized and ready.")
    yield


app = FastAPI(
    title="PR-BountyPay API",
    description="Autonomous GitHub PR & Unit-Test Bounty Settlement Engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bounty_router)
app.include_router(webhook_router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "PR-BountyPay Backend"}