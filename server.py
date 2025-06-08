import os, uuid, logging, random
from typing import Optional
from fastapi import FastAPI, HTTPException, Body
from sqlmodel import SQLModel, Field, Session, create_engine
from pydantic import BaseModel
from contextlib import contextmanager

# ——— Configuration ——————————————————
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

app = FastAPI()

# Database URL setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

# ——— Models —————————————————————————
class Match(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(random.randint(10000, 99999)), primary_key=True)  # 5-digit random number
    p1_id: str
    p1_name: str
    p1_ready: bool = False
    p2_id: Optional[str] = None
    p2_name: Optional[str] = None
    p2_ready: bool = False
    is_active: bool = True

# Database session management
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

# ——— API Endpoints ——————————————————

# Create game endpoint
class CreateGameRequest(BaseModel):
    player_name: str

@app.post("/create_game")
def create_game(request: CreateGameRequest):
    with get_session() as session:
        game_id = str(random.randint(10000, 99999))  # 5-digit random number
        game = Match(id=game_id, p1_name=request.player_name, p1_id=str(uuid.uuid4()))
        session.add(game)
        session.commit()
        return {
            "game_id": game.id,
            "player_id": game.p1_id,
            "role": "A"
        }

# Join game endpoint
class JoinGameRequest(BaseModel):
    player_name: str

@app.post("/join/{game_id}")
def join_game(game_id: str, request: JoinGameRequest):
    with get_session() as session:
        game = session.get(Match, game_id)
        if not game:
            log.error(f"Game with ID {game_id} not found in the database.")
            raise HTTPException(404, "Game not found")
        
        if game.p2_id:
            raise HTTPException(400, "Game is full")
        
        game.p2_id = str(uuid.uuid4())
        game.p2_name = request.player_name
        session.add(game)
        session.commit()
        
        log.info(f"Player {request.player_name} successfully joined the game.")
        return {
            "game_id": game.id,
            "player_id": game.p2_id,
            "role": "B"
        }

# Set player as ready
@app.post("/ready/{game_id}")
def set_ready(game_id: str, player_id: str = Body(..., embed=True)):
    with get_session() as session:
        # Retrieve the game from the database
        game = session.get(Match, game_id)
        if not game:
            log.error(f"Game {game_id} not found.")
            raise HTTPException(status_code=404, detail="Game not found")
        
        # Check if the player exists in the game
        if player_id == game.p1_id:
            game.p1_ready = True
        elif player_id == game.p2_id:
            game.p2_ready = True
        else:
            raise HTTPException(status_code=403, detail="Player not part of the game")
        
        # Update game state
        session.add(game)
        session.commit()
        return {
            "game_id": game.id,
            "p1_ready": game.p1_ready,
            "p2_ready": game.p2_ready
        }

# Get game state
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
