from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

MOVES_FILE = "moves.json"
TIMEOUT = 60

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

@app.route('/')
def index():
    return jsonify({"message": "Server is running!"})

@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()

    if not data or "player" not in data or "move" not in data:
        return jsonify({"error": "Invalid request"}), 400

    moves = load_moves()
    if "timestamp" not in moves:
        moves["timestamp"] = time.time()

    moves[data["player"]] = data["move"]
    moves[f"{data['player']}_ready"] = True
    save_moves(moves)

    print(f"[SUBMIT] {data['player']} submitted {data['move']}")
    return jsonify({"status": "Move received"})

@app.route('/result', methods=['GET'])
def result():
    moves = load_moves()

    # Timeout handler
    if "timestamp" in moves:
        elapsed = time.time() - moves["timestamp"]
        if elapsed > TIMEOUT:
            save_moves({})
            print("[TIMEOUT] Reset after timeout")
            return jsonify({"status": "Timeout"})

    # Kalau result sudah dihitung
    if "result_ready" in moves and moves["result_ready"]:
        return jsonify({
            "A": moves.get("A"),
            "B": moves.get("B"),
            "result": moves.get("result")
        })

    # Kalau dua player sudah submit
    if "A" in moves and "B" in moves:
        a = moves["A"]
        b = moves["B"]

        if a == b:
            winner = "Seri"
        elif (a == "Batu" and b == "Gunting") or (a == "Gunting" and b == "Kertas") or (a == "Kertas" and b == "Batu"):
            winner = "Player A Menang"
        else:
            winner = "Player B Menang"

        moves["result"] = winner
        moves["result_ready"] = True
        save_moves(moves)

        print(f"[RESULT] A: {a}, B: {b} -> {winner}")

        return jsonify({
            "A": a,
            "B": b,
            "result": winner
        })

    print("[WAITING] Waiting for players...")
    return jsonify({"status": "Waiting for opponent's move..."})

@app.route('/standby', methods=['POST'])
def standby():
    data = request.get_json()
    moves = load_moves()
    moves[f"{data['player']}_ready"] = True
    save_moves(moves)
    return jsonify({"status": f"Player {data['player']} is ready."})

@app.route('/get_moves', methods=['GET'])
def get_moves():
    moves = load_moves()
    return jsonify(moves)

@app.route('/reset', methods=['POST'])
def reset():
    save_moves({})
    print("[RESET] Game reset manually.")
    return jsonify({"status": "Game reset successfully."})

@app.route('/debug', methods=['GET'])
def debug_moves():
    moves = load_moves()
    return jsonify(moves)

if __name__ == '__main__':
    if not os.path.exists(MOVES_FILE):
        save_moves({})
    app.run(host='0.0.0.0', port=5000)
