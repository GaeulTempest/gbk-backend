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

# --- 1) Tentukan URL database (tulis-aman) ---
def _default_sqlite_url() -> str:
    # Cek direktori writable platform (Railway /tmp)
    for p in ("/railway/tmp", "/tmp"):
        if pathlib.Path(p).exists():
            # Pastikan foldernya ada
            pathlib.Path(p).mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{p}/rps.db"
    # fallback local
    return "sqlite:///rps.db"

DATABASE_URL = os.getenv("DATABASE_URL", _default_sqlite_url())

# --- 2) Buat engine & tabel di startup ---
engine = create_engine(DATABASE_URL, echo=False)

app = FastAPI(title="RPS Gesture Game API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.get("/", include_in_schema=False)
def health_check():
    return {"status": "ok"}

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)


# --- 3) Model & helper ---
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
    winner: Optional[str] = None  # "draw" or player_id

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
    """Simpan gerakan & return state sebagai dict sebelum Session ditutup."""
    with Session(engine) as sess:
        g = sess.get(Match, game_id)
        if not g or player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player")
        # set move
        if player_id == g.p1_id:
            g.p1_move = move
        else:
            g.p2_move = move
        # hitung winner
        if g.p1_move and g.p2_move and not g.winner:
            res = judge(g.p1_move, g.p2_move)
            g.winner = (
                "draw" if res == 0
                else g.p1_id if res == 1
                else g.p2_id
            )
        sess.add(g)
        sess.commit()
        return g.dict()


# --- 4) REST endpoints ---
@app.post("/create_game")
def create_game():
    # bikin match baru
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


# --- 5) WebSocket for real-time updates ---
connections: Dict[str, Set[WebSocket]] = {}

@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(ws: WebSocket, game_id: str, player_id: str):
    await ws.accept()
    connections.setdefault(game_id, set()).add(ws)
    try:
        while True:
            # tunggu ping dari client
            await ws.receive_text()
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
