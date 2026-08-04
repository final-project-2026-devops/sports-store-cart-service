import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from routes import cart

logger = logging.getLogger("cart-service")

app = FastAPI(title="Sports Store — Cart Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cart.router, prefix="/api")

Instrumentator().instrument(app).expose(app)


@app.get("/health")
def health():
    return {"status": "ok", "service": "cart-service"}
