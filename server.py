import os, uuid, logging
from typing import Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select

# ───── FastAPI & DB ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO); log = logging.getLogger("srv")
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")
engine  = create_engine(DB_URL, echo=False)

class Match(SQLModel, table=True):
    id        : str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id     : str
    p1_name   : str
    p1_ready  : bool = False
    p2_id     : Optional[str] = None
    p2_name   : Optional[str] = None
    p2_ready  : bool = False

class NewGameReq(BaseModel):  player_name: str
class JoinReq     (BaseModel):  player_name: str
class ReadyReq    (BaseModel):  player_id  : str

@app.on_event("startup")
def _init(): SQLModel.metadata.create_all(engine); log.info("DB ready")

# ───── helpers ───────────────────────────────────────────────────
def _broadcast(game: Match, msg: dict):
    # naive in-proc websockets hub
    for ws in clients.get(game.id, []):
        try: ws.send_json(msg)
        except: pass

def _state(game: Match):
    return {
        "players": {
            "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
            "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready},
        }
    }

# ───── endpoints ─────────────────────────────────────────────────
@app.post("/create_game")
def create_game(body: NewGameReq):
    with Session(engine) as s:
        g = Match(p1_id=str(uuid.uuid4()), p1_name=body.player_name)
        s.add(g); s.commit(); s.refresh(g)
        return {"game_id": g.id, "player_id": g.p1_id, "role": "A"}

@app.post("/join/{gid}")
def join_game(gid: str, body: JoinReq):
    with Session(engine) as s:
        g = s.exec(select(Match).where(Match.id==gid)).first()
        if not g:         raise HTTPException(404,"Game not found")
        if g.p2_id:       raise HTTPException(400,"Game full")
        g.p2_id   = str(uuid.uuid4())
        g.p2_name = body.player_name
        s.add(g); s.commit(); s.refresh(g)
        _broadcast(g, _state(g))
        return {"player_id": g.p2_id, "role": "B"}

@app.post("/ready/{gid}")
def set_ready(gid:str, body:ReadyReq):
    with Session(engine) as s:
        g=s.get(Match,gid);  p=body.player_id
        if not g or p not in {g.p1_id,g.p2_id}: raise HTTPException(403)
        if p==g.p1_id: g.p1_ready=True
        else:          g.p2_ready=True
        s.add(g); s.commit(); s.refresh(g)
        _broadcast(g, _state(g))
        return {"ok":True}

# ───── WebSocket hub ─────────────────────────────────────────────
clients: dict[str,set[WebSocket]] = {}

@app.websocket("/ws/{gid}/{pid}")
async def ws(gid:str, pid:str, ws:WebSocket):
    await ws.accept()
    clients.setdefault(gid,set()).add(ws)
    try:
        with Session(engine) as s:
            g=s.get(Match,gid)
            if g: await ws.send_json(_state(g))
        while True:
            await ws.receive_text()          # we don't expect messages, ignore
    except WebSocketDisconnect:
        clients[gid].discard(ws)
