# ----------------- server.py -----------------
import os
import uuid
import pathlib
from enum import Enum
from typing import Optional, Set, Dict

from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, SQLModel, Session, create_engine
from fastapi import FastAPI
import os, pathlib

app = FastAPI(title="RPS Gesture Game API")

@app.get("/", include_in_schema=False)
def health_check():
    return {"status": "ok"}

# … rest of your imports & code …


# 1) Tentukan URL SQLite di direktori write-able Railway (/railway/tmp, /tmp)
def _default_sqlite_url() -> str:
    for p in ("/railway/tmp", "/tmp"):
        path = pathlib.Path(p)
        if path.exists() or (path.parent.exists()):
            path.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{p}/rps.db"
    return "sqlite:///rps.db"  # fallback lokal

DATABASE_URL = os.getenv("DATABASE_URL", _default_sqlite_url())
engine = create_engine(DATABASE_URL, echo=False)

# 2) Definisi model
class MoveEnum(str, Enum):
    rock = "rock"
    paper = "paper"
    scissors = "scissors"

class Match(SQLModel, table=True):
    id: str = Field(primary_key=True)
    p1_id: str
    p2_id: Optional[str] = None
    p1_move: Optional[MoveEnum] = None
    p2_move: Optional[MoveEnum] = None
    winner: Optional[str] = None  # "draw" atau player_id

# 3) Inisialisasi FastAPI + CORS
app = FastAPI(title="RPS Gesture Game API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# 4) Health-check supaya Railway tidak SIGTERM container
@app.get("/", include_in_schema=False)
def health_check():
    return {"status": "ok"}

# 5) Create tables sekali di startup
@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# 6) Helper: aturan suit dan penyimpanan moves
def judge(m1: MoveEnum, m2: MoveEnum) -> int:
    beats = {
        (MoveEnum.rock, MoveEnum.scissors),
        (MoveEnum.scissors, MoveEnum.paper),
        (MoveEnum.paper, MoveEnum.rock),
    }
    if m1 == m2:
        return 0
    return 1 if (m1, m2) in beats else 2

def _submit(game_id: str, player_id: str, move: MoveEnum) -> dict:
    """Simpan move, commit, dan kembalikan state sebagai dict sebelum session ditutup."""
    with Session(engine) as sess:
        g = sess.get(Match, game_id)
        if not g or player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player")
        # set move
        if player_id == g.p1_id:
            g.p1_move = move
        else:
            g.p2_move = move
        # hitung pemenang
        if g.p1_move and g.p2_move and not g.winner:
            res = judge(g.p1_move, g.p2_move)
            g.winner = (
                "draw" if res == 0
                else g.p1_id if res == 1
                else g.p2_id
            )
        sess.add(g)
        sess.commit()
        # Kembalikan dict agar broadcast tidak trigger DetachedInstanceError
        return g.dict()

# 7) REST-API endpoints
@app.post("/create_game")
def create_game():
    g = Match(id=str(uuid.uuid4()), p1_id=str(uuid.uuid4()))
    with Session(engine) as sess:
        sess.add(g)
        sess.commit()
    return {"game_id": g.id, "player_id": g.p1_id}

@app.post("/join/{game_id}")
def join_game(game_id: str):
    with Session(engine) as sess:
        g = sess.get(Match, game_id)
        if not g:
            raise HTTPException(404, "Game not found")
        if g.p2_id:
            raise HTTPException(400, "Game full")
        g.p2_id = str(uuid.uuid4())
        sess.add(g)
        sess.commit()
    return {"player_id": g.p2_id}

@app.post("/move/{game_id}")
def move_rest(game_id: str, player_id: str, move: MoveEnum):
    _submit(game_id, player_id, move)
    return {"status": "ok"}

@app.get("/state/{game_id}")
def get_state(game_id: str):
    with Session(engine) as sess:
        g = sess.get(Match, game_id)
        if not g:
            raise HTTPException(404, "Game not found")
        return g.dict()

# 8) WebSocket untuk real-time broadcast
connections: Dict[str, Set[WebSocket]] = {}

@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(ws: WebSocket, game_id: str, player_id: str):
    await ws.accept()
    connections.setdefault(game_id, set()).add(ws)
    try:
        while True:
            await ws.receive_text()  # ping dari client
    except WebSocketDisconnect:
        connections[game_id].discard(ws)

async def _broadcast(game_id: str, payload: dict):
    for ws in list(connections.get(game_id, [])):
        try:
            await ws.send_json(payload)
        except RuntimeError:
            connections[game_id].discard(ws)

@app.post("/move_ws/{game_id}")
async def move_ws(game_id: str, player_id: str, move: MoveEnum, bg: BackgroundTasks):
    state = _submit(game_id, player_id, move)
    bg.add_task(_broadcast, game_id, state)
    return {"status": "ok"}
