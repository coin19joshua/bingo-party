from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
# 允許跨域，確保手機連線順暢
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 遊戲狀態
game_state = {
    "drawn_numbers": [],
    "players": {}
}

def generate_card():
    numbers = random.sample(range(1, 76), 25)
    card = [numbers[i:i+5] for i in range(0, 25, 5)]
    card[2][2] = 0 
    return card

def check_player_status(card, drawn):
    lines = []
    for i in range(5):
        lines.append(card[i]) 
        lines.append([card[x][i] for x in range(5)]) 
    lines.append([card[i][i] for i in range(5)])
    lines.append([card[i][4-i] for i in range(5)])

    is_bingo = False
    is_reach = False

    for line in lines:
        matches = 0
        for num in line:
            if num == 0 or num in drawn:
                matches += 1
        if matches == 5: is_bingo = True
        elif matches == 4: is_reach = True
            
    if is_bingo: return "BINGO"
    if is_reach: return "REACH"
    return "NORMAL"

@app.route('/')
def index():
    return "請掃描 QR Code 進入遊戲"

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/play')
def play():
    return render_template('player.html')

@socketio.on('join_game')
def handle_join(data):
    nickname = data.get('nickname', 'Guest')
    card = generate_card()
    game_state['players'][request.sid] = {
        "name": nickname, "card": card, "status": "NORMAL"
    }
    emit('init_game', {"card": card, "drawn": game_state['drawn_numbers']})
    update_admin()

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in game_state['players']:
        del game_state['players'][request.sid]
        update_admin()

@socketio.on('draw_number')
def handle_draw(data):
    number = int(data.get('number'))
    if number not in game_state['drawn_numbers']:
        game_state['drawn_numbers'].append(number)
        for sid, player in game_state['players'].items():
            status = check_player_status(player['card'], game_state['drawn_numbers'])
            player['status'] = status
            emit('update_status', {"status": status, "new_number": number}, room=sid)
        emit('number_drawn', {"number": number}, broadcast=True)
        update_admin()

@socketio.on('reset_game')
def handle_reset():
    game_state['drawn_numbers'] = []
    for sid in game_state['players']:
        game_state['players'][sid]['card'] = generate_card()
        game_state['players'][sid]['status'] = "NORMAL"
        emit('init_game', {"card": game_state['players'][sid]['card'], "drawn": []}, room=sid)
    emit('game_reset', broadcast=True)
    update_admin()

def update_admin():
    leaderboard = []
    for p in game_state['players'].values():
        leaderboard.append({"name": p['name'], "status": p['status']})
    status_order = {"BINGO": 0, "REACH": 1, "NORMAL": 2}
    leaderboard.sort(key=lambda x: status_order[x['status']])
    socketio.emit('admin_update', {
        "players": leaderboard,
        "drawn": game_state['drawn_numbers'],
        "count": len(game_state['players'])
    }, broadcast=True)

if __name__ == '__main__':
    socketio.run(app)
