from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

MOVES_FILE = "moves.json"
TIMEOUT = 30  # Timeout dalam detik - sesuai permintaanmu

# Fungsi untuk membaca moves
def load_moves():
    if not os.path.exists(MOVES_FILE):
        return {}
    try:
        with open(MOVES_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

# Fungsi untuk menyimpan moves
def save_moves(data):
    with open(MOVES_FILE, "w") as f:
        json.dump(data, f)

@app.route('/')
def index():
    return jsonify({"message": "Gunting Batu Kertas Backend is Running!"})

@app.route('/submit', methods=['POST'])
def submit():
    data = request.get_json()

    # Validasi input
    if not data or "player" not in data or "move" not in data:
        return jsonify({"error": "Invalid request format. Expected 'player' and 'move'."}), 400

    if data["player"] not in ["A", "B"]:
        return jsonify({"error": "Invalid player. Must be 'A' or 'B'."}), 400

    if data["move"] not in ["Batu", "Gunting", "Kertas"]:
        return jsonify({"error": "Invalid move. Must be 'Batu', 'Gunting', or 'Kertas'."}), 400

    moves = load_moves()

    # Jika belum ada timestamp, berarti ini input pertama
    if not moves.get("timestamp"):
        moves["timestamp"] = time.time()

    # Simpan move pemain
    moves[data["player"]] = data["move"]
    save_moves(moves)

    return jsonify({"status": "Move received successfully."})

@app.route('/result', methods=['GET'])
def result():
    moves = load_moves()

    # Cek timeout
    if "timestamp" in moves:
        elapsed = time.time() - moves["timestamp"]
        if elapsed > TIMEOUT:
            save_moves({})
            return jsonify({"status": "Timeout! Game reset automatically after 30 seconds."})

    # Cek apakah kedua pemain sudah submit
    if "A" in moves and "B" in moves:
        a, b = moves["A"], moves["B"]
        
        # Tentukan pemenang
        if a == b:
            winner = "Seri"
        elif (a == "Batu" and b == "Gunting") or (a == "Gunting" and b == "Kertas") or (a == "Kertas" and b == "Batu"):
            winner = "Player A Menang"
        else:
            winner = "Player B Menang"

        save_moves({})  # Reset setelah hasil keluar
        return jsonify({"A": a, "B": b, "result": winner})

    return jsonify({"status": "Waiting for opponent's move..."})

@app.route('/reset', methods=['POST'])
def reset():
    save_moves({})
    return jsonify({"status": "Game manually reset."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
