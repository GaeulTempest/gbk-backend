from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

MOVES_FILE = "moves.json"
TIMEOUT = 60  # Timeout 60 detik

# Fungsi load moves
def load_moves():
    if not os.path.exists(MOVES_FILE):
        print("moves.json not found, creating new file.")
        return {}
    try:
        with open(MOVES_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("JSON decode error in moves.json.")
        return {}

# Fungsi save moves
def save_moves(data):
    with open(MOVES_FILE, "w") as f:
        json.dump(data, f)

# Route utama
@app.route('/')
def index():
    return jsonify({"message": "Gunting Batu Kertas Backend is Running!"})

# Route submit gerakan
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

    # Jika baru mulai, buat timestamp
    if "timestamp" not in moves:
        moves["timestamp"] = time.time()
        print("[INFO] Game started at", moves["timestamp"])

    # Simpan gerakan pemain
    moves[data["player"]] = data["move"]
    moves[f"{data['player']}_ready"] = True  # Tandai pemain ready otomatis
    save_moves(moves)

    print(f"[MOVE] Player {data['player']} submitted move: {data['move']}")

    return jsonify({"status": "Move received successfully."})

# Route cek hasil
@app.route('/result', methods=['GET'])
def result():
    moves = load_moves()

    if "timestamp" in moves:
        elapsed = time.time() - moves["timestamp"]
        if elapsed > TIMEOUT:
            print("[TIMEOUT] Resetting game after 60 seconds.")
            save_moves({})
            return jsonify({"status": "Timeout! Game reset."})

    # Kalau sudah lengkap A dan B
    if "A" in moves and "B" in moves:
        a = moves["A"]
        b = moves["B"]

        # Tentukan pemenang
        if a == b:
            winner = "Seri"
        elif (a == "Batu" and b == "Gunting") or (a == "Gunting" and b == "Kertas") or (a == "Kertas" and b == "Batu"):
            winner = "Player A Menang"
        else:
            winner = "Player B Menang"

        print(f"[RESULT] Player A: {a}, Player B: {b}, Result: {winner}")

        save_moves({})  # Reset setelah selesai
        return jsonify({"A": a, "B": b, "result": winner})

    # Kalau belum lengkap
    print("[WAITING] Waiting for opponent move...")
    return jsonify({"status": "Waiting for opponent's move..."})

# Route standby ready
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

    print(f"[STANDBY] Player {data['player']} is ready.")

    return jsonify({"status": f"Player {data['player']} is ready."})

# Route get moves (cek siapa ready)
@app.route('/get_moves', methods=['GET'])
def get_moves():
    moves = load_moves()
    return jsonify(moves)

# Route manual reset
@app.route('/reset', methods=['POST'])
def reset():
    save_moves({})
    print("[RESET] Game reset manually.")
    return jsonify({"status": "Game reset successfully."})

# Route debug melihat semua data
@app.route('/debug', methods=['GET'])
def debug_moves():
    moves = load_moves()
    return jsonify(moves)

# Start server
if __name__ == '__main__':
    if not os.path.exists(MOVES_FILE):
        save_moves({})  # Buat moves.json kosong saat pertama kali
        print("[INFO] Created empty moves.json.")

    app.run(host='0.0.0.0', port=5000)
