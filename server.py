import os, uuid, logging, asyncio, random
from typing import Optional, Dict, Set
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine
from contextlib import contextmanager

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
    id: str = Field(default_factory=lambda: str(random.randint(10000, 99999)), primary_key=True)  # 5-digit ID
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
        # Membuat ID game 5 digit secara acak
        game_id = str(random.randint(10000, 99999))  # 5-digit ID
        game = Match(id=game_id, p1_name=request.player_name)
        session.add(game)
        return {
            "game_id": game.id,
            "player_id": game.p1_id,
            "role": "A"
        }

class JoinGameRequest(BaseModel):
    player_name: str

@app.post("/join/{game_id}")
def join_game(game_id: str, request: JoinGameRequest):
    with get_session() as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        
        if game.p2_id:
            raise HTTPException(400, "Game is full")
        
        game.p2_id = str(uuid.uuid4())
        game.p2_name = request.player_name
        return {
            "game_id": game.id,
            "player_id": game.p2_id,
            "role": "B"
        }

@app.post("/ready/{game_id}")
def set_ready(game_id: str, player_id: str = Body(..., embed=True)):
    with get_session() as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        
        if player_id == game.p1_id:
            game.p1_ready = True
        elif player_id == game.p2_id:
            game.p2_ready = True
        else:
            raise HTTPException(403, "Invalid player")
        
        # Kembalikan status permainan terbaru untuk mengirim ke semua pemain
        return game_state(game)

@app.get("/state/{game_id}")
def get_game_state(game_id: str):
    with get_session() as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        
        return {
            "players": {
                "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
                "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready} 
                if game.p2_id else None,
            },
            "is_active": game.is_active
        }

# ——— Helpers ————————————————————————
def game_state(game: Match) -> dict:
    return {
        "players": {
            "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
            "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready} 
            if game.p2_id else None,
        },
        "is_active": game.is_active
    }
