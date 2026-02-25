import sys
import time
import glob
import serial

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QProgressBar
)

BAUD = 9600

def auto_detect_port():
    ports = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*")
    return ports[0] if ports else None

def parse_arduino_line(line: str):
    line = line.strip()
    if not line:
        return None
    if line.startswith("SYSTEM") or line.startswith("STATE"):
        return None

    try:
        parts = line.split(",")
        if len(parts) != 3:
            return None

        x_v = float(parts[0].split("=", 1)[1])
        y_v = float(parts[1].split("=", 1)[1])
        direction = parts[2].split("=", 1)[1].strip().upper()
        return x_v, y_v, direction
    except Exception:
        return None

class Lab4JoystickGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lab 4 — Joystick Monitor")

        self.ser = None
        self.port = None
        self.is_running = False
        self.last_time = None

        main = QVBoxLayout()

        # buttons
        row1 = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        row1.addWidget(self.start_btn)
        row1.addWidget(self.stop_btn)
        row1.addStretch(1)
        main.addLayout(row1)

        # bars
        center = QHBoxLayout()

        data_frame = QFrame()
        data_frame.setFrameShape(QFrame.Shape.Box)
        data_layout = QVBoxLayout()

        title = QLabel("Joystick Position")
        title.setStyleSheet("font-weight: bold;")
        data_layout.addWidget(title)

        self.bar_x = QProgressBar()
        self.bar_x.setRange(0, 500)
        self.bar_x.setFormat("X: %v / 500")
        data_layout.addWidget(self.bar_x)

        self.bar_y = QProgressBar()
        self.bar_y.setRange(0, 500)
        self.bar_y.setFormat("Y: %v / 500")
        data_layout.addWidget(self.bar_y)

        data_frame.setLayout(data_layout)
        center.addWidget(data_frame)

        # direction cross
        cross = QVBoxLayout()
        self.up = self.block()
        cross.addWidget(self.up)

        mid = QHBoxLayout()
        self.left = self.block()
        self.center_block = self.block()
        self.right = self.block()
        mid.addWidget(self.left)
        mid.addWidget(self.center_block)
        mid.addWidget(self.right)
        cross.addLayout(mid)

        self.down = self.block()
        cross.addWidget(self.down)

        center.addLayout(cross)
        main.addLayout(center)

        # labels
        bottom = QHBoxLayout()
        self.x_label = QLabel("X: -")
        self.y_label = QLabel("Y: -")
        self.rate_label = QLabel("Hz: -")
        self.dir_label = QLabel("Dir: -")
        bottom.addWidget(self.x_label)
        bottom.addWidget(self.y_label)
        bottom.addWidget(self.rate_label)
        bottom.addWidget(self.dir_label)
        main.addLayout(bottom)

        self.setLayout(main)

        self.start_btn.clicked.connect(self.start_test)
        self.stop_btn.clicked.connect(self.stop_test)

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(20)

    # ---------- UI helpers ----------
    def block(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.Box)
        f.setMinimumSize(40, 40)
        return f

    def highlight(self, direction):
        off = ""
        on = "background-color: lightgreen;"

        self.up.setStyleSheet(off)
        self.down.setStyleSheet(off)
        self.left.setStyleSheet(off)
        self.right.setStyleSheet(off)
        self.center_block.setStyleSheet(off)

        if direction == "UP":
            self.up.setStyleSheet(on)
        elif direction == "DOWN":
            self.down.setStyleSheet(on)
        elif direction == "LEFT":
            self.left.setStyleSheet(on)
        elif direction == "RIGHT":
            self.right.setStyleSheet(on)
        else:
            self.center_block.setStyleSheet(on)

        self.dir_label.setText(f"Dir: {direction}")

    # ---------- Serial handshake ----------
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

        # Wait for "SYSTEM READY" so we don't lose START during boot
        ready = False
        t0 = time.time()
        while time.time() - t0 < 3.0:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    # print("BOOT:", line)  # uncomment to debug boot lines
                    if "SYSTEM READY" in line:
                        ready = True
                        break
            except Exception:
                break

        if not ready:
            # still try to proceed; some boards won't print reliably
            pass

        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

        # Send START after boot
        try:
            self.ser.write(b"START\n")
            self.ser.flush()
            print("Connected on", self.port, "→ START sent")
            return True
        except Exception as e:
            print("Failed to send START:", e)
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            return False

    def send(self, txt: str):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write((txt + "\n").encode("utf-8"))
                self.ser.flush()
            except Exception:
                pass

    def close_serial(self):
        if self.ser and self.ser.is_open:
            try:
                self.send("STOP")
            except Exception:
                pass
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    # ---------- Controls ----------
    def start_test(self):
        if not (self.ser and self.ser.is_open):
            if not self.open_serial_and_start():
                return

        self.is_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.last_time = None

    def stop_test(self):
        self.is_running = False
        self.close_serial()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ---------- Data loop ----------
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
                    x_v, y_v, direction = parsed
                    self.update_ui(x_v, y_v, direction)
                    updated = True
        except Exception:
            # unplugged / error
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

    def update_ui(self, x_v, y_v, direction):
        self.x_label.setText(f"X: {x_v:.2f} V")
        self.y_label.setText(f"Y: {y_v:.2f} V")
        self.bar_x.setValue(max(0, min(500, int(x_v * 100))))
        self.bar_y.setValue(max(0, min(500, int(y_v * 100))))
        self.highlight(direction)

    def closeEvent(self, e):
        self.stop_test()
        super().closeEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Lab4JoystickGUI()
    w.resize(700, 400)
    w.show()
    sys.exit(app.exec())