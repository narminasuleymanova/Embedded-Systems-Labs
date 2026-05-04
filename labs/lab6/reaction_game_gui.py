import sys
import serial
import glob
import threading
import time
import json
import os
import datetime
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QTextEdit, QLineEdit,
    QMessageBox, QDialog, QComboBox, QDialogButtonBox
)
from PyQt6.QtGui import QFont

# ── Settings ─────────────────────────────────────────────────
BAUD_RATE         = 9600
ARDUINO_BOOT_WAIT = 2.0
HANDSHAKE_TIMEOUT = 3.0
DATA_DIR          = "player_data"

# ── Tug-of-war settings ─────────────────────────────────────
TOW_POSITIONS = 7        # 7 slots: indices 0,1,2,3,4,5,6
TOW_START     = 3        # both start in the middle
TOW_P1_GOAL   = 0        # P1 wins by reaching position 0 (left)
TOW_P2_GOAL   = 6        # P2 wins by reaching position 6 (right)

os.makedirs(DATA_DIR, exist_ok=True)


# ── File helpers ─────────────────────────────────────────────
def player_file(name):
    safe = name.strip().lower().replace(" ", "_")
    return os.path.join(DATA_DIR, f"{safe}.json")


def load_player(name):
    path = player_file(name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"name": name, "sessions": []}


def save_player(data):
    with open(player_file(data["name"]), "w") as f:
        json.dump(data, f, indent=2)


