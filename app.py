from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 遊戲核心數據
game_state = {
    "status": "PLAYING", 
    "drawn_numbers": [], 
    "players": {} 
}

def generate_card():
    # 產生 1-75 不重複的 25 個數字
    numbers = random.sample(range(1, 76), 25)
    card = [numbers[i:i+5] for i in range(0, 25, 5)]
    card[2][2] = 0 # 中間免費格
    return card

def check_player_status(card, drawn):
    lines = []
    # 橫列 & 直列
    for i in range(5):
        lines.append(card[i]) 
        lines.append([card[x][i] for x in range(5)]) 
    # 對角線
    lines.append([card[i][i] for i in range(5)])
    lines.append([card[i][4-i] for i in range(5)])

    is_bingo = False
    is_reach = False

    for line in lines:
        matches = 0
        for num in line:
            if num == 0 or num in drawn:
                matches += 1
        
        if matches == 5:
            is_bingo = True
        elif matches == 4:
            is_reach = True
            
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

# --- WebSocket 事件 ---

@socketio.on('join_game')
def handle_join(data):
    if game_state['status'] == 'ENDED':
        emit('error', {'msg': '遊戲已結束，等待下一局'})
        return

    nickname = data.get('nickname', 'Guest')
    card = generate_card()
    
    # 儲存玩家
    game_state['players'][request.sid] = {
        "name": nickname,
        "card": card,
        "status": "NORMAL"
    }
    
    emit('init_game', {"card": card, "drawn": game_state['drawn_numbers']})
    # ★ 修復：有人加入，強制廣播最新人數給後台
    update_admin_full()

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in game_state['players']:
        del game_state['players'][request.sid]
        # ★ 修復：有人斷線，強制廣播最新人數給後台
        update_admin_full()

@socketio.on('request_draw')
def handle_draw_request():
    if game_state['status'] == 'ENDED':
        return

    all_nums = set(range(1, 76))
    drawn_set = set(game_state['drawn_numbers'])
    available = list(all_nums - drawn_set)

    if not available: return

    new_number = random.choice(available)
    game_state['drawn_numbers'].append(new_number)
    
    winners = []
    
    # 更新所有玩家狀態
    for sid, player in game_state['players'].items():
        status = check_player_status(player['card'], game_state['drawn_numbers'])
        player['status'] = status
        
        if status == "BINGO":
            winners.append(player['name'])
        
        emit('update_status', {"status": status, "new_number": new_number}, room=sid)

    emit('number_drawn', {"number": new_number}, broadcast=True)
    
    if len(winners) > 0:
        game_state['status'] = 'ENDED'
        socketio.emit('game_over', {"winners": winners}, broadcast=True)
    
    update_admin_full()

@socketio.on('reset_game')
def handle_reset():
    # ★ 核彈級重置邏輯 ★
    game_state['status'] = 'PLAYING'
    game_state['drawn_numbers'] = []
    
    # 1. 先通知所有人「遊戲重置了，快重整！」
    socketio.emit('game_reset', broadcast=True)
    
    # 2. 清空伺服器端的所有玩家資料
    game_state['players'].clear()
    
    # 3. 更新後台（這時候人數會變 0）
    update_admin_full()

def update_admin_full():
    leaderboard = []
    # 撈取資料
    for p in game_state['players'].values():
        leaderboard.append({"name": p['name'], "status": p['status']})
    
    # 排序：Bingo > Reach > Normal
    status_order = {"BINGO": 0, "REACH": 1, "NORMAL": 2}
    leaderboard.sort(key=lambda x: status_order[x['status']])
    
    # ★ Debug用：在伺服器端印出聽牌人數，確保後端有抓到
    reach_count = sum(1 for p in leaderboard if p['status'] == 'REACH')
    print(f"Update Admin: Total {len(leaderboard)}, Reach {reach_count}")

    socketio.emit('admin_update', {
        "players": leaderboard,
        "drawn": game_state['drawn_numbers'],
        "count": len(game_state['players']),
        "status": game_state['status']
    }, broadcast=True)

if __name__ == '__main__':
    socketio.run(app)
