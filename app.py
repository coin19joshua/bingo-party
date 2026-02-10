from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
# 使用 eventlet 以支援高併發與即時性
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 遊戲核心數據
game_state = {
    "status": "PLAYING", # PLAYING (進行中), ENDED (有人中獎)
    "drawn_numbers": [], # 已經開出的號碼
    "players": {}        # 所有玩家資料
}

def generate_card():
    # 產生 1-75 不重複的 25 個數字
    numbers = random.sample(range(1, 76), 25)
    card = [numbers[i:i+5] for i in range(0, 25, 5)]
    card[2][2] = 0 # 中間免費格
    return card

def check_player_status(card, drawn):
    # 檢查 5x5 矩陣的連線狀態
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

# --- WebSocket 事件處理 ---

@socketio.on('join_game')
def handle_join(data):
    if game_state['status'] == 'ENDED':
        emit('error', {'msg': '遊戲已結束'})
        return

    nickname = data.get('nickname', 'Guest')
    card = generate_card()
    
    # 記錄玩家
    game_state['players'][request.sid] = {
        "name": nickname,
        "card": card,
        "status": "NORMAL"
    }
    
    # 回傳卡片給玩家
    emit('init_game', {"card": card, "drawn": game_state['drawn_numbers']})
    
    # **關鍵**：有人加入，立刻通知後台更新人數
    update_admin_full()

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in game_state['players']:
        del game_state['players'][request.sid]
        # **關鍵**：有人離開，立刻通知後台更新人數
        update_admin_full()

@socketio.on('request_draw')
def handle_draw_request():
    """
    這是新的邏輯：
    1. 後台發送 'request_draw'
    2. 伺服器計算號碼
    3. 伺服器廣播 'number_drawn'
    """
    if game_state['status'] == 'ENDED':
        return

    # 計算剩餘號碼
    all_nums = set(range(1, 76))
    drawn_set = set(game_state['drawn_numbers'])
    available = list(all_nums - drawn_set)

    if not available:
        return # 沒號碼了

    # 伺服器決定號碼 (保證唯一真理)
    new_number = random.choice(available)
    game_state['drawn_numbers'].append(new_number)
    
    winners = []
    
    # 更新所有玩家狀態
    for sid, player in game_state['players'].items():
        status = check_player_status(player['card'], game_state['drawn_numbers'])
        player['status'] = status
        
        if status == "BINGO":
            winners.append(player['name'])
        
        # 通知玩家手機
        emit('update_status', {"status": status, "new_number": new_number}, room=sid)

    # 廣播號碼給所有人 (包含後台)
    emit('number_drawn', {"number": new_number}, broadcast=True)
    
    # 檢查是否有人贏了
    if len(winners) > 0:
        game_state['status'] = 'ENDED'
        socketio.emit('game_over', {"winners": winners}, broadcast=True)
    
    # 無論如何，更新後台資訊 (包含歷史紀錄)
    update_admin_full()

@socketio.on('reset_game')
def handle_reset():
    game_state['status'] = 'PLAYING'
    game_state['drawn_numbers'] = []
    
    # 重置所有玩家
    for sid in game_state['players']:
        game_state['players'][sid]['card'] = generate_card()
        game_state['players'][sid]['status'] = "NORMAL"
        emit('init_game', {"card": game_state['players'][sid]['card'], "drawn": []}, room=sid)
    
    emit('game_reset', broadcast=True)
    update_admin_full()

def update_admin_full():
    leaderboard = []
    # 只回傳有在玩的人 (狀態是 REACH 或 BINGO 的優先)
    for p in game_state['players'].values():
        leaderboard.append({"name": p['name'], "status": p['status']})
    
    # 排序：Bingo > Reach > Normal
    status_order = {"BINGO": 0, "REACH": 1, "NORMAL": 2}
    leaderboard.sort(key=lambda x: status_order[x['status']])
    
    # 發送完整數據給後台
    socketio.emit('admin_update', {
        "players": leaderboard,
        "drawn": game_state['drawn_numbers'], # 歷史號碼
        "count": len(game_state['players']),
        "status": game_state['status']
    }, broadcast=True)

if __name__ == '__main__':
    socketio.run(app)
