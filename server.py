import os
import uuid
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, dict] = {}
        self.connections: Dict[str, List[WebSocket]] = {}

    def create_room(self, owner_name: str, max_players: int = 2) -> dict:
        room_id = str(uuid.uuid4())
        self.rooms[room_id] = {
            "id": room_id,
            "owner": owner_name,
            "players": [owner_name],
            "max_players": max_players,
            "status": "waiting"
        }
        return self.rooms[room_id]
    
    def join_room(self, room_id: str, player_name: str) -> Optional[dict]:
        room = self.rooms.get(room_id)
        if room and len(room["players"]) < room["max_players"]:
            room["players"].append(player_name)
            return room
        return None

    def list_rooms(self) -> List[dict]:
        return [{
            "id": r["id"],
            "owner": r["owner"],
            "players": len(r["players"]),
            "max_players": r["max_players"],
            "status": r["status"]
        } for r in self.rooms.values() if r["status"] == "waiting"]

manager = RoomManager()

class ConnectionManager:
    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in manager.connections:
            manager.connections[room_id] = []
        manager.connections[room_id].append(websocket)

    async def broadcast(self, room_id: str, message: dict):
        if room_id in manager.connections:
            for connection in manager.connections[room_id]:
                await connection.send_json(message)

conn_manager = ConnectionManager()

@app.post("/create-room")
async def create_room(data: dict):
    room = manager.create_room(data["playerName"])
    return {"room": room}

@app.post("/join-room/{room_id}")
async def join_room(room_id: str, data: dict):
    room = manager.join_room(room_id, data["playerName"])
    if not room:
        raise HTTPException(400, "Room penuh atau tidak ditemukan")
    return {"room": room}

@app.get("/list-rooms")
async def list_rooms():
    return {"rooms": manager.list_rooms()}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await conn_manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_json()
            await conn_manager.broadcast(room_id, {
                "type": "update",
                "room": manager.rooms.get(room_id)
            })
    except WebSocketDisconnect:
        manager.connections[room_id].remove(websocket)
