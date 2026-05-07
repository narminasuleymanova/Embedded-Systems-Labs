import sys
import glob
import csv
import os
import time
from datetime import datetime

import serial
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QProgressBar, QTextEdit
)

# ---- CONFIGURATION ----
BAUD_RATE = 9600
DB_FILE = "../../../../Documents/lab7 task/security_system/rfid_database.csv"


def auto_detect_port():
    """Auto-detect Arduino serial port on macOS/Linux/Windows."""
    # macOS
    ports = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*")
    # Linux
    ports += glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    if ports:
        return ports[0]
    # Windows - try common COM ports
    for i in range(1, 20):
        try:
            s = serial.Serial(f"COM{i}", BAUD_RATE, timeout=0.1)
            s.close()
            return f"COM{i}"
        except Exception:
            continue
    return None


def load_database():
    """Load tag database from CSV file."""
    db = {}
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row["uid"]
                db[uid] = {
                    "id": int(row["id"]),
                    "uid": uid,
                    "count": int(row["count"]),
                    "last_seen": row["last_seen"]
                }
    return db


def save_database(db):
    """Save tag database to CSV file."""
    with open(DB_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "uid", "count", "last_seen"])
        writer.writeheader()
        sorted_tags = sorted(db.values(), key=lambda x: x["id"])
        for entry in sorted_tags:
            writer.writerow(entry)


class SecurityGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Security System Monitor")
        self.setMinimumSize(600, 500)

        # Database: { "uid_string": { "id": int, "uid": str, "count": int, "last_seen": str } }
        self.db = load_database()
        self.next_id = max((entry["id"] for entry in self.db.values()), default=0) + 1

        # Serial connection
        self.serial_conn = None

        # Build the GUI
        self.init_ui()

        # Timer to poll serial port every 100ms
        self.timer = QTimer()
        self.timer.timeout.connect(self.read_serial)
        self.timer.start(100)

        # Try to connect on startup
        self.connect_serial()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # --- Top: status and connect button ---
        top_layout = QHBoxLayout()

        self.status_label = QLabel("Status: Disconnected")
        top_layout.addWidget(self.status_label)

        self.state_label = QLabel("System State: ---")
        top_layout.addWidget(self.state_label)

        top_layout.addStretch()

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_serial)
        top_layout.addWidget(self.connect_btn)

        main_layout.addLayout(top_layout)

        # --- Separator ---
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(line1)

        # --- Serial log ---
        log_label = QLabel("Serial Log:")
        main_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        main_layout.addWidget(self.log_text)

        # --- Separator ---
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(line2)

        # --- Tag database view ---
        db_label = QLabel("RFID Tag Database:")
        main_layout.addWidget(db_label)

        self.db_text = QTextEdit()
        self.db_text.setReadOnly(True)
        main_layout.addWidget(self.db_text)

        # --- Bottom buttons ---
        bottom_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("Refresh Database View")
        self.refresh_btn.clicked.connect(self.refresh_db_view)
        bottom_layout.addWidget(self.refresh_btn)

        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.log_text.clear)
        bottom_layout.addWidget(self.clear_log_btn)

        main_layout.addLayout(bottom_layout)

        self.setLayout(main_layout)

        # Show initial database
        self.refresh_db_view()

    def connect_serial(self):
        """Auto-detect port, open serial, and wait for Arduino reboot."""
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()

            # Auto-detect the port
            port = auto_detect_port()
            if not port:
                self.status_label.setText("Status: No Arduino found")
                self.log("No Arduino detected. Plug it in and click Connect.")
                return

            self.log(f"Found Arduino on {port}")
            self.status_label.setText(f"Status: Connecting ({port})...")

            # Open serial - this resets the Arduino
            self.serial_conn = serial.Serial(port, BAUD_RATE, timeout=0.1)

            # Wait for Arduino to reboot (it resets when serial opens)
            self.log("Waiting for Arduino to reboot...")
            time.sleep(2)

            # Flush any boot garbage from the buffer
            self.serial_conn.reset_input_buffer()

            self.status_label.setText(f"Status: Connected ({port})")
            self.log(f"Connected to {port} - ready!")

        except Exception as e:
            self.status_label.setText("Status: Disconnected")
            self.log(f"Connection failed: {e}")

    def read_serial(self):
        """Called by QTimer every 100ms. Reads available serial lines."""
        if not self.serial_conn or not self.serial_conn.is_open:
            return

        try:
            while self.serial_conn.in_waiting > 0:
                line = self.serial_conn.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.process_message(line)
        except Exception as e:
            self.log(f"Serial error: {e}")

    def process_message(self, msg):
        """Parse a message from Arduino and update state/database."""
        self.log(f"<< {msg}")

        if msg == "SYSTEM_READY":
            self.state_label.setText("System State: WAITING")

        elif msg.startswith("LOCKED:"):
            code = msg.split(":")[1]
            self.state_label.setText(f"System State: LOCKED (code set: {code})")

        elif msg == "UNLOCKED":
            self.state_label.setText("System State: UNLOCKED (RFID active)")

        elif msg == "WRONG_CODE":
            self.log("!! Wrong unlock code entered")

        elif msg.startswith("TAG:"):
            uid = msg.split(":", 1)[1]
            self.handle_tag(uid)

        elif msg.startswith("KEY:"):
            digit = msg.split(":")[1]
            self.log(f"Keypad digit: {digit}")

        elif msg.startswith("IR:"):
            digit = msg.split(":")[1]
            self.log(f"IR digit: {digit}")

    def handle_tag(self, uid):
        """Add or update a tag in the database."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if uid in self.db:
            # Tag seen before - increment count
            self.db[uid]["count"] += 1
            self.db[uid]["last_seen"] = now
            self.log(f"Tag {uid} scanned again (count: {self.db[uid]['count']})")
        else:
            # New tag - create entry with unique ID
            self.db[uid] = {
                "id": self.next_id,
                "uid": uid,
                "count": 1,
                "last_seen": now
            }
            self.log(f"New tag registered: {uid} (ID: {self.next_id})")
            self.next_id += 1

        save_database(self.db)
        self.refresh_db_view()

    def refresh_db_view(self):
        """Update the database display."""
        if not self.db:
            self.db_text.setText("No tags recorded yet.")
            return

        # Simple table format
        header = f"{'ID':<6}{'UID':<20}{'Scans':<8}{'Last Seen'}"
        lines = [header, "-" * 55]

        # Sort by ID
        sorted_tags = sorted(self.db.values(), key=lambda x: x["id"])
        for entry in sorted_tags:
            line = f"{entry['id']:<6}{entry['uid']:<20}{entry['count']:<8}{entry['last_seen']}"
            lines.append(line)

        self.db_text.setText("\n".join(lines))

    def log(self, text):
        """Append a line to the serial log."""
        self.log_text.append(text)

    def closeEvent(self, event):
        """Clean up serial on window close."""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SecurityGUI()
    window.show()
    sys.exit(app.exec())