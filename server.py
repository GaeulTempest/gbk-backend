import os, uuid, logging
from typing import Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select

# ───── FastAPI & DB ────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True
)

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")
engine  = create_engine(DB_URL, echo=False)

# ───── Model ───────────────────────────────
class Match(SQLModel, table=True):
    id:        str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id:     str
    p1_name:   str
    p1_ready:  bool = False
    p2_id:     Optional[str] = None
    p2_name:   Optional[str] = None
    p2_ready:  bool = False

class NewGameReq(BaseModel):  player_name: str
class JoinReq(BaseModel):     player_name: str
class ReadyReq(BaseModel):    player_id:   str

@app.on_event("startup")
def _init(): SQLModel.metadata.create_all(engine); log.info("DB ready")

# ───── helper broadcast ────────────────────
clients: dict[str, set[WebSocket]] = {}

def _state(g: Match):
    return {
        "players": {
            "A": {"id": g.p1_id, "name": g.p1_name, "ready": g.p1_ready},
            "B": {"id": g.p2_id, "name": g.p2_name, "ready": g.p2_ready},
        }
    }

async def _broadcast(g: Match):
    for ws in list(clients.get(g.id, [])):
        try: await ws.send_json(_state(g))
        except: clients[g.id].discard(ws)

# ───── REST endpoints ──────────────────────
@app.post("/create_game")
def create_game(body: NewGameReq):
    with Session(engine) as s:
        g = Match(p1_id=str(uuid.uuid4()), p1_name=body.player_name)
        s.add(g); s.commit(); s.refresh(g)
    return {"game_id": g.id, "player_id": g.p1_id, "role": "A"}

@app.post("/join/{gid}")
def join_game(gid: str, body: JoinReq):
    with Session(engine) as s:
        g = s.exec(select(Match).where(Match.id == gid)).first()
        if not g:            raise HTTPException(404, "Game not found")
        if g.p2_id:          raise HTTPException(400, "Game full")
        g.p2_id   = str(uuid.uuid4())
        g.p2_name = body.player_name
        s.add(g); s.commit(); s.refresh(g)
    # broadcast di luar session
    import asyncio; asyncio.create_task(_broadcast(g))
    return {"player_id": g.p2_id, "role": "B"}

@app.post("/ready/{gid}")
def set_ready(gid: str, body: ReadyReq):
    with Session(engine) as s:
        g = s.get(Match, gid)
        if not g or body.player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403)
        if body.player_id == g.p1_id: g.p1_ready = True
        else:                          g.p2_ready = True
        s.add(g); s.commit(); s.refresh(g)
    import asyncio; asyncio.create_task(_broadcast(g))
    return {"ok": True}

# ───── WebSocket ───────────────────────────
@app.websocket("/ws/{gid}/{pid}")
async def ws(gid: str, pid: str, ws: WebSocket):
    await ws.accept()
    clients.setdefault(gid, set()).add(ws)
    try:
        with Session(engine) as s:
            g = s.get(Match, gid)
            if g: await ws.send_json(_state(g))
        while True:
            await ws.receive_text()          # ignore incoming
    except WebSocketDisconnect:
        clients[gid].discard(ws)
