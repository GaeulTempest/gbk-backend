import os, uuid, logging, asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select

# ── logging ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

# ── FastAPI & CORS ─────────────────────────────────────────
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True)

# ── database ───────────────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")
engine  = create_engine(DB_URL, echo=False)

class Match(SQLModel, table=True):
    id:        str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id:     str
    p1_name:   str
    p1_ready:  bool = False
    p2_id:     Optional[str] = None
    p2_name:   Optional[str] = None
    p2_ready:  bool = False

@app.on_event("startup")
def init_db():
    SQLModel.metadata.create_all(engine)
    log.info("DB ready")

# ── request schemas ───────────────────────────────────────
class NewGame(BaseModel):  player_name: str
class JoinReq(BaseModel):  player_name: str
class ReadyReq(BaseModel): player_id  : str

# ── websocket hub ─────────────────────────────────────────
clients: dict[str, set[WebSocket]] = {}

def state(g: Match) -> dict:
    return {
        "players": {
            "A": {"id": g.p1_id, "name": g.p1_name, "ready": g.p1_ready},
            "B": {"id": g.p2_id, "name": g.p2_name, "ready": g.p2_ready},
        }
    }

async def broadcast(g: Match):
    for ws in list(clients.get(g.id, [])):
        try:
            await ws.send_json(state(g))
        except Exception:
            clients[g.id].discard(ws)

# ── REST endpoints ────────────────────────────────────────
@app.post("/create_game")
def create_game(body: NewGame):
    name = body.player_name.strip()
    if not name:
        raise HTTPException(400, "player_name required")

    with Session(engine) as s:
        game = Match(p1_id=str(uuid.uuid4()), p1_name=name)
        s.add(game); s.commit(); s.refresh(game)

    return {"game_id": game.id, "player_id": game.p1_id, "role": "A"}

@app.post("/join/{gid}")
async def join_game(gid: str, body: JoinReq):
    name = body.player_name.strip()
    if not name:
        raise HTTPException(400, "player_name required")

    with Session(engine) as s:
        g = s.exec(select(Match).where(Match.id == gid)).first()
        if not g:          raise HTTPException(404, "Game not found")
        if g.p2_id:        raise HTTPException(400, "Game already has 2 players")

        g.p2_id, g.p2_name = str(uuid.uuid4()), name
        s.add(g); s.commit(); s.refresh(g)

    await broadcast(g)
    return {"player_id": g.p2_id, "role": "B"}

@app.post("/ready/{gid}")
async def set_ready(gid: str, body: ReadyReq):
    with Session(engine) as s:
        g = s.get(Match, gid)
        if not g or body.player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403)

        if body.player_id == g.p1_id:
            g.p1_ready = True
        else:
            g.p2_ready = True

        s.add(g); s.commit(); s.refresh(g)

    await broadcast(g)
    return {"ok": True}

# ── WebSocket endpoint ───────────────────────────────────
@app.websocket("/ws/{gid}/{pid}")
async def ws_handler(gid: str, pid: str, ws: WebSocket):
    await ws.accept()
    clients.setdefault(gid, set()).add(ws)

    try:
        with Session(engine) as s:
            g = s.get(Match, gid)
            if g: await ws.send_json(state(g))

        while True:
            await ws.receive_text()   # ignore payload
    except WebSocketDisconnect:
        clients[gid].discard(ws)
