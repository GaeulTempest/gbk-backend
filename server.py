from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

MOVES_FILE = "moves.json"
STATS_FILE = "stats.json"
TIMEOUT = 60  # Timeout 60 detik

# Fungsi Load dan Save

def load_moves():
    if not os.path.exists(MOVES_FILE):
        return {}
    try:
        with open(MOVES_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_moves(data):
    with open(MOVES_FILE, "w") as f:
        json.dump(data, f)

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "Player A": {"win": 0, "lose": 0, "draw": 0},
            "Player B": {"win": 0, "lose": 0, "draw": 0}
        }
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {
            "Player A": {"win": 0, "lose": 0, "draw": 0},
            "Player B": {"win": 0, "lose": 0, "draw": 0}
        }

def save_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f)

# --- API Routes ---

@app.route('/')
def index():
    return jsonify({"message": "Server is running!"})

@app.route('/standby', methods=['POST'])
def standby():
    data = request.get_json()

    if not data or "player" not in data:
        return jsonify({"error": "Invalid request format. Expected 'player'."}), 400

    if data["player"] not in ["A", "B"]:
        return jsonify({"error": "Invalid player. Must be 'A' or 'B'."}), 400

    moves = load_moves()
    moves[f"{data['player']}_ready"] = True
    save_moves(moves)

    return jsonify({"status": f"Player {data['player']} is ready."})

@app.route('/get_moves', methods=['GET'])
def get_moves():
    moves = load_moves()
    return jsonify(moves)

@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()

    if not data or "player" not in data or "move" not in data:
        return jsonify({"error": "Invalid request format. Expected 'player' and 'move'."}), 400

    if data["player"] not in ["A", "B"]:
        return jsonify({"error": "Invalid player. Must be 'A' or 'B'."}), 400

    if data["move"] not in ["Batu", "Gunting", "Kertas"]:
        return jsonify({"error": "Invalid move. Must be 'Batu', 'Gunting', or 'Kertas'."}), 400

    moves = load_moves()
    if "timestamp" not in moves:
        moves["timestamp"] = time.time()

    moves[data["player"]] = data["move"]
    save_moves(moves)

    return jsonify({"status": "Move received successfully."})

@app.route('/result', methods=['GET'])
def result():
    moves = load_moves()

    if "timestamp" in moves:
        elapsed = time.time() - moves["timestamp"]
        if elapsed > TIMEOUT:
            save_moves({})
            return jsonify({"status": "Timeout"})

    if "result_ready" in moves and moves["result_ready"]:
        return jsonify({
            "A": moves.get("A"),
            "B": moves.get("B"),
            "result": moves.get("result")
        })

    if "A" in moves and "B" in moves:
        a = moves["A"]
        b = moves["B"]

        if a == b:
            winner = "Seri"
        elif (a == "Batu" and b == "Gunting") or (a == "Gunting" and b == "Kertas") or (a == "Kertas" and b == "Batu"):
            winner = "Player A Menang"
        else:
            winner = "Player B Menang"

        # Update Statistik
        stats = load_stats()
        if winner == "Seri":
            stats["Player A"]["draw"] += 1
            stats["Player B"]["draw"] += 1
        elif winner == "Player A Menang":
            stats["Player A"]["win"] += 1
            stats["Player B"]["lose"] += 1
        else:
            stats["Player A"]["lose"] += 1
            stats["Player B"]["win"] += 1
        save_stats(stats)

        moves["result"] = winner
        moves["result_ready"] = True
        save_moves(moves)

        return jsonify({
            "A": a,
            "B": b,
            "result": winner
        })

    return jsonify({"status": "Waiting for opponent's move..."})

@app.route('/stats', methods=['GET'])
def stats():
    stats = load_stats()
    return jsonify(stats)

@app.route('/reset', methods=['POST'])
def reset():
    save_moves({})
    return jsonify({"status": "Game reset successfully."})

# Start Server
if __name__ == '__main__':
    if not os.path.exists(MOVES_FILE):
        save_moves({})
    if not os.path.exists(STATS_FILE):
        save_stats({
            "Player A": {"win": 0, "lose": 0, "draw": 0},
            "Player B": {"win": 0, "lose": 0, "draw": 0}
        })
    app.run(host='0.0.0.0', port=8080)
