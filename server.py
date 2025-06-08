import os, uuid, logging, random
from typing import Optional, Dict, Set
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine
from contextlib import contextmanager
import asyncio

# ——— Configuration ——————————————————
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("srv")

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins, you can restrict this for production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database URL setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rps.db")
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, game_id: str, websocket: WebSocket):
        await websocket.accept()
        if game_id not in self.active_connections:
            self.active_connections[game_id] = set()
        self.active_connections[game_id].add(websocket)

    def disconnect(self, game_id: str, websocket: WebSocket):
        if game_id in self.active_connections:
            self.active_connections[game_id].discard(websocket)
            if not self.active_connections[game_id]:
                del self.active_connections[game_id]

    async def broadcast(self, game_id: str, message: dict):
        if game_id in self.active_connections:
            for connection in self.active_connections[game_id].copy():
                try:
                    await connection.send_json(message)
                except Exception as e:
                    log.error(f"Broadcast error: {str(e)}")
                    self.disconnect(game_id, connection)

manager = ConnectionManager()

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

# ——— Database Setup —————————————————
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

# Set player as ready
@app.post("/ready/{game_id}")
async def set_ready(game_id: str, player_id: str = Body(..., embed=True)):
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

        # Broadcast updated state to all connected players via WebSocket
        message = {
            "game_id": game.id,
            "players": {
                "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
                "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready} if game.p2_id else None
            }
        }
        # Broadcast to all WebSocket clients
        await manager.broadcast(game_id, message)
        return message

# WebSocket Connection Endpoint
@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str):
    # Ensure that the WebSocket is connected only for valid game and player
    with get_session() as session:
        game = session.get(Match, game_id)
        if not game:
            await websocket.close(code=1008)
            raise HTTPException(status_code=404, detail="Game not found")

        if player_id not in [game.p1_id, game.p2_id]:
            await websocket.close(code=1008)
            raise HTTPException(status_code=403, detail="Player not part of the game")

    await manager.connect(game_id, websocket)
    
    try:
        while True:
            await websocket.receive_text()  # Keeps the connection alive
            # Send the current game state to the connected client
            with get_session() as session:
                game = session.get(Match, game_id)
                message = {
                    "game_id": game.id,
                    "players": {
                        "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
                        "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready} if game.p2_id else None
                    }
                }
                await websocket.send_json(message)
    except WebSocketDisconnect:
        manager.disconnect(game_id, websocket)
        log.info(f"Player {player_id} disconnected from game {game_id}")
