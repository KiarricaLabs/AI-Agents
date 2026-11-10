from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
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
            def make_enqueue(p, t, u, iv):
                def enqueue():
                    from core.run_worker import enqueue_scheduled_run
                    enqueue_scheduled_run(db, p, t, u, iv)
                return enqueue
            sched = Scheduler(make_enqueue(pid, tenant, user, interval), interval_seconds=interval)
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

from api.routers import memory, voice, agents, brand  # noqa: E402
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
_PUBLIC_PATHS = {"/health", "/metrics", "/ready"}


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
app.include_router(voice.router)
try:
    from api.routers import voice_eleven
    app.include_router(voice_eleven.router)
except Exception: pass
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


@app.get("/runs/queue")
def run_queue(request: Request):
    from datetime import datetime, timezone
    from config.settings import DB_PATH, DEFAULT_TENANT
    from storage.database import Database

    t = getattr(request.state, "tenant_id", None) or DEFAULT_TENANT
    u = getattr(request.state, "user_id", None)
    db = Database(path=DB_PATH, tenant_id=t)
    where = "tenant_id=?"
    params = [t]
    if u:
        where += " AND user_id=?"
        params.append(u)
    queued_count = db.query(
        f"SELECT COUNT(*) AS c FROM agent_runs WHERE status='queued' AND {where}",
        tuple(params),
    )[0]["c"]
    running_count = db.query(
        f"SELECT COUNT(*) AS c FROM agent_runs WHERE status='running' AND {where}",
        tuple(params),
    )[0]["c"]
    oldest_rows = db.query(
        f"SELECT MIN(created_at) AS m FROM agent_runs WHERE status='queued' AND {where}",
        tuple(params),
    )
    oldest = oldest_rows[0]["m"] if oldest_rows else None
    oldest_age = None
    if oldest:
        try:
            dt = datetime.fromisoformat(str(oldest).replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                oldest_age = int((datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            oldest_age = None
    return {
        "queued_count": queued_count,
        "running_count": running_count,
        "oldest_queued_age_seconds": oldest_age,
    }


@app.get("/runs/stale")
def stale_runs(request: Request, older_than_seconds: int = 300):
    from datetime import datetime, timezone
    from config.settings import DB_PATH, DEFAULT_TENANT
    from storage.database import Database
    from fastapi import HTTPException, Query

    # Query param validation (FastAPI handles via function signature? ensure bounds)
    if older_than_seconds < 1 or older_than_seconds > 86400:
        raise HTTPException(status_code=422, detail="older_than_seconds must be between 1 and 86400")

    t = getattr(request.state, "tenant_id", None) or DEFAULT_TENANT
    u = getattr(request.state, "user_id", None)
    db = Database(path=DB_PATH, tenant_id=t)
    sql = "SELECT id, project_id, status, started_at FROM agent_runs WHERE status='running' AND tenant_id=?"
    params = [t]
    if u:
        sql += " AND user_id=?"
        params.append(u)
    rows = db.query(sql, tuple(params))
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        started = r.get("started_at")
        if not started:
            continue
        try:
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            # Naive timestamp: age cannot be reliably determined; skip.
            continue
        age = (now - dt).total_seconds()
        if age >= older_than_seconds:
            out.append({
                "run_id": r["id"],
                "project_id": r.get("project_id"),
                "status": r["status"],
                "started_at": started,
                "age_seconds": int(age),
                "possibly_stale": True,
            })
    return {"items": out}


@app.get("/ready")
async def ready():
    import asyncio
    from datetime import datetime, timezone
    from config.settings import DB_PATH, DEFAULT_TENANT
    from storage.database import Database
    from core.model_router import ModelRouter

    checks = {"database": "unknown", "model": "unknown", "queue": "unknown"}

    # Database check (bounded).
    def _db_check():
        db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)
        db.query("SELECT 1")
        return True

    try:
        await asyncio.wait_for(asyncio.to_thread(_db_check), timeout=1.0)
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "fail"

    # Model check (reuse existing logic, bounded).
    def _model_check():
        info = ModelRouter().check_availability(timeout=1.0)
        return bool(info.get("ok"))

    try:
        ok_model = await asyncio.wait_for(asyncio.to_thread(_model_check), timeout=2.0)
        checks["model"] = "ok" if ok_model else "fail"
    except Exception:
        checks["model"] = "fail"

    ready_flag = checks["database"] == "ok" and checks["model"] == "ok"
    status_code = 200 if ready_flag else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "ready": ready_flag,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
