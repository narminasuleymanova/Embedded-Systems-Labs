import sys
import time
import glob
import serial
import csv
from datetime import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QProgressBar, QTextEdit
)

BAUD = 9600


def auto_detect_port():
    ports = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*")
    return ports[0] if ports else None


def parse_arduino_line(line: str):
    line = line.strip()
    if not line:
        return None

    # Ignore boot / state messages
    if line.startswith("SYSTEM") or line.startswith("STATE"):
        return None

    try:
        parts = line.split(",")
        if len(parts) != 3:
            return None

        # level=123
        level_str = parts[0].split("=", 1)[1]
        # volt=2.34
        volt_str = parts[1].split("=", 1)[1]
        # status=LOUD
        status_str = parts[2].split("=", 1)[1].strip().upper()

        level = int(level_str)
        volt = float(volt_str)
        return level, volt, status_str
    except Exception:
        return None


class SoundLevelGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lab — Sound Level Monitor")

        self.ser = None
        self.port = None
        self.is_running = False
        self.last_time = None  # for Hz measurement

        # Store only LOUD events: list of (timestamp, level, status)
        self.loud_events = []

        # CSV logging (only LOUD events)
        self.csv_file = None
        self.csv_writer = None

        # ---------- Layouts ----------
        main = QVBoxLayout()

        # --- Top row: Start/Stop buttons ---
        row1 = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        row1.addWidget(self.start_btn)
        row1.addWidget(self.stop_btn)
        row1.addStretch(1)
        main.addLayout(row1)

        # --- Center: data visualization frame ---
        center = QHBoxLayout()

        data_frame = QFrame()
        data_frame.setFrameShape(QFrame.Shape.Box)
        data_layout = QVBoxLayout()

        title = QLabel("Current Sound Level")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        data_layout.addWidget(title)

        # Raw level bar (0–1023)
        self.bar_raw = QProgressBar()
        self.bar_raw.setRange(0, 1023)
        self.bar_raw.setFormat("Raw: %v / 1023")
        data_layout.addWidget(self.bar_raw)

        # Voltage bar (0–5 V, mapped to 0–500)
        self.bar_volt = QProgressBar()
        self.bar_volt.setRange(0, 500)  # 0.00–5.00 V * 100
        self.bar_volt.setFormat("Volt: %.2f V" % 0.0)
        data_layout.addWidget(self.bar_volt)

        # Status label
        self.status_label = QLabel("Status: -")
        self.status_label.setStyleSheet("font-weight: bold;")
        data_layout.addWidget(self.status_label)

        data_frame.setLayout(data_layout)
        center.addWidget(data_frame)

        # --- Right side: loud events history ---
        history_frame = QFrame()
        history_frame.setFrameShape(QFrame.Shape.Box)
        history_layout = QVBoxLayout()

        history_title = QLabel("Loud Events (Threshold Exceeded)")
        history_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        history_layout.addWidget(history_title)

        self.events_count_label = QLabel("Total loud events: 0")
        history_layout.addWidget(self.events_count_label)

        self.events_text = QTextEdit()
        self.events_text.setReadOnly(True)
        history_layout.addWidget(self.events_text)

        history_frame.setLayout(history_layout)
        center.addWidget(history_frame)

        main.addLayout(center)

        # --- Bottom info row ---
        bottom = QHBoxLayout()
        self.raw_label = QLabel("Raw: -")
        self.volt_label = QLabel("Volt: -")
        self.rate_label = QLabel("Hz: -")
        bottom.addWidget(self.raw_label)
        bottom.addWidget(self.volt_label)
        bottom.addWidget(self.rate_label)
        bottom.addStretch(1)
        main.addLayout(bottom)

        self.setLayout(main)

        # --- Signals ---
        self.start_btn.clicked.connect(self.start_monitor)
        self.stop_btn.clicked.connect(self.stop_monitor)

        # --- QTimer for polling serial ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(20)  # 50 Hz polling

    # ---------- Serial / Handshake ----------

    def open_serial_and_start(self) -> bool:
        self.port = auto_detect_port()
        if not self.port:
            print("Arduino not found")
            return False

        try:
            self.ser = serial.Serial(self.port, BAUD, timeout=0.2)
        except Exception as e:
            print("Port busy/unavailable:", e)
            self.ser = None
            return False

        # Opening the port usually resets Arduino
        time.sleep(2.0)

        # Wait up to ~3s for 'STATE=READY' (optional)
        ready = False
        t0 = time.time()
        while time.time() - t0 < 3.0:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    # print("BOOT:", line)  # uncomment for debugging boot messages
                    if "STATE=READY" in line or "READY" in line:
                        ready = True
                        break
            except Exception:
                break

        if not ready:
            # It's OK if we don't see the ready message; we can still proceed.
            pass

        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

        print("Connected on", self.port)
        return True

    def close_serial(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def start_monitor(self):
        if not (self.ser and self.ser.is_open):
            if not self.open_serial_and_start():
                return

        # ---------- OPEN CSV FILE (LOUD events only) ----------
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"sound_loud_events_{timestamp}.csv"
        try:
            self.csv_file = open(filename, "w", newline="")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["timestamp", "level", "voltage", "status"])
            print(f"CSV logging (LOUD only) to {filename}")
        except Exception as e:
            print("Could not create CSV file:", e)
            self.csv_file = None
            self.csv_writer = None
        # ------------------------------------------------------

        self.is_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.last_time = None

    def stop_monitor(self):
        self.is_running = False
        self.close_serial()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        # ---------- CLOSE CSV FILE ----------
        if self.csv_file:
            try:
                self.csv_file.close()
                print("CSV file saved.")
            except Exception:
                pass
            self.csv_file = None
            self.csv_writer = None
        # -------------------------------------

    def tick(self):
        if not self.is_running:
            return
        if not (self.ser and self.ser.is_open):
            return

        updated = False

        try:
            while self.ser.in_waiting:
                line = self.ser.readline().decode(errors="ignore")
                parsed = parse_arduino_line(line)
                if parsed:
                    level, volt, status = parsed
                    self.update_ui(level, volt, status)
                    updated = True
        except Exception:
            # unplugged or error
            self.close_serial()
            self.is_running = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        if updated:
            now = time.time()
            if self.last_time:
                hz = 1.0 / (now - self.last_time)
                self.rate_label.setText(f"Hz: {hz:.1f}")
            self.last_time = now

    # ---------- UI update ----------

    def update_ui(self, level: int, volt: float, status: str):
        # Current values (always shown)
        self.raw_label.setText(f"Raw: {level}")
        self.volt_label.setText(f"Volt: {volt:.2f} V")

        # Set progress bars
        self.bar_raw.setValue(max(0, min(1023, level)))
        self.bar_volt.setValue(max(0, min(500, int(volt * 100))))
        self.bar_volt.setFormat(f"Volt: {volt:.2f} V")

        # Status styling
        self.status_label.setText(f"Status: {status}")
        if status == "LOUD":
            self.status_label.setStyleSheet("font-weight: bold; color: red;")
        else:
            self.status_label.setStyleSheet("font-weight: bold; color: green;")

        # Store only loud events (time + sound level + status)
        if status == "LOUD":
            # ---------- WRITE LOUD EVENT TO CSV ----------
            if self.csv_writer:
                ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    self.csv_writer.writerow([ts_str, level, f"{volt:.2f}", status])
                except Exception as e:
                    print("CSV write error:", e)
            # --------------------------------------------

            ts = time.time()
            self.loud_events.append((ts, level, status))
            # Optionally limit history size
            if len(self.loud_events) > 200:
                self.loud_events.pop(0)

            self.update_loud_events_view()

    def update_loud_events_view(self):
        self.events_count_label.setText(f"Total loud events: {len(self.loud_events)}")

        # Show last 10 loud events
        lines = []
        for ts, level, status in self.loud_events[-10:]:
            t_str = time.strftime("%H:%M:%S", time.localtime(ts))
            # Example: "12:34:56 -> 654 -> LOUD"
            lines.append(f"{t_str} -> {level} -> {status}")

        self.events_text.setPlainText("\n".join(lines))

    def closeEvent(self, e):
        self.stop_monitor()
        super().closeEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = SoundLevelGUI()
    w.resize(800, 400)
    w.show()
    sys.exit(app.exec())