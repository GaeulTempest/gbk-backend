import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, SQLModel, Session, create_engine

# ----------------- FastAPI instance -----------------
app = FastAPI()

# ----------------- CORS Middleware -----------------
# Menambahkan CORS untuk memungkinkan akses dari semua origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Mengizinkan semua origin
    allow_credentials=True,
    allow_methods=["*"],  # Mengizinkan semua metode HTTP
    allow_headers=["*"],  # Mengizinkan semua header
)

# ----------------- Database Setup -----------------
# URL database, dapat menggunakan PostgreSQL atau SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")  # Default ke SQLite jika tidak ada URL
engine = create_engine(DATABASE_URL, echo=True)

# ----------------- Database Model -----------------
# Model untuk menyimpan data pertandingan
class Match(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    p1_id: str
    p2_id: str | None = None
    p1_move: str | None = None
    p2_move: str | None = None
    winner: str | None = None

# ----------------- Create Tables -----------------
# Buat tabel di database jika belum ada
@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# ----------------- API Endpoints -----------------
@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

# Endpoint untuk membuat game baru
@app.post("/create_game")
def create_game():
    new_game = Match(p1_id=str(uuid.uuid4()))
    with Session(engine) as session:
        session.add(new_game)
        session.commit()
        session.refresh(new_game)
    return {"game_id": new_game.id, "player_id": new_game.p1_id}

# Endpoint untuk bergabung ke game
@app.post("/join/{game_id}")
def join_game(game_id: str):
    with Session(engine) as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if game.p2_id:
            raise HTTPException(status_code=400, detail="Game full")
        game.p2_id = str(uuid.uuid4())
        session.add(game)
        session.commit()
        session.refresh(game)
    return {"player_id": game.p2_id}

# Endpoint untuk mengirimkan gerakan pemain (Rock, Paper, Scissors)
@app.post("/move/{game_id}")
def move(game_id: str, player_id: str, move: str):
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
        
        # Menilai pemenang jika kedua pemain sudah mengirimkan gerakan
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
    return {"status": "ok", "winner": game.winner}

# Endpoint untuk melihat status game
@app.get("/state/{game_id}")
def get_game_state(game_id: str):
    with Session(engine) as session:
        game = session.get(Match, game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        return game.dict()

