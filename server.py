import os, uuid, logging, asyncio
from typing import Optional, Dict, Set
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine

# ——— Logging & App Init ——————————————————
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

# ——— Model —————————————————
class Match(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id: str
    p1_name: str
    p1_ready: bool = False
    p2_id: Optional[str] = None
    p2_name: Optional[str] = None
    p2_ready: bool = False
    p1_move: Optional[str] = None
    p2_move: Optional[str] = None

def state(g: Match) -> dict:
    return {
        "players": {
            "A": {"id": g.p1_id, "name": g.p1_name, "ready": g.p1_ready},
            "B": {"id": g.p2_id, "name": g.p2_name, "ready": g.p2_ready},
        },
        "moves": {"A": g.p1_move, "B": g.p2_move}
    }

# ——— Schemas —————————————————
class NewGame(BaseModel): player_name: str
class JoinReq(BaseModel): player_name: str
class ReadyReq(BaseModel): player_id: str
class MoveReq(BaseModel): player_id: str; move: str

# ——— Startup —————————————————
@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    log.info("DB ready")

# ——— HTTP Endpoints —————————————————
@app.post("/create_game")
def create_game(body: NewGame):
    name = body.player_name.strip()
    if not name:
        raise HTTPException(400, "player_name empty")
    with Session(engine) as sess:
        g = Match(p1_id=str(uuid.uuid4()), p1_name=name)
        sess.add(g); sess.commit(); sess.refresh(g)
    return {"game_id": g.id, "player_id": g.p1_id, "role": "A"}

@app.post("/join/{gid}")
def join_game(gid: str, body: JoinReq):
    name = body.player_name.strip()
    if not name:
        raise HTTPException(400, "player_name empty")
    with Session(engine) as sess:
        g = sess.get(Match, gid)
        if not g:
            raise HTTPException(404, "Game not found")
        if g.p2_id:
            raise HTTPException(400, "Room full")
        g.p2_id, g.p2_name = str(uuid.uuid4()), name
        sess.add(g); sess.commit(); sess.refresh(g)
    broadcast(g)
    return {"player_id": g.p2_id, "role": "B"}

@app.post("/ready/{gid}")
def set_ready(gid: str, body: ReadyReq):
    with Session(engine) as sess:
        g = sess.get(Match, gid)
        if not g or body.player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player or game")
        if body.player_id == g.p1_id:
            g.p1_ready = True
        else:
            g.p2_ready = True
        sess.add(g); sess.commit(); sess.refresh(g)
    broadcast(g)
    return state(g)

@app.post("/move/{gid}")
def submit_move(gid: str, body: MoveReq):
    with Session(engine) as sess:
        g = sess.get(Match, gid)
        if not g or body.player_id not in {g.p1_id, g.p2_id}:
            raise HTTPException(403, "Invalid player or game")
        if body.player_id == g.p1_id:
            g.p1_move = body.move
        else:
            g.p2_move = body.move
        sess.add(g); sess.commit(); sess.refresh(g)
    broadcast(g)
    return state(g)

@app.get("/state/{gid}")
def get_state_endpoint(gid: str):
    with Session(engine) as sess:
        g = sess.get(Match, gid)
        if not g:
            raise HTTPException(404, "Game not found")
        return state(g)

# ——— WebSocket Broadcast —————————————————
clients: Dict[str, Set[WebSocket]] = {}

async def _send(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
    except Exception as e:
        log.error(f"Error sending data: {e}")
        pass  # handle errors gracefully

def broadcast(game: Match):
    payload = state(game)
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        pass
    for ws in list(clients.get(game.id, [])):
        if loop and loop.is_running():
            loop.call_soon_threadsafe(asyncio.create_task, _send(ws, payload))

@app.websocket("/ws/{gid}/{pid}")
async def ws_endpoint(gid: str, pid: str, ws: WebSocket):
    await ws.accept()
    clients.setdefault(gid, set()).add(ws)
    try:
        with Session(engine) as sess:
            g = sess.get(Match, gid)
            if g:
                await ws.send_json(state(g))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        log.info(f"Connection to game {gid} player {pid} closed.")
        clients[gid].discard(ws)
        break
    finally:
        await ws.close()
