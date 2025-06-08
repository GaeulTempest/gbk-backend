import os, uuid, logging, asyncio
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
    id: str = Field(default_factory=lambda: str(random.randint(10000, 99999)), primary_key=True)  # 5-digit random number
    p1_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    p1_name: str
    p1_ready: bool = False
    p2_id: Optional[str] = None
    p2_name: Optional[str] = None
    p2_ready: bool = False
    p1_move: Optional[str] = None
    p2_move: Optional[str] = None
    is_active: bool = True

# ——— WebSocket Management ———————————
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, game_id: str, player_id: str, websocket: WebSocket):
        await websocket.accept()
        if game_id not in self.active_connections:
            self.active_connections[game_id] = set()

        # Validate if player_id matches with the game
        game = self.get_game(game_id)
        if not game:
            log.error(f"Game {game_id} does not exist.")
            await websocket.close(code=1008)  # Close with abnormal closure code
            return

        if player_id not in [game.p1_id, game.p2_id]:
            log.error(f"Player {player_id} not part of the game {game_id}.")
            await websocket.close(code=1008)  # Close with abnormal closure code
            return

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

    def get_game(self, game_id: str) -> Optional[Match]:
        """Retrieve game information from the database."""
        with get_session() as session:
            game = session.get(Match, game_id)
            return game

manager = ConnectionManager()

# ——— API Endpoints ——————————————————
class CreateGameRequest(BaseModel):
    player_name: str

@app.post("/create_game")
def create_game(request: CreateGameRequest):
    with get_session() as session:
        game_id = str(random.randint(10000, 99999))  # 5-digit random number
        game = Match(id=game_id, p1_name=request.player_name)
        session.add(game)
        session.commit()
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

# ——— WebSocket Endpoint ——————————————
@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str):
    try:
        await manager.connect(game_id, player_id, websocket)
        log.info(f"Player {player_id} connected to game {game_id}")

        try:
            while True:
                await websocket.receive_text()
                state = get_game_state(game_id)
                await manager.broadcast(game_id, state)
                
        except WebSocketDisconnect:
            manager.disconnect(game_id, websocket)
            log.info(f"Player {player_id} disconnected from game {game_id}")
            
    except Exception as e:
        log.error(f"WebSocket error for game {game_id}, player {player_id}: {str(e)}")
