"""API entry point."""

from dotenv import load_dotenv

load_dotenv(override=True)

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.brand import PRODUCT_NAME
from app.ratelimit import limiter
from app.routes import agent

app = FastAPI(title=f"{PRODUCT_NAME} API")

# --- Rate limiting -------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# --- CORS ----------------------------------------------------------------
# Lock to the production Vercel origin(s) via ALLOWED_ORIGINS (comma-sep).
# Vercel preview deploys still allowed via the *.vercel.app regex.
_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    *(
        [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
        if os.environ.get("ALLOWED_ORIGINS")
        else []
    ),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    # No cookies/credentials are used — keep this False so a permissive
    # origin can never be paired with credentialed requests.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

app.include_router(agent.router)


@app.get("/")
@limiter.exempt
async def root():
    return {"service": PRODUCT_NAME.lower(), "status": "ok"}


@app.get("/health")
@limiter.exempt
async def health():
    return {"ok": True}
