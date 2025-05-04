# ----------------- server.py -----------------
import os, uuid, asyncio
from enum import Enum
from typing import Optional, Set, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, SQLModel, Session, create_engine

# ⬇️ Fallback ke SQLite bila DATABASE_URL tidak ada
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///rps.db")
engine = create_engine(DATABASE_URL, echo=False)

# ---------- Model ----------
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

# ---------- FastAPI ----------
app = FastAPI(title="RPS Gesture Game API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def on_startup():
    # dipanggil sekali per worker ➜ tabel dibuat bila belum ada
    SQLModel.metadata.create_all(engine)

# ---------- Util ----------
def judge(m1: MoveEnum, m2: MoveEnum) -> int:
    beats = {(MoveEnum.rock, MoveEnum.scissors),
             (MoveEnum.scissors, MoveEnum.paper),
             (MoveEnum.paper, MoveEnum.rock)}
    return 0 if m1 == m2 else 1 if (m1, m2) in beats else 2

# ---------- REST ----------
@app.post("/create_game")
def create_game():
    g = Match(id=str(uuid.uuid4()), p1_id=str(uuid.uuid4()))
    with Session(engine) as s:
        s.add(g); s.commit()
    return {"game_id": g.id, "player_id": g.p1_id}

@app.post("/join/{game_id}")
def join(game_id: str):
    with Session(engine) as s:
        g = s.get(Match, game_id)
        if not g: raise HTTPException(404, "Game not found")
        if g.p2_id: raise HTTPException(400, "Game full")
        g.p2_id = str(uuid.uuid4()); s.add(g); s.commit()
    return {"player_id": g.p2_id}

def _submit(game_id: str, player_id: str, move: MoveEnum):
    with Session(engine) as s:
        g = s.get(Match, game_id)
        if not g or player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player")
        if player_id == g.p1_id: g.p1_move = move
        else: g.p2_move = move
        if g.p1_move and g.p2_move and not g.winner:
            res = judge(g.p1_move, g.p2_move)
            g.winner = "draw" if res == 0 else g.p1_id if res == 1 else g.p2_id
        s.add(g); s.commit(); return g

@app.post("/move/{game_id}")
def move(game_id: str, player_id: str, move: MoveEnum):
    _submit(game_id, player_id, move)
    return {"status": "ok"}

@app.get("/state/{game_id}")
def state(game_id: str):
    with Session(engine) as s:
        g = s.get(Match, game_id)
        if not g: raise HTTPException(404, "Game not found")
        return g.dict()

# ---------- WebSocket ----------
connections: Dict[str, Set[WebSocket]] = {}

@app.websocket("/ws/{game_id}/{player_id}")
async def ws_game(ws: WebSocket, game_id: str, player_id: str):
    await ws.accept()
    connections.setdefault(game_id, set()).add(ws)
    try:
        while True:
            await ws.receive_text()  # ping
    except WebSocketDisconnect:
        connections[game_id].discard(ws)

async def broadcast(game_id: str, payload: dict):
    for ws in list(connections.get(game_id, [])):
        try:    await ws.send_json(payload)
        except RuntimeError:
            connections[game_id].discard(ws)

@app.post("/move_ws/{game_id}")
async def move_ws(game_id: str, player_id: str, move: MoveEnum, bg: BackgroundTasks):
    g = _submit(game_id, player_id, move)
    bg.add_task(broadcast, game_id, g.dict())
    return {"status": "ok"}
