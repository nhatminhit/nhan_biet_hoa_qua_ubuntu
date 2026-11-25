"""One-click, failure-tolerant launcher for exhibition use."""

import importlib.util
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parent


def port_open(port=8000):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    print("=" * 64)
    print(" FRUITGUARD AI - CHE DO TRIEN LAM AN TOAN")
    print("=" * 64)
    required = ["best.pt", "yolov8n.pt", "demo_conveyor.mp4", "app_gui.py", "api_server.py"]
    missing = [name for name in required if not (ROOT / name).exists()]
    if missing:
        print("[LOI] Thieu tep bat buoc:", ", ".join(missing))
        input("Nhan Enter de thoat...")
        return 1
    for module in ("fastapi", "uvicorn", "customtkinter", "ultralytics"):
        if importlib.util.find_spec(module) is None:
            print(f"[LOI] Chua cai thu vien: {module}")
            input("Nhan Enter de thoat...")
            return 1

    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(0)
    camera_ok = camera.isOpened()
    camera.release()
    print("[OK] Model va thu vien san sang.")
    print("[OK] Webcam san sang." if camera_ok else "[DU PHONG] Khong co webcam - GUI se dung video mau.")

    web_process = None
    if not port_open():
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        web_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=ROOT, creationflags=flags,
        )
    else:
        print("[OK] Dashboard da dang chay tren cong 8000.")

    threading.Timer(2.0, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    try:
        return subprocess.call([sys.executable, "app_gui.py"], cwd=ROOT)
    finally:
        if web_process and web_process.poll() is None:
            web_process.terminate()
            try:
                web_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                web_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
