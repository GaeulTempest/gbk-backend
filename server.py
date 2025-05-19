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
    is_active: bool = True  # Status apakah game masih aktif

def state(g: Match) -> dict:
    return {
        "players": {
            "A": {"id": g.p1_id, "name": g.p1_name, "ready": g.p1_ready},
            "B": {"id": g.p2_id, "name": g.p2_name, "ready": g.p2_ready},
        },
        "moves": {"A": g.p1_move, "B": g.p2_move}
    }

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

    # Verifikasi Game ID dan Player ID
    with Session(engine) as sess:
        g = sess.get(Match, gid)
        
        if not g or not g.is_active:
            # Jika game tidak ditemukan atau sudah tidak aktif, kirimkan error dan tutup koneksi
            log.error(f"Game ID {gid} not found or not active.")
            await ws.send_json({"error": "Game not found or already ended"})
            await ws.close()
            return
        
        if pid not in {g.p1_id, g.p2_id}:
            log.error(f"Player ID {pid} is not valid for this game.")
            await ws.send_json({"error": "Player not found in this game"})
            await ws.close()
            return

        # Kirim status game ke pemain
        await ws.send_json(state(g))

    try:
        while True:
            # Tunggu pesan dari klien dan pastikan koneksi tetap stabil
            await ws.receive_text()

    except WebSocketDisconnect:
        log.info(f"Connection to game {gid} player {pid} closed.")
        if gid in clients:
            clients[gid].discard(ws)
    except Exception as e:
        log.error(f"WebSocket error: {e}")
    finally:
        # Pastikan WebSocket selalu ditutup dengan benar
        await ws.close()
