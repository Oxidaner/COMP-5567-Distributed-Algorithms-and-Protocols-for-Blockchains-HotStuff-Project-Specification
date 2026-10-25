"""Run from the project root with: python backend/main.py"""
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import uvicorn

from backend.hotstuff import HotStuffDemo


demo = HotStuffDemo()
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


async def ticker():
    while True:
        await asyncio.sleep(0.8)
        if demo.running:
            try:
                demo.step()
            except NotImplementedError:
                # step() has paused the experiment and preserved the event.
                pass


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(ticker())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="HotStuff Classroom Demo", lifespan=lifespan)
@app.exception_handler(NotImplementedError)
async def missing_function(request, exc):
    return JSONResponse(status_code=501, content={"detail": str(exc), "state": demo.snapshot()})


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str
    receiver: str
    amount: int = Field(strict=True, ge=1, le=1_000_000)


class ByzantineRequest(BaseModel):
    node_id: int | None = Field(default=None, strict=True, ge=1, le=4)


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/state")
async def state():
    return demo.snapshot()


@app.post("/api/control/{action}")
async def control(action: str):
    # No awaits inside mutations: all actions are atomic on the one event loop.
    if action == "start":
        demo.running = True
    elif action == "pause":
        demo.running = False
    elif action == "step":
        demo.running = False
        demo.step()
    elif action == "reset":
        demo.reset()
    elif action == "crash-leader":
        demo.crash_leader()
    elif action == "recover":
        demo.recover()
    else:
        raise HTTPException(404, "Unknown control action")
    return demo.snapshot()


@app.post("/api/transactions")
async def submit_transaction(request: TransferRequest):
    try:
        tx = demo.submit(request.sender, request.receiver, request.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"transaction_id": tx.id, "state": demo.snapshot()}


@app.post("/api/byzantine")
async def byzantine(request: ByzantineRequest):
    demo.set_byzantine(request.node_id)
    return demo.snapshot()


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_txs_per_block: int = Field(strict=True, ge=1)


class AttackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    node_id: int = Field(strict=True, ge=1, le=4)


@app.post("/api/config/batch")
async def batch_config(request: BatchRequest):
    try:
        demo.configure_batch(request.max_txs_per_block)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"max_txs_per_block": demo.max_txs_per_block, "state": demo.snapshot()}


@app.post("/api/attacks")
async def attack(request: AttackRequest):
    try:
        demo.inject_attack(request.kind, request.node_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return demo.snapshot()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

