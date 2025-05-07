import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, SQLModel, Session, create_engine
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI instance
app = FastAPI()

# CORS Middleware to allow all origins (adjust for your security needs)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # This allows all origins, modify this for production
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")  # Default SQLite if not set
engine = create_engine(DATABASE_URL, echo=True)

# SQLModel for creating the database table
class Match(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id: str
    p2_id: str | None = None
    p1_name: str  # Added player name for player 1
    p2_name: str | None = None  # Added player name for player 2
    p1_move: str | None = None
    p2_move: str | None = None
    winner: str | None = None

# Create the tables when the app starts
@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    logger.info("Database tables created.")

# Pydantic model to validate request data for creating game and joining game
class CreateGameRequest(BaseModel):
    player_name: str

class JoinGameRequest(BaseModel):
    player_name: str

# Endpoint to create a new game
@app.post("/create_game")
def create_game(request: CreateGameRequest):
    player_name = request.player_name
    logger.info(f"Creating new game for player: {player_name}")
    if not player_name:
        raise HTTPException(status_code=400, detail="Player name is required")
    
    new_game = Match(p1_id=str(uuid.uuid4()), p1_name=player_name)
    with Session(engine) as session:
        session.add(new_game)
        session.commit()
        session.refresh(new_game)
    
    logger.info(f"New game created with ID: {new_game.id}")
    return {"game_id": new_game.id, "player_id": new_game.p1_id, "player_name": new_game.p1_name}

# Endpoint for a player to join an existing game (using POST)
@app.post("/join/{game_id}")
# Endpoint untuk pemain bergabung dengan game yang sudah ada (menggunakan POST)
@app.post("/join/{game_id}")
def join_game(game_id: str, request: JoinGameRequest):
    player_name = request.player_name
    logger.info(f"Player {player_name} trying to join game with ID: {game_id}")
    
    if not player_name:
        raise HTTPException(status_code=400, detail="Player name is required")
    
    with Session(engine) as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if game.p2_id:
            raise HTTPException(status_code=400, detail="Game is full")
        game.p2_id = str(uuid.uuid4())
        game.p2_name = player_name
        session.add(game)
        session.commit()
        session.refresh(game)
    
    logger.info(f"Player {player_name} joined the game. Game ID: {game_id}")
    return {"player_id": game.p2_id, "player_name": game.p2_name}


# Endpoint to get the current state of the game
@app.get("/state/{game_id}")
def get_game_state(game_id: str):
    logger.info(f"Fetching state for game with ID: {game_id}")
    with Session(engine) as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        return game.dict()

# Endpoint to handle the moves of each player
@app.post("/move/{game_id}")
def move(game_id: str, player_id: str, move: str):
    logger.info(f"Player {player_id} making move in game {game_id}: {move}")
    with Session(engine) as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if player_id == game.p1_id:
            game.p1_move = move
        elif player_id == game.p2_id:
            game.p2_move = move
        else:
            raise HTTPException(status_code=400, detail="Player not in game")
        
        # Determine winner if both players have made their moves
        if game.p1_move and game.p2_move and not game.winner:
            if game.p1_move == game.p2_move:
                game.winner = "draw"
            elif (game.p1_move == "rock" and game.p2_move == "scissors") or \
                 (game.p1_move == "scissors" and game.p2_move == "paper") or \
                 (game.p1_move == "paper" and game.p2_move == "rock"):
                game.winner = game.p1_id
            else:
                game.winner = game.p2_id
        
        session.add(game)
        session.commit()
        session.refresh(game)
    logger.info(f"Game {game_id} updated. Winner: {game.winner if game.winner else 'TBD'}")
    return {"status": "ok", "winner": game.winner}
