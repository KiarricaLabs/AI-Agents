from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Personal AI Team")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from api.routers import memory, workspaces, episodes, agents, brand, work  # noqa: E402
from api.routers import team  # noqa: E402
from config.settings import DEFAULT_TENANT, LOCAL_MODE, LOCAL_USER  # noqa: E402
from core.auth import verify_token, validate_auth_secret  # noqa: E402
from core.ratelimit import RateLimiter  # noqa: E402

# Fail closed at startup: refuse to boot with a missing/insecure token-signing
# secret in non-local mode. Local mode uses a labelled dev fallback (see core.auth).
validate_auth_secret()

_rl = RateLimiter(max_calls=100000, window=60)

# Operational endpoints that do not require application identity.
_PUBLIC_PATHS = {"/health", "/metrics"}


@app.middleware("http")
async def security_mw(request, call_next):
    from core.tracing import start_span, end_span
    span = start_span("http.request", {"path": request.url.path})
    key = request.client.host if request.client else "anon"
    if not _rl.allow(key):
        end_span(span)
        return JSONResponse(status_code=429, content={"detail": "rate limited"})

    if request.url.path not in _PUBLIC_PATHS:
        tok = request.headers.get("x-token")
        if tok:
            # Production path: identity comes from a server-verified token only.
            claims = verify_token(tok)
            if not claims:
                end_span(span)
                return JSONResponse(status_code=401, content={"detail": "invalid token"})
            request.state.user_id = claims.get("sub")
            request.state.tenant_id = claims.get("tenant")
            request.state.role = claims.get("role", "user")
        elif LOCAL_MODE:
            # Explicit local-development mode: trusted, configured identity only.
            request.state.user_id = LOCAL_USER
            request.state.tenant_id = DEFAULT_TENANT
            request.state.role = "admin"
        else:
            # Fail closed: no token and local mode disabled.
            end_span(span)
            return JSONResponse(status_code=401, content={"detail": "identity required"})

    resp = await call_next(request)
    end_span(span)
    return resp


app.include_router(memory.router)
app.include_router(workspaces.router)
app.include_router(episodes.router)
app.include_router(agents.router)
app.include_router(brand.router)
app.include_router(work.router)
app.include_router(team.router)


@app.get("/metrics")
def metrics():
    from core.metrics import render
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(render())


@app.get("/health")
def health():
    return {"ok": True}
