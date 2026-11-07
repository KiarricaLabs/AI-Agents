from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import os

_SCHEDULERS = {}

@asynccontextmanager
async def lifespan(app):
    # Startup: restore schedulers for projects with a schedule.
    from config.settings import DB_PATH, DEFAULT_TENANT
    from storage.database import Database
    from core.scheduler import Scheduler
    from core.run_worker import get_worker
    try:
        db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        get_worker(db)
        rows = db.query("SELECT id, tenant_id, user_id, schedule_interval_seconds FROM agent_projects WHERE schedule_interval_seconds IS NOT NULL")
        for r in rows:
            pid = r["id"]
            if pid in _SCHEDULERS:
                continue
            interval = r["schedule_interval_seconds"] or 300
            tenant = r["tenant_id"]
            user = r["user_id"]
            def make_enqueue(p, t, u):
                def enqueue():
                    import uuid, json
                    from datetime import datetime, timezone
                    # approval gate: only approved/running projects
                    pr = db.query("SELECT status FROM agent_projects WHERE id=? AND tenant_id=? AND user_id=?", (p, t, u))
                    if not pr or pr[0]["status"] not in ("approved", "running"):
                        return
                    job_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    with db.transaction() as conn:
                        conn.execute("INSERT INTO agent_runs (id,project_id,tenant_id,user_id,status,created_at) VALUES (?,?,?,?,?,?)",
                                     (job_id, p, t, u, "queued", now))
                return enqueue
            sched = Scheduler(make_enqueue(pid, tenant, user), interval_seconds=interval)
            sched.start()
            _SCHEDULERS[pid] = sched
    except Exception:
        pass
    yield
    # Shutdown
    for s in list(_SCHEDULERS.values()):
        try:
            s.stop()
        except Exception:
            pass
    _SCHEDULERS.clear()

app = FastAPI(title="Personal AI Team", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from api.routers import memory, agents, brand  # noqa: E402
from api.routers import team  # noqa: E402
from api.routers import agent_comm, progress as progress_api  # noqa: E402
from api.routers import feedback  # noqa: E402
from api.routers import evaluations  # noqa: E402
from api.routers import projects  # noqa: E402
from api.routers import actions  # noqa: E402
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
app.include_router(agents.router)
app.include_router(brand.router)
app.include_router(team.router)
app.include_router(agent_comm.router)
app.include_router(progress_api.router)
app.include_router(feedback.router)
app.include_router(evaluations.router)
app.include_router(projects.router)
app.include_router(actions.router)


@app.get("/metrics")
def metrics():
    from core.metrics import render
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(render())


@app.get("/health")
def health():
    return {"ok": True}
