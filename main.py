import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from .security import NeedLogin
from .seed import seed
from .engine import llm
from .routes import router
from .ui import render, BASE

@asynccontextmanager
async def lifespan(_):
    seed()
    yield


app = FastAPI(title="BrandLens", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
                   same_site="lax", max_age=60 * 60 * 12)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
app.include_router(router)


@app.exception_handler(NeedLogin)
async def need_login(request: Request, exc: NeedLogin):
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "ai_judge": llm.enabled()})
