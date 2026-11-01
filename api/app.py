from fastapi import FastAPI

app = FastAPI(title="Personal AI Team")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
from api.routers import memory, workspaces, episodes
from config.settings import DEFAULT_TENANT
from core.auth import verify_token
from core.ratelimit import RateLimiter
from core.policy import PolicyEngine
from core.policy_enforcer import PolicyEnforcer

_rl = RateLimiter(max_calls=100000, window=60)

@app.middleware("http")
async def security_mw(request, call_next):
    from core.tracing import start_span, end_span
    span = start_span("http.request", {"path": request.url.path})
    # rate limit by client host
    key = request.client.host if request.client else "anon"
    if not _rl.allow(key):
        from fastapi.responses import JSONResponse
        end_span(span)
        return JSONResponse(status_code=429, content={"detail": "rate limited"})
    # identity resolution: token if present else local trusted
    tok = request.headers.get("x-token")
    if tok:
        claims = verify_token(tok)
        if not claims:
            from fastapi.responses import JSONResponse
            end_span(span)
            return JSONResponse(status_code=401, content={"detail": "invalid token"})
        request.state.user_id = claims.get("sub")
        request.state.tenant_id = claims.get("tenant")
        request.state.role = claims.get("role", "user")
    else:
        request.state.user_id = "local"
        request.state.tenant_id = DEFAULT_TENANT
        request.state.role = "admin"
    resp = await call_next(request)
    end_span(span)
    return resp

app.include_router(memory.router)
app.include_router(workspaces.router)
app.include_router(episodes.router)


@app.get("/metrics")
def metrics():
    from core.metrics import render
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(render())

@app.get("/health")
def health():
    return {"ok": True}