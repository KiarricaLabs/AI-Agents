from fastapi import FastAPI

app = FastAPI(title="Personal AI Team")
from api.routers import memory, workspaces
app.include_router(memory.router)
app.include_router(workspaces.router)


@app.get("/health")
def health():
    return {"ok": True}