import os
import uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    p1_name: str
    p2_name: str | None = None
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
        try:
            session.commit()  # Commit transaction to save new game
            session.refresh(new_game)  # Refresh the game object after commit
        except Exception as e:
            logger.error(f"Error while committing game creation: {e}")
            session.rollback()  # Rollback if there is an error
            raise HTTPException(status_code=500, detail="Error creating the game")
    
    logger.info(f"New game created with ID: {new_game.id}")
    return {"game_id": new_game.id, "player_id": new_game.p1_id, "player_name": new_game.p1_name}

# Endpoint for a player to join an existing game (using POST)
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

# WebSocket endpoint for player communication during the game
@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str):
    with Session(engine) as session:
        game = session.get(Match, game_id)
        if not game:
            await websocket.close(code=4000)  # Invalid game
            return
        if player_id not in [game.p1_id, game.p2_id]:
            await websocket.close(code=4001)  # Invalid player
            return
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Process the data received from the player
            await websocket.send_text(f"Data received: {data}")
    except WebSocketDisconnect:
        logger.info(f"Player {player_id} disconnected from game {game_id}")
