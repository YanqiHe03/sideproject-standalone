"""HTTP entry point. Model startup and generation live in generation.py."""

from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from generation import GenerationEngine


class GenerateRequest(BaseModel):
    temp: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    context: int = Field(default=64, ge=1)
    delay: float = Field(default=0.05, ge=0, allow_inf_nan=False)
    reset: bool = True


class ResetRequest(BaseModel):
    value: int = 1


def create_app(load_engine=GenerationEngine.load):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = load_engine()
        try:
            yield
        finally:
            app.state.engine = None

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/generate")
    async def generate_endpoint(req: GenerateRequest, request: Request):
        records = request.app.state.engine.generate(**req.model_dump())
        return StreamingResponse(
            (json.dumps(record) + "\n" for record in records),
            media_type="application/x-ndjson",
        )

    @app.post("/reset")
    async def reset_endpoint(req: ResetRequest, request: Request):
        sent = request.app.state.engine.reset_output(req.value)
        return JSONResponse(
            {"status": "ok" if sent else "unavailable", "value": req.value},
            status_code=200 if sent else 503,
        )

    @app.get("/")
    async def dashboard():
        return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Backend Dashboard</title>
    <style>
        body { font-family: monospace; background: #000; color: #0f0; padding: 20px; }
    </style>
</head>
<body>
    <h1>THE SIDE PROJECT - BACKEND</h1>
    <div>Status: ONLINE</div>
</body>
</html>
""")

    return app


app = create_app()

if __name__ == "__main__":
    import logging
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=7860)
