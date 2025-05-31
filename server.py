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
    allow_origins=["*"],  # Sesuaikan dengan kebutuhan Anda
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
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
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

# ——— API Endpoints ——————————————————
class CreateGameRequest(BaseModel):
    player_name: str

@app.post("/create_game")
def create_game(request: CreateGameRequest):
    try:
        # Validasi player_name
        if not request.player_name:
            raise HTTPException(status_code=400, detail="Player name is required")

        # Buat game baru
        with get_session() as session:
            game = Match(p1_name=request.player_name)
            session.add(game)
            session.commit()  # Pastikan untuk commit perubahan ke database
            log.info(f"Game created with ID {game.id} and Player {game.p1_name}")

            # Return response yang menyertakan ID game dan player ID
            return {
                "game_id": game.id,
                "player_id": game.p1_id,
                "role": "A"
            }
    except Exception as e:
        log.error(f"Error creating game: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create game")

# ——— WebSocket Endpoint ——————————————
@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str):
    try:
        with get_session() as session:
            game = session.get(Match, game_id)
            if not game or not game.is_active:
                await websocket.close(code=1008)
                return

            if player_id not in [game.p1_id, game.p2_id]:
                await websocket.close(code=1008)
                return

        await manager.connect(game_id, websocket)
        
        try:
            while True:
                await websocket.receive_text()
                state = get_game_state(game_id)
                await manager.broadcast(game_id, state)
                
        except WebSocketDisconnect:
            manager.disconnect(game_id, websocket)
            
    except Exception as e:
        log.error(f"WebSocket error: {str(e)}")
    finally:
        manager.disconnect(game_id, websocket)

# ——— Helpers ————————————————————————  
def game_state(game: Match) -> dict:
    return {
        "players": {
            "A": {"id": game.p1_id, "name": game.p1_name, "ready": game.p1_ready},
            "B": {"id": game.p2_id, "name": game.p2_name, "ready": game.p2_ready} 
            if game.p2_id else None,
        },
        "moves": {"A": game.p1_move, "B": game.p2_move},
        "is_active": game.is_active
    }
