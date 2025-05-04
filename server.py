# ----------------- server.py -----------------
"""FastAPI backend (REST + WebSocket) untuk Rock‑Paper‑Scissors Gesture.

• Penyimpanan SQLModel (SQLite / PostgreSQL via DATABASE_URL)
• Setiap match  UUID game_id, tiap pemain  UUID player_id
• WebSocket  /ws/{game_id}/{player_id}  men‑push status real‑time
"""

import os, uuid, asyncio
from enum import Enum
from typing import Optional, Set, Dict

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    HTTPException, BackgroundTasks
)
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, SQLModel, Session, create_engine
from fastapi import FastAPI
app = FastAPI()

# ---------- DB setup ----------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///rps.db")
engine = create_engine(DATABASE_URL, echo=False)

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
    winner: Optional[str] = None  # player_id / "draw"

# ---------- FastAPI ----------
app = FastAPI(title="RPS Gesture Game API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# ---------- util ----------
def judge(m1: MoveEnum, m2: MoveEnum) -> int:
    """0 draw, 1 p1 win, 2 p2 win"""
    beats = {
        (MoveEnum.rock, MoveEnum.scissors),
        (MoveEnum.scissors, MoveEnum.paper),
        (MoveEnum.paper, MoveEnum.rock),
    }
    if m1 == m2:
        return 0
    return 1 if (m1, m2) in beats else 2

# ---------- REST ----------
@app.post("/create_game")
def create_game():
    game = Match(id=str(uuid.uuid4()), p1_id=str(uuid.uuid4()))
    with Session(engine) as s:
        s.add(game); s.commit()
    return {"game_id": game.id, "player_id": game.p1_id}

@app.post("/join/{game_id}")
def join_game(game_id: str):
    with Session(engine) as s:
        game = s.get(Match, game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        if game.p2_id:
            raise HTTPException(400, "Game full")
        game.p2_id = str(uuid.uuid4())
        s.add(game); s.commit()
    return {"player_id": game.p2_id}

def _submit_move(game_id: str, player_id: str, move: MoveEnum):
    with Session(engine) as s:
        g: Match = s.get(Match, game_id)
        if not g or player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player")
        if player_id == g.p1_id:
            g.p1_move = move
        else:
            g.p2_move = move
        if g.p1_move and g.p2_move and not g.winner:
            res = judge(g.p1_move, g.p2_move)
            g.winner = (
                "draw" if res == 0 else g.p1_id if res == 1 else g.p2_id
            )
        s.add(g); s.commit()
        return g

@app.post("/move/{game_id}")
def submit_move(game_id: str, player_id: str, move: MoveEnum):
    _submit_move(game_id, player_id, move)
    return {"status": "ok"}

@app.get("/state/{game_id}")
def state(game_id: str):
    with Session(engine) as s:
        g = s.get(Match, game_id)
        if not g:
            raise HTTPException(404, "Game not found")
        return g.dict()

# ---------- WebSocket ----------
connections: Dict[str, Set[WebSocket]] = {}

@app.websocket("/ws/{game_id}/{player_id}")
async def ws_game(ws: WebSocket, game_id: str, player_id: str):
    await ws.accept()
    connections.setdefault(game_id, set()).add(ws)
    try:
        while True:
            # client pings setiap 20 detik  terima & buang
            await ws.receive_text()
    except WebSocketDisconnect:
        connections[game_id].discard(ws)

async def broadcast(game_id: str, payload: dict):
    for ws in list(connections.get(game_id, [])):
        try:
            await ws.send_json(payload)
        except RuntimeError:
            connections[game_id].discard(ws)

@app.post("/move_ws/{game_id}")
async def move_ws(
    game_id: str, player_id: str, move: MoveEnum,
    bg: BackgroundTasks
):
    game = _submit_move(game_id, player_id, move)
    bg.add_task(broadcast, game_id, game.dict())
    return {"status": "ok"}
