from flask import Flask, request, jsonify
import json
import time
import os

app = Flask(__name__)

MOVES_FILE = "moves.json"
TIMEOUT = 60  # 60 detik timeout otomatis

# Fungsi load moves dari file
def load_moves():
    if not os.path.exists(MOVES_FILE):
        return {}
    try:
        with open(MOVES_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

# Fungsi save moves ke file
def save_moves(data):
    with open(MOVES_FILE, "w") as f:
        json.dump(data, f)

# Route utama (cek server hidup)
@app.route('/')
def index():
    return jsonify({"message": "Gunting Batu Kertas Backend is Running!"})

# Route submit gesture
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

    # Tambahkan timestamp kalau pertama kali main
    if "timestamp" not in moves:
        moves["timestamp"] = time.time()

    # Simpan gerakan pemain
    moves[data["player"]] = data["move"]
    save_moves(moves)

    return jsonify({"status": "Move received successfully."})

# Route untuk lihat hasil
@app.route('/result', methods=['GET'])
def result():
    moves = load_moves()

    # Cek timeout
    if "timestamp" in moves:
        elapsed = time.time() - moves["timestamp"]
        if elapsed > TIMEOUT:
            save_moves({})
            return jsonify({"status": "Timeout! Game reset automatically after 60 seconds."})

    # Kalau sudah ada dua pemain submit
    if "A" in moves and "B" in moves:
        a = moves["A"]
        b = moves["B"]

        # Menentukan pemenang
        if a == b:
            winner = "Seri"
        elif (a == "Batu" and b == "Gunting") or (a == "Gunting" and b == "Kertas") or (a == "Kertas" and b == "Batu"):
            winner = "Player A Menang"
        else:
            winner = "Player B Menang"

        save_moves({})  # Reset file moves setelah hasil keluar
        return jsonify({"A": a, "B": b, "result": winner})

    # Kalau belum lengkap, kasih status tunggu
    return jsonify({"status": "Waiting for opponent's move..."})

# Route untuk standby (daftar ready)
@app.route('/standby', methods=['POST'])
def standby():
    data = request.get_json()

    if not data or "player" not in data:
        return jsonify({"error": "Invalid request format. Expected 'player'."}), 400

    if data["player"] not in ["A", "B"]:
        return jsonify({"error": "Invalid player. Must be 'A' or 'B'."}), 400

    moves = load_moves()

    # Tambahkan info siap main
    moves[f"{data['player']}_ready"] = True
    save_moves(moves)

    return jsonify({"status": f"Player {data['player']} is ready."})

# Route untuk lihat siapa yang standby
@app.route('/get_moves', methods=['GET'])
def get_moves():
    moves = load_moves()
    return jsonify(moves)

# Route manual reset game
@app.route('/reset', methods=['POST'])
def reset():
    save_moves({})
    return jsonify({"status": "Game reset successfully."})

# Jalankan server
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
