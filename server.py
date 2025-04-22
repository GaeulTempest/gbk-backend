from flask import Flask, request, jsonify
import json

app = Flask(__name__)

MOVES_FILE = "moves.json"

def load_moves():
    try:
        with open(MOVES_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_moves(data):
    with open(MOVES_FILE, "w") as f:
        json.dump(data, f)

@app.route('/submit', methods=['POST'])
def submit():
    data = request.json
    moves = load_moves()
    moves[data["player"]] = data["move"]
    save_moves(moves)
    return jsonify({"status": "received"})

@app.route('/result', methods=['GET'])
def result():
    moves = load_moves()
    if "A" in moves and "B" in moves:
        a, b = moves["A"], moves["B"]
        if a == b:
            winner = "Seri"
        elif (a == "Batu" and b == "Gunting") or \
             (a == "Gunting" and b == "Kertas") or \
             (a == "Kertas" and b == "Batu"):
            winner = "Player A Menang"
        else:
            winner = "Player B Menang"
        return jsonify({"A": a, "B": b, "result": winner})
    return jsonify({"status": "Menunggu lawan"})

@app.route('/reset', methods=['POST'])
def reset():
    save_moves({})
    return jsonify({"status": "reset"})

if __name__ == '__main__':
    app.run(debug=True)
