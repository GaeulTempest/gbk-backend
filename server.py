import os, uuid, logging, asyncio, random
from typing import Optional, Dict, Set
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine
from contextlib import contextmanager
import requests

# ——— Configuration ——————————————————
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")

# ——— Database Setup —————————————————
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

@contextmanager
def get_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            log.error(f"Database error: {str(e)}")
            raise
        finally:
            session.close()

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# ——— Models —————————————————————————
class Match(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(random.randint(10000, 99999)), primary_key=True)
    p1_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    p1_name: str
    p1_ready: bool = False
    p2_id: Optional[str] = None
    p2_name: Optional[str] = None
    p2_ready: bool = False
    p1_move: Optional[str] = None
    p2_move: Optional[str] = None
    is_active: bool = True

# ——— API Endpoints ——————————————————
class CreateGameRequest(BaseModel):
    player_name: str

@app.post("/create_game")
def create_game(request: CreateGameRequest):
    with get_session() as session:
        game_id = str(random.randint(10000, 99999))
        game = Match(id=game_id, p1_name=request.player_name)
        session.add(game)
        return {
            "game_id": game.id,
            "player_id": game.p1_id,
            "role": "A"
        }

# ——— STUN/TURN Configuration Endpoint ——————————————————
@app.get("/stun_turn_config")
def get_stun_turn_config():
    try:
        # Xirsys API credentials
        ident = "wawanshot"
        secret = "6ebc02ec-4257-11f0-9543-aa614b70fb40"
        channel = "multiplayergbk"

        # URL to get STUN/TURN servers from Xirsys
        url = "https://global.xirsys.net/_turn/"
        headers = {
            "Authorization": f"Basic {ident}:{secret}"
        }
        data = {"channel": channel}
        response = requests.post(url, headers=headers, data=data)

        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=500, detail=f"Failed to fetch STUN/TURN servers: {response.text}")
    except requests.RequestException as e:
        log.error(f"Error when accessing STUN/TURN API: {str(e)}")
        raise HTTPException(status_code=500, detail="Error when accessing STUN/TURN API.")
    except Exception as e:
        log.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper Functions for Game State
def game_state(game: Match) -> dict:
    return {
        "players": {
            "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
            "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready} 
            if game.p2_id else None,
        },
        "is_active": game.is_active
    }
