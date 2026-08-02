from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import cart

app = FastAPI(title="Sports Store — Cart Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cart.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "service": "cart-service"}
