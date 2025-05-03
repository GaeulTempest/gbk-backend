# ----------------- server.py -----------------
"""FastAPI backend providing REST + WebSocket for real‑time updates.

* SQLite (via SQLModel) for atomic state storage.
* Each match identified by UUID game_id; each player by UUID player_id.
* Simple bearer token (player_id) used for auth.
• WebSocket channel /ws/{game_id}/{player_id} → pushes state changes.
"""

import os
import uuid
from enum import Enum
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, SQLModel, create_engine, Session, select

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///rps.db")
engine = create_engine(DATABASE_URL, echo=False)

app = FastAPI(title="RPS Gesture Game API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
    winner: Optional[str] = None  # player_id

SQLModel.metadata.create_all(engine)

# ---------- helpers ----------

def judge(m1: MoveEnum, m2: MoveEnum) -> int:
    """Return 0 draw, 1 if p1 wins, 2 if p2 wins."""
    rules = {
        (MoveEnum.rock, MoveEnum.scissors): 1,
        (MoveEnum.scissors, MoveEnum.paper): 1,
        (MoveEnum.paper, MoveEnum.rock): 1,
    }
    if m1 == m2:
        return 0
    return 1 if rules.get((m1, m2)) == 1 else 2

# ---------- REST endpoints ----------

@app.post("/create_game")
def create_game():
    game_id = str(uuid.uuid4())
    p1_id = str(uuid.uuid4())
    match = Match(id=game_id, p1_id=p1_id)
    with Session(engine) as sess:
        sess.add(match)
        sess.commit()
    return {"game_id": game_id, "player_id": p1_id}

@app.post("/join/{game_id}")
def join_game(game_id: str):
    p2_id = str(uuid.uuid4())
    with Session(engine) as sess:
        match = sess.get(Match, game_id)
        if not match:
            raise HTTPException(status_code=404, detail="Game not found")
        if match.p2_id:
            raise HTTPException(status_code=400, detail="Game full")
        match.p2_id = p2_id
        sess.add(match)
        sess.commit()
    return {"player_id": p2_id}

@app.post("/move/{game_id}")
def submit_move(game_id: str, player_id: str, move: MoveEnum):
    with Session(engine) as sess:
        match = sess.get(Match, game_id)
        if not match or player_id not in {match.p1_id, match.p2_id}:
            raise HTTPException(status_code=403, detail="Invalid player")
        if player_id == match.p1_id:
            match.p1_move = move
        else:
            match.p2_move = move

        # judge if both moves present
        if match.p1_move and match.p2_move and not match.winner:
            res = judge(match.p1_move, match.p2_move)
            if res == 0:
                match.winner = "draw"
            elif res == 1:
                match.winner = match.p1_id
            else:
                match.winner = match.p2_id
        sess.add(match)
        sess.commit()
    return {"status": "ok"}

@app.get("/state/{game_id}")
def get_state(game_id: str):
    with Session(engine) as sess:
        match = sess.get(Match, game_id)
        if not match:
            raise HTTPException(status_code=404, detail="Game not found")
        return match.dict()

# ---------- WebSocket ----------

connections = {}

@app.websocket("/ws/{game_id}/{player_id}")
async def ws_game(websocket: WebSocket, game_id: str, player_id: str):
    await websocket.accept()
    connections.setdefault(game_id, set()).add(websocket)
    try:
        while True:
            # keep alive ping‑pong
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections[game_id].remove(websocket)

# small utility to broadcast update
async def broadcast(game_id: str, payload: dict):
    import asyncio
    for ws in list(connections.get(game_id, [])):
        try:
            await ws.send_json(payload)
        except RuntimeError:
            connections[game_id].discard(ws)
    await asyncio.sleep(0)  # yield

# call broadcast after each move using FastAPI event hook
from fastapi import BackgroundTasks

@app.post("/move_ws/{game_id}")
async def ws_submit_move(game_id: str, player_id: str, move: MoveEnum, background_tasks: BackgroundTasks):
    submit_move(game_id, player_id, move)  # reuse logic
    state = get_state(game_id)
    background_tasks.add_task(broadcast, game_id, state)
    return {"status": "ok"}
