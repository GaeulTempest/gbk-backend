import os
import uuid
import logging
import asyncio

from typing import Optional, Dict, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine

# ────── init & logging ──────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

app = FastAPI(title="RPS-Gesture Game API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")

# ─── buat engine dengan check_same_thread=False jika SQLite ────────
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)

# ────── models ──────────────────────────────────────────
class Match(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id: str
    p1_name: str
    p1_ready: bool = False

    p2_id: Optional[str] = None
    p2_name: Optional[str] = None
    p2_ready: bool = False

def state(g: Match) -> dict:
    return {
        "players": {
            "A": {"id": g.p1_id, "name": g.p1_name, "ready": g.p1_ready},
            "B": {"id": g.p2_id, "name": g.p2_name, "ready": g.p2_ready},
        }
    }

# ────── schemas ─────────────────────────────────────────
class NewGame(BaseModel):
    player_name: str

class JoinReq(BaseModel):
    player_name: str

class ReadyReq(BaseModel):
    player_id: str

# ────── DB init ─────────────────────────────────────────
@app.on_event("startup")
def init_db():
    SQLModel.metadata.create_all(engine)
    log.info("Database ready")

# ────── HTTP endpoints ──────────────────────────────────
@app.post("/create_game")
def create_game(body: NewGame):
    if not body.player_name.strip():
        raise HTTPException(400, "player_name empty")
    with Session(engine) as s:
        g = Match(p1_id=str(uuid.uuid4()), p1_name=body.player_name.strip())
        s.add(g)
        s.commit()
        s.refresh(g)
    return {"game_id": g.id, "player_id": g.p1_id, "role": "A"}

@app.post("/join/{gid}")
def join_game(gid: str, body: JoinReq):
    with Session(engine) as s:
        g = s.get(Match, gid)
        if not g:
            raise HTTPException(404, "Game not found")
        if g.p2_id:
            raise HTTPException(400, "Room full")
        if not body.player_name.strip():
            raise HTTPException(400, "player_name empty")

        g.p2_id = str(uuid.uuid4())
        g.p2_name = body.player_name.strip()
        s.add(g)
        s.commit()
        s.refresh(g)

    # broadcast update ke semua WS klien
    broadcast(g)
    return {"player_id": g.p2_id, "role": "B"}

@app.post("/ready/{gid}")
def set_ready(gid: str, body: ReadyReq):
    with Session(engine) as s:
        g = s.get(Match, gid)
        if not g or body.player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player or game")
        if body.player_id == g.p1_id:
            g.p1_ready = True
        else:
            g.p2_ready = True
        s.add(g)
        s.commit()
        s.refresh(g)

    broadcast(g)
    return state(g)

@app.get("/state/{gid}")
def get_state_endpoint(gid: str):
    with Session(engine) as s:
        g = s.get(Match, gid)
        if not g:
            raise HTTPException(404, "Game not found")
        return state(g)

# ────── WebSocket broadcast ─────────────────────────────
clients: Dict[str, Set[WebSocket]] = {}

async def _send(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
    except:
        pass

def broadcast(game: Match):
    payload = state(game)
    loop = None
    try:
        # dapatkan loop utama (uvicorn)
        loop = asyncio.get_event_loop()
    except RuntimeError:
        pass

    for ws in list(clients.get(game.id, [])):
        if loop and loop.is_running():
            # jadwalkan pengiriman tanpa menunggu
            loop.call_soon_threadsafe(asyncio.create_task, _send(ws, payload))

@app.websocket("/ws/{gid}/{pid}")
async def ws_endpoint(gid: str, pid: str, ws: WebSocket):
    await ws.accept()
    clients.setdefault(gid, set()).add(ws)
    try:
        # kirim snapshot awal
        with Session(engine) as s:
            g = s.get(Match, gid)
            if g:
                await ws.send_json(state(g))
        # tetap buka koneksi, abaikan pesan masuk
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients[gid].discard(ws)