# ── Main Application ────────────────────────────────────────
class ReactionGameApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reaction Game — Tug-of-War")
        self.resize(750, 620)

        # Serial connection
        self.ser = None
        self.connected = False

        # Game state — tug-of-war position based
        self.tow_pos = TOW_START     # current position on the 0–6 track
        self.p1_rt = None
        self.p2_rt = None
        self.round_num = 0
        self.session_log = []
        self.game_active = False
        self.round_active = False
        self.false_start_player = None

        self.build_gui()

        # QTimer for polling serial
        self.serial_buffer = []
        self.serial_timer = QTimer()
        self.serial_timer.timeout.connect(self.process_serial_messages)
        self.serial_timer.start(20)

    # ── Build the GUI ────────────────────────────────────────
    def build_gui(self):
        main_layout = QVBoxLayout()

        # --- Connection row ---
        conn_layout = QHBoxLayout()
        self.conn_label = QLabel("Not connected")
        conn_layout.addWidget(self.conn_label)
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.connect)
        conn_layout.addWidget(connect_btn)
        conn_layout.addStretch(1)
        main_layout.addLayout(conn_layout)

        # --- Player names row ---
        names_layout = QHBoxLayout()
        names_layout.addWidget(QLabel("Player 1:"))
        self.p1_entry = QLineEdit()
        self.p1_entry.setFixedWidth(120)
        names_layout.addWidget(self.p1_entry)
        names_layout.addWidget(QLabel("Player 2:"))
        self.p2_entry = QLineEdit()
        self.p2_entry.setFixedWidth(120)
        names_layout.addWidget(self.p2_entry)
        names_layout.addStretch(1)
        main_layout.addLayout(names_layout)

        # --- Start button ---
        self.start_btn = QPushButton("START GAME")
        self.start_btn.clicked.connect(self.start_game)
        self.start_btn.setEnabled(False)
        main_layout.addWidget(self.start_btn)

        # --- Status label ---
        self.status_label = QLabel("Waiting for Arduino...")
        self.status_label.setFont(QFont("Arial", 13))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

        # --- Round log ---
        main_layout.addWidget(QLabel("Round Log:"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(160)
        main_layout.addWidget(self.log_box)

        # --- Visualisation buttons ---
        viz_layout = QHBoxLayout()
        rt_btn = QPushButton("Reaction Times")
        rt_btn.clicked.connect(self.plot_reaction_times)
        viz_layout.addWidget(rt_btn)
        wr_btn = QPushButton("Win Rates")
        wr_btn.clicked.connect(self.plot_win_rates)
        viz_layout.addWidget(wr_btn)
        h2h_btn = QPushButton("Head-to-Head")
        h2h_btn.clicked.connect(self.plot_head_to_head)
        viz_layout.addWidget(h2h_btn)
        viz_layout.addStretch(1)
        main_layout.addLayout(viz_layout)

        self.setLayout(main_layout)

    # ── Connection ───────────────────────────────────────────
    def auto_detect_port(self):
        ports = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*")
        return ports[0] if ports else None

    def connect(self):
        if self.connected:
            return
        port = self.auto_detect_port()
        if not port:
            self.conn_label.setText("No Arduino found. Plug in and retry.")
            return
        t = threading.Thread(target=self.do_handshake, args=(port,), daemon=True)
        t.start()

    def do_handshake(self, port):
        try:
            s = serial.Serial(port, BAUD_RATE, timeout=1)
        except Exception:
            self.serial_buffer.append(("__CONN__", "Could not open port. Retry."))
            return

        time.sleep(ARDUINO_BOOT_WAIT)
        s.reset_input_buffer()
        s.write(b"HELLO\n")

        deadline = time.time() + HANDSHAKE_TIMEOUT
        found = False
        while time.time() < deadline:
            if s.in_waiting:
                line = s.readline().decode("utf-8", errors="ignore").strip()
                if line == "ARDUINO_READY":
                    found = True
                    break
            time.sleep(0.05)

        if found:
            self.ser = s
            self.connected = True
            self.serial_buffer.append(("__CONNECTED__", port))
            reader = threading.Thread(target=self.serial_reader, daemon=True)
            reader.start()
        else:
            s.close()
            self.serial_buffer.append(("__CONN__", "No response from Arduino. Retry."))

    def process_serial_messages(self):
        while self.serial_buffer:
            tag, val = self.serial_buffer.pop(0)
            if tag == "__CONN__":
                self.conn_label.setText(val)
            elif tag == "__CONNECTED__":
                self.on_connected(val)
            elif tag == "__LOST__":
                self.conn_label.setText("Connection lost. Replug and retry.")
            elif tag == "__MSG__":
                self.handle_message(val)

    def on_connected(self, port):
        self.conn_label.setText(f"Connected: {port}")
        self.start_btn.setEnabled(True)
        self.status_label.setText("Ready — enter names and start!")
        self.log_msg(f"Arduino found on {port}")

    # ── Serial reader (background thread) ────────────────────
    def serial_reader(self):
        while self.connected:
            try:
                if self.ser and self.ser.in_waiting:
                    line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self.serial_buffer.append(("__MSG__", line))
            except Exception:
                self.connected = False
                self.serial_buffer.append(("__LOST__", ""))
                break
            time.sleep(0.01)

    def handle_message(self, msg):
        if msg.startswith("COUNTDOWN:"):
            # Hide the countdown number — just show a waiting message
            self.status_label.setText("Wait for it... DON'T PRESS!")

        elif msg == "BUZZ":
            self.status_label.setText("BUZZ! PRESS NOW!")

        elif msg.startswith("P1:"):
            self.p1_rt = int(msg.split(":")[1])

        elif msg.startswith("P2:"):
            self.p2_rt = int(msg.split(":")[1])

        elif msg.startswith("FALSE_START:"):
            self.false_start_player = int(msg.split(":")[1])

        elif msg.startswith("POS:"):
            # Arduino reports the new tug-of-war position
            self.tow_pos = int(msg.split(":")[1])

        elif msg.startswith("WINNER:"):
            winner = int(msg.split(":")[1])
            is_false = self.false_start_player is not None
            fp = self.false_start_player
            self.false_start_player = None
            self.resolve_round(is_false, winner, fp)

        elif msg.startswith("MATCH:"):
            # Arduino confirms a player reached the goal — handled in resolve_round
            pass

        elif msg == "SPIN_DONE":
            self.log_msg("Victory spin complete.")

        elif msg == "TIMEOUT":
            if self.round_active:
                self.round_active = False
                self.status_label.setText("Both timed out — no point.")
                self.log_msg(f"Round {self.round_num}: Timeout — no presses")
                QTimer.singleShot(1500, self.next_round)

    # ── Game logic ───────────────────────────────────────────
    def start_game(self):
        p1 = self.p1_entry.text().strip()
        p2 = self.p2_entry.text().strip()
        if not p1 or not p2:
            QMessageBox.warning(self, "Names needed", "Enter both player names.")
            return
        if not self.connected:
            QMessageBox.warning(self, "Not connected", "Arduino not connected.")
            return

        # Reset tug-of-war to centre
        self.tow_pos = TOW_START
        self.round_num = 0
        self.session_log = []
        self.game_active = True
        self.log_msg(f"--- {p1} vs {p2} — {datetime.datetime.now():%Y-%m-%d %H:%M} ---")
        self.log_msg(f"Tug-of-War: {p1} ← [0][1][2][●3][4][5][6] → {p2}")
        self.log_msg(f"{p1} must pull marker to position 0, {p2} to position 6.")
        self.next_round()

    def next_round(self):
        if not self.game_active:
            return
        self.round_num += 1
        self.p1_rt = None
        self.p2_rt = None
        self.round_active = True
        self.false_start_player = None
        self.status_label.setText(f"Round {self.round_num} — get ready...")
        self.send("START\n")

    def resolve_round(self, false_start, winner_idx, false_player=None):
        if not self.round_active:
            return
        self.round_active = False

        p1 = self.p1_entry.text().strip()
        p2 = self.p2_entry.text().strip()

        # If not a false start, fill in missing reaction times
        if not false_start:
            if self.p1_rt is None:
                self.p1_rt = 99999
            if self.p2_rt is None:
                self.p2_rt = 99999
            winner_idx = 1 if self.p1_rt <= self.p2_rt else 2

        winner_name = p1 if winner_idx == 1 else p2

        # Save round data
        round_data = {
            "round":       self.round_num,
            "p1_rt":       self.p1_rt,
            "p2_rt":       self.p2_rt,
            "winner":      winner_name,
            "false_start": false_start,
            "tow_pos":     self.tow_pos,
        }
        self.session_log.append(round_data)

        # Log message
        pos_bar = self.format_position_bar()
        if false_start:
            self.log_msg(f"Round {self.round_num}: P{false_player} false start! "
                         f"Point to {winner_name}  {pos_bar}")
        else:
            self.log_msg(f"Round {self.round_num}: {winner_name} wins "
                         f"[P1: {self.p1_rt}ms | P2: {self.p2_rt}ms]  {pos_bar}")

        # Check if the tug-of-war reached either end
        if self.tow_pos <= TOW_P1_GOAL:
            self.end_match(p1)
        elif self.tow_pos >= TOW_P2_GOAL:
            self.end_match(p2)
        else:
            QTimer.singleShot(1500, self.next_round)

    def format_position_bar(self):
        """Return a text representation like [_][_][●][_][_][_][_] for the log."""
        parts = []
        for i in range(TOW_POSITIONS):
            if i == self.tow_pos:
                parts.append("[●]")
            else:
                parts.append("[ ]")
        return "".join(parts)

    def end_match(self, winner_name):
        self.game_active = False
        self.status_label.setText(f"{winner_name.upper()} WINS THE MATCH!")
        self.log_msg(f"=== MATCH OVER — {winner_name} pulled the marker to their goal! ===")

        winner_idx = 1 if winner_name == self.p1_entry.text().strip() else 2
        self.send(f"SPIN:{winner_idx}\n")

        self.save_results()
        QMessageBox.information(self, "Match Over!",
                                f"{winner_name} wins the tug-of-war!\nResults saved.")

    def save_results(self):
        p1 = self.p1_entry.text().strip()
        p2 = self.p2_entry.text().strip()
        date_str = datetime.datetime.now().isoformat()

        # Count round wins from the session log
        p1_round_wins = sum(1 for r in self.session_log if r["winner"] == p1)
        p2_round_wins = sum(1 for r in self.session_log if r["winner"] == p2)

        for idx, name in [(1, p1), (2, p2)]:
            opponent = p2 if idx == 1 else p1
            player_data = load_player(name)

            rts = [r[f"p{idx}_rt"] for r in self.session_log
                   if r.get(f"p{idx}_rt") and r[f"p{idx}_rt"] < 9000]

            my_wins = p1_round_wins if idx == 1 else p2_round_wins
            opp_wins = p2_round_wins if idx == 1 else p1_round_wins

            session = {
                "date":        date_str,
                "opponent":    opponent,
                "my_wins":     my_wins,
                "opp_wins":    opp_wins,
                "match_winner": self.session_log[-1]["winner"] if self.session_log else None,
                "total_rounds": len(self.session_log),
                "rounds":      self.session_log,
                "avg_rt_ms":   round(sum(rts) / len(rts), 1) if rts else None,
            }
            player_data["sessions"].append(session)
            save_player(player_data)

    # ── Helper methods ───────────────────────────────────────
    def send(self, msg):
        if self.ser and self.ser.is_open:
            self.ser.write(msg.encode())

    def log_msg(self, text):
        self.log_box.append(text)

    # ── Player picker dialog ─────────────────────────────────
    def pick_player(self, title="Select Player"):
        files = [f[:-5] for f in os.listdir(DATA_DIR) if f.endswith(".json")]
        if not files:
            QMessageBox.information(self, "No data", "No player files found yet.")
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(250, 120)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Player:"))
        combo = QComboBox()
        combo.addItems(files)
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return combo.currentText()
        return None

    # ── Data Visualisation ───────────────────────────────────
    def plot_reaction_times(self):
        name = self.pick_player("Reaction Times")
        if not name:
            return

        data = load_player(name)
        sessions = data.get("sessions", [])
        if not sessions:
            QMessageBox.information(self, "No data", f"No sessions for {name}.")
            return

        rts = []
        labels = []
        for i, s in enumerate(sessions):
            for r in s["rounds"]:
                rt = r.get("p1_rt") or r.get("p2_rt")
                if rt and rt < 9000:
                    rts.append(rt)
                    labels.append(f"S{i+1}R{r['round']}")

        if not rts:
            QMessageBox.information(self, "No data", "No reaction times recorded.")
            return

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(labels, rts, "o-", color="blue", linewidth=2)
        avg = sum(rts) / len(rts)
        ax.axhline(avg, color="red", linestyle="--", label=f"Avg: {avg:.0f} ms")
        ax.set_title(f"{name.title()} — Reaction Times")
        ax.set_xlabel("Session / Round")
        ax.set_ylabel("Reaction Time (ms)")
        ax.legend()
        plt.xticks(rotation=45, ha="right", fontsize=8)
        plt.tight_layout()
        plt.show()

    def plot_win_rates(self):
        files = [f[:-5] for f in os.listdir(DATA_DIR) if f.endswith(".json")]
        if not files:
            QMessageBox.information(self, "No data", "No player data found.")
            return

        names = []
        rates = []
        for fname in files:
            d = load_player(fname)
            sessions = d.get("sessions", [])
            if not sessions:
                continue
            wins = sum(1 for s in sessions if s["my_wins"] > s["opp_wins"])
            total = len(sessions)
            names.append(fname.replace("_", " ").title())
            rates.append(100 * wins / total if total else 0)

        if not names:
            QMessageBox.information(self, "No data", "No session data to plot.")
            return

        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(names, rates, color="steelblue")
        ax.set_ylim(0, 110)
        ax.set_title("Win Rate by Player (%)")
        ax.set_ylabel("Win Rate (%)")
        plt.tight_layout()
        plt.show()

    def plot_head_to_head(self):
        files = [f[:-5] for f in os.listdir(DATA_DIR) if f.endswith(".json")]
        if len(files) < 2:
            QMessageBox.information(self, "Need 2 players",
                                    "Need at least 2 saved player files.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Head-to-Head")
        dialog.resize(250, 180)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Player A:"))
        combo_a = QComboBox()
        combo_a.addItems(files)
        layout.addWidget(combo_a)
        layout.addWidget(QLabel("Player B:"))
        combo_b = QComboBox()
        combo_b.addItems(files)
        if len(files) > 1:
            combo_b.setCurrentIndex(1)
        layout.addWidget(combo_b)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setLayout(layout)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        result_a = combo_a.currentText()
        result_b = combo_b.currentText()
        if not result_a or result_a == result_b:
            return

        def get_avg_rts(player_name):
            d = load_player(player_name)
            avgs = []
            for s in d["sessions"]:
                rts = []
                for r in s["rounds"]:
                    for key in ("p1_rt", "p2_rt"):
                        v = r.get(key)
                        if v and v < 9000:
                            rts.append(v)
                if rts:
                    avgs.append(sum(rts) / len(rts))
            return avgs

        rt1 = get_avg_rts(result_a)
        rt2 = get_avg_rts(result_b)

        fig, ax = plt.subplots(figsize=(8, 4))
        if rt1:
            ax.plot(range(1, len(rt1) + 1), rt1, "o-", color="blue",
                    label=result_a.replace("_", " ").title(), linewidth=2)
        if rt2:
            ax.plot(range(1, len(rt2) + 1), rt2, "s-", color="red",
                    label=result_b.replace("_", " ").title(), linewidth=2)
        ax.set_title("Head-to-Head: Avg Reaction Time per Session")
        ax.set_xlabel("Session #")
        ax.set_ylabel("Avg RT (ms)")
        ax.legend()
        plt.tight_layout()
        plt.show()

    def closeEvent(self, event):
        self.connected = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        super().closeEvent(event)


# ── Run the app ──────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ReactionGameApp()
    window.show()
    sys.exit(app.exec())