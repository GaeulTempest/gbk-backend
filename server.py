from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

MOVES_FILE = "moves.json"
STATS_FILE = "stats.json"
TIMEOUT = 60  # 60 detik timeout game

# Load data moves
def load_moves():
    if not os.path.exists(MOVES_FILE):
        return {}
    try:
        with open(MOVES_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

# Save data moves
def save_moves(data):
    with open(MOVES_FILE, "w") as f:
        json.dump(data, f)

# Load statistik
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"Player A": {"win": 0, "lose": 0, "draw": 0},
                "Player B": {"win": 0, "lose": 0, "draw": 0}}
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {"Player A": {"win": 0, "lose": 0, "draw": 0}}

# Save statistik
def save_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f)

# --- API ROUTES ---

@app.route('/')
def index():
    return jsonify({"message": "Server is running!"})

@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()

    if not data or "player" not in data or "move" not in data:
        return jsonify({"error": "Invalid request."}), 400

    moves = load_moves()
    if "timestamp" not in moves:
        moves["timestamp"] = time.time()

    moves[data["player"]] = data["move"]
    moves[f"{data['player']}_ready"] = True
    save_moves(moves)

    print(f"[SUBMIT] {data['player']} -> {data['move']}")
    return jsonify({"status": "Move received."})

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

        # Update statistik
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

        print(f"[RESULT] {winner}")
        return jsonify({
            "A": a,
            "B": b,
            "result": winner
        })

    return jsonify({"status": "Waiting for opponent's move..."})

@app.route('/standby', methods=['POST'])
def standby():
    data = request.get_json()
