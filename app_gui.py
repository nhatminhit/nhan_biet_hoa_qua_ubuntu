"""
Giao dien Desktop Chuyen nghiep (CustomTkinter)
He thong Phan loai Trai cay tren Bang chuyen (Fruit Conveyor AI)
- HO TRO CHE DO BOUNDING BOX & DEM SO LUONG QUA LANH / HONG
- Dau vao: Chon file video MP4 hoac Webcam
- Xu ly Real-time Single-Stage YOLO Detection / Two-Stage Pipeline (tu dong theo best.pt)
- Vach dem san luong thong minh (Counting Line)
- Truc quan hoa Eigen-CAM Heatmap
"""

import os
import re
import sys
import subprocess
import time
import threading
import json
import webbrowser
from datetime import datetime
from collections import deque
import numpy as np
import cv2
from PIL import Image, ImageTk
import customtkinter as ctk
from tkinter import filedialog, messagebox

from conveyor_core import CLASS_NAMES, EigenCAM, ConveyorController, normalize_class_name
from conveyor_bbox_detector import FruitTracker2Stage
from ultralytics import YOLO
from report_generator import generate_session_report

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def _detect_linux_xft_dpi():
    """Đọc Xft.dpi trên Linux/Ubuntu để đồng bộ tỷ lệ font và khung widget."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        out = subprocess.check_output(["xrdb", "-query"], text=True, stderr=subprocess.DEVNULL, timeout=1.5)
        match = re.search(r"Xft\.dpi:\s*([0-9]+(?:\.[0-9]+)?)", out)
        if match:
            dpi = float(match.group(1))
            if dpi > 96.0:
                return dpi
    except Exception:
        pass
    return None


_LINUX_XFT_DPI = _detect_linux_xft_dpi()
_LINUX_UI_SCALE = min(_LINUX_XFT_DPI / 96.0, 1.65) if _LINUX_XFT_DPI else 1.0
if _LINUX_XFT_DPI:
    ctk.set_widget_scaling(_LINUX_UI_SCALE)
    ctk.set_window_scaling(_LINUX_UI_SCALE)


class ConveyorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self._ui_scale = _LINUX_UI_SCALE
        if _LINUX_XFT_DPI:
            self.tk.call("tk", "scaling", _LINUX_XFT_DPI / 72.0)

        self.title("Hệ Thống Phân Loại Trái Cây Băng Chuyền - YOLOv8 Bounding Box & Counting")
        self.geometry("1320x840")
        self.minsize(1120, 760)

        # Trạng thái ứng dụng
        self.running = False
        self.paused = False
        self.video_thread = None
        self.cap = None
        self._session_id = 0
        self._closing = False
        self._processing_lock = threading.RLock()
        self._use_bbox_mode = True
        self._use_heatmap = False
        self.video_source = "demo_conveyor.mp4"
        self.model_path = "best.pt"
        self.config_path = "camera_calibration.json"
        self.rejected_dir = os.path.join("output", "rejected_products")
        self.explanations_dir = os.path.join("output", "explanations")
        self.dashboard_state_path = os.path.join("output", "dashboard_state.json")
        self.production_log_path = os.path.join("output", "production_log.jsonl")
        self.demo_session_path = "exhibition_session.json"
        self.batch_id = "DEMO-001"
        self.batch_fruit = "Trái cây"
        self.average_weight_g = 180.0
        self.purchase_price_per_kg = 30000.0
        self._last_dashboard_write = 0.0
        self._last_logged_total = 0
        self._current_fps = 0.0
        self._current_latency_ms = 0.0
        self._dashboard_started_at = None
        self.roi_enabled = False
        self.save_rejected_images = True
        self.roi_x1, self.roi_y1 = 0.05, 0.10
        self.roi_x2, self.roi_y2 = 0.95, 0.90
        self._load_calibration()
        self._load_demo_session()

        # Tải 2 mô hình (Classification & Two-Stage Bounding Box Tracker)
        self.cls_model = None
        self.cam_generator = None
        self.controller = None
        self.bbox_tracker = None
        self.load_models_safe()

        # Xây dựng giao diện
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(500, self._dashboard_heartbeat)

    def load_models_safe(self):
        try:
            if os.path.exists(self.model_path):
                self.cls_model = YOLO(self.model_path)
                self.cam_generator = EigenCAM(self.cls_model)
                self.controller = ConveyorController(debounce_frames=5, conf_thresh=0.80)
                
                # Khởi tạo bộ Bounding Box & Tracking (tự nhận diện Single-Stage Detect hoặc Two-Stage)
                self.bbox_tracker = FruitTracker2Stage(
                    cls_model_path=self.model_path,
                    det_model_path="yolov8n.pt",
                    counting_line_ratio=0.50,
                    line_orientation="vertical",
                    cls_model=self.cls_model,
                )
            else:
                messagebox.showerror("Lỗi", f"Không tìm thấy file model: {self.model_path}")
        except Exception as e:
            messagebox.showerror("Lỗi tải model", str(e))

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=int(370 * self._ui_scale))
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ======================================================================
        # CỘT TRÁI: ĐIỀU KHIỂN & CẤU HÌNH
        # ======================================================================
        left_panel = ctk.CTkScrollableFrame(self, corner_radius=12, width=370)
        left_panel.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")

        # Tiêu đề
        lbl_title = ctk.CTkLabel(
            left_panel, 
            text="🍎 BĂNG CHUYỀN AI", 
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#00D2FF"
        )
        lbl_title.pack(pady=(14, 2))
        lbl_sub = ctk.CTkLabel(left_panel, text="Bounding Box & Line Counting Dashboard", font=ctk.CTkFont(size=11), text_color="#B0BEC5")
        lbl_sub.pack(pady=(0, 10))

        # Khung 1: Chọn Nguồn Video
        box_source = ctk.CTkFrame(left_panel, corner_radius=8, fg_color="#1F232B")
        box_source.pack(fill="x", padx=12, pady=5)

        ctk.CTkLabel(box_source, text="📂 NGUỒN ĐẦU VÀO", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=10, pady=(6, 4))
        
        # Nút duy nhất cho tải/đổi video theo yêu cầu người dùng (Màu tím đồng bộ)
        btn_clear_load_new = ctk.CTkButton(
            box_source, 
            text="🗑️ Xóa video cũ & Tải video mới", 
            command=self.clear_and_load_new_video,
            fg_color="#8E24AA", 
            hover_color="#7B1FA2",
            font=ctk.CTkFont(weight="bold")
        )
        btn_clear_load_new.pack(fill="x", padx=10, pady=5)

        btn_sample = ctk.CTkButton(
            box_source, 
            text="🎬 Dùng Video Mẫu (demo_conveyor.mp4)", 
            command=self.use_sample_video,
            fg_color="#37474F", 
            hover_color="#455A64"
        )
        btn_sample.pack(fill="x", padx=10, pady=3)

        btn_cam = ctk.CTkButton(
            box_source, 
            text="📹 Sử dụng Webcam máy tính", 
            command=self.use_webcam,
            fg_color="#37474F", 
            hover_color="#455A64"
        )
        btn_cam.pack(fill="x", padx=10, pady=3)

        btn_session = ctk.CTkButton(
            box_source,
            text="🏷️ Bắt đầu Lô",
            command=self.open_demo_session_window,
            fg_color="#00695C", hover_color="#00796B",
            font=ctk.CTkFont(weight="bold")
        )
        btn_session.pack(fill="x", padx=10, pady=3)

        btn_end_session = ctk.CTkButton(
            box_source, text="📄 Kết thúc phiên & Tạo báo cáo",
            command=self.end_demo_session,
            fg_color="#AD6A00", hover_color="#8A5400"
        )
        btn_end_session.pack(fill="x", padx=10, pady=(3, 5))

        self.lbl_selected_source = ctk.CTkLabel(
            box_source, 
            text=f"Đã chọn: {os.path.basename(self.video_source)}", 
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#90CAF9",
            wraplength=int(320 * self._ui_scale)
        )
        self.lbl_selected_source.pack(padx=10, pady=(3, 6))

        # Khung 2: Chế độ AI & Bounding Box
        box_settings = ctk.CTkFrame(left_panel, corner_radius=8, fg_color="#1F232B")
        box_settings.pack(fill="x", padx=12, pady=5)

        ctk.CTkLabel(box_settings, text="🎯 CHẾ ĐỘ NHẬN DIỆN", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=10, pady=(6, 4))

        # Công tắc bật Bounding Box Mode (Mặc định: BẬT)
        self.switch_bbox = ctk.CTkSwitch(
            box_settings, 
            text="📦 Bounding Box (Đếm Quả Lành / Hỏng)", 
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_bbox_toggle,
            progress_color="#00C853"
        )
        self.switch_bbox.select()
        self.switch_bbox.pack(anchor="w", padx=10, pady=6)

        self.lbl_line = ctk.CTkLabel(box_settings, text="Vị trí Vạch đếm DỌC (Vertical Line): 50%", font=ctk.CTkFont(size=11))
        self.lbl_line.pack(anchor="w", padx=10, pady=(2, 0))
        self.slider_line = ctk.CTkSlider(box_settings, from_=0.15, to=0.85, number_of_steps=14, command=self._on_line_change)
        self.slider_line.set(0.50)
        self.slider_line.pack(fill="x", padx=10, pady=(2, 6))

        # Công tắc: Tắt Bounding Box sau khi qua vạch vàng (Mặc định: BẬT)
        self.switch_hide_after_line = ctk.CTkSwitch(
            box_settings, 
            text="🚫 Tắt Bounding Box sau vạch vàng", 
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_hide_box_toggle,
            progress_color="#FF9100"
        )
        self.switch_hide_after_line.select()
        self.switch_hide_after_line.pack(anchor="w", padx=10, pady=(2, 6))

        # Thanh trượt 1: Độ tin cậy Bounding Box (Det Confidence)
        self.lbl_det_conf = ctk.CTkLabel(box_settings, text="🎯 Độ tin cậy Bounding Box (Det Conf): 40%", font=ctk.CTkFont(size=11))
        self.lbl_det_conf.pack(anchor="w", padx=10, pady=(2, 0))
        self.slider_det_conf = ctk.CTkSlider(box_settings, from_=0.15, to=0.80, number_of_steps=13, command=self._on_det_conf_change)
        self.slider_det_conf.set(0.40)
        self.slider_det_conf.pack(fill="x", padx=10, pady=(2, 6))

        # Thanh trượt 2: Ngưỡng lọc hoa quả / loại bỏ nền rác (Cls Threshold)
        self.lbl_cls_thresh = ctk.CTkLabel(box_settings, text="🛡️ Ngưỡng lọc hoa quả (Cls Thresh): 65%", font=ctk.CTkFont(size=11))
        self.lbl_cls_thresh.pack(anchor="w", padx=10, pady=(2, 0))
        self.slider_cls_thresh = ctk.CTkSlider(box_settings, from_=0.40, to=0.90, number_of_steps=10, command=self._on_cls_thresh_change)
        self.slider_cls_thresh.set(0.65)
        self.slider_cls_thresh.pack(fill="x", padx=10, pady=(2, 6))

        self.switch_cam = ctk.CTkSwitch(
            box_settings, text="Bản đồ nhiệt Eigen-CAM (Heatmap)",
            font=ctk.CTkFont(size=11), command=self._on_heatmap_toggle
        )
        self.switch_cam.pack(anchor="w", padx=10, pady=6)

        btn_calibration = ctk.CTkButton(
            box_settings,
            text="⚙ Hiệu chuẩn Camera & ROI",
            command=self.open_calibration_window,
            fg_color="#455A64",
            hover_color="#546E7A",
            height=28
        )
        btn_calibration.pack(fill="x", padx=10, pady=(0, 7))

        # Khung 3: Bộ điều khiển
        box_ctrl = ctk.CTkFrame(left_panel, corner_radius=8, fg_color="#1F232B")
        box_ctrl.pack(fill="x", padx=12, pady=5)

        ctk.CTkLabel(box_ctrl, text="🎮 ĐIỀU KHIỂN", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=10, pady=(6, 4))

        self.btn_start = ctk.CTkButton(
            box_ctrl, 
            text="▶ BẮT ĐẦU CHẠY", 
            command=self.start_processing,
            fg_color="#00C853", 
            hover_color="#00A344",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=34
        )
        self.btn_start.pack(fill="x", padx=10, pady=3)

        self.btn_pause = ctk.CTkButton(
            box_ctrl, 
            text="⏸ TẠM DỪNG", 
            command=self.toggle_pause,
            fg_color="#FF9100", 
            hover_color="#E65100",
            state="disabled",
            height=30
        )
        self.btn_pause.pack(fill="x", padx=10, pady=3)

        self.btn_stop = ctk.CTkButton(
            box_ctrl, 
            text="⏹ DỪNG LẠI", 
            command=self.stop_processing,
            fg_color="#D50000", 
            hover_color="#9B0000",
            state="disabled",
            height=30
        )
        self.btn_stop.pack(fill="x", padx=10, pady=3)

        btn_reset = ctk.CTkButton(
            box_ctrl, 
            text="🔄 Đặt lại bộ đếm sản lượng", 
            command=self.reset_counters,
            fg_color="#424242", 
            hover_color="#616161",
            height=28
        )
        btn_reset.pack(fill="x", padx=10, pady=(3, 6))

        # ======================================================================
        # CỘT PHẢI: KHUNG XEM VIDEO & BẢNG SẢN LƯỢNG
        # ======================================================================
        right_panel = ctk.CTkFrame(self, corner_radius=12)
        right_panel.grid(row=0, column=1, padx=(0, 12), pady=12, sticky="nsew")
        right_panel.grid_rowconfigure(0, weight=1)
        right_panel.grid_rowconfigure(1, weight=0)
        right_panel.grid_columnconfigure(0, weight=1)

        # 1. Khung hiển thị Video
        self.video_container = ctk.CTkFrame(right_panel, corner_radius=8, fg_color="#101216")
        self.video_container.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.lbl_video = ctk.CTkLabel(self.video_container, text="[Vui lòng chọn file MP4 và bấm BẮT ĐẦU CHẠY]")
        self.lbl_video.pack(expand=True, fill="both")

        # 2. Bảng Thống kê & Giám sát bên dưới
        stats_frame = ctk.CTkFrame(right_panel, corner_radius=8, fg_color="#1B1E24")
        stats_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Card 1: Tổng số quả đã đếm
        c1 = ctk.CTkFrame(stats_frame, fg_color="#242831", corner_radius=6)
        c1.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(c1, text="TỔNG ĐÃ QUA VẠCH", font=ctk.CTkFont(size=11, weight="bold"), text_color="#B0BEC5").pack(padx=10, pady=(8, 2))
        self.val_total = ctk.CTkLabel(c1, text="0", font=ctk.CTkFont(size=24, weight="bold"), text_color="#FFFFFF")
        self.val_total.pack(padx=10, pady=(0, 8))

        # Card 2: Quả Lành (Xanh)
        c2 = ctk.CTkFrame(stats_frame, fg_color="#242831", corner_radius=6)
        c2.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(c2, text="🟢 QUẢ LÀNH (ĐẠT)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#81C784").pack(padx=10, pady=(8, 2))
        self.val_good = ctk.CTkLabel(c2, text="0", font=ctk.CTkFont(size=24, weight="bold"), text_color="#00E676")
        self.val_good.pack(padx=10, pady=(0, 8))

        # Card 3: Quả Hỏng (Đỏ)
        c3 = ctk.CTkFrame(stats_frame, fg_color="#242831", corner_radius=6)
        c3.grid(row=0, column=2, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(c3, text="🔴 QUẢ HỎNG (LOẠI)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#E57373").pack(padx=10, pady=(8, 2))
        self.val_rejected = ctk.CTkLabel(c3, text="0", font=ctk.CTkFont(size=24, weight="bold"), text_color="#FF1744")
        self.val_rejected.pack(padx=10, pady=(0, 8))

        # Card 4: Tỷ lệ hỏng
        c4 = ctk.CTkFrame(stats_frame, fg_color="#242831", corner_radius=6)
        c4.grid(row=0, column=3, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(c4, text="TỶ LỆ HAO HỤT", font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFB74D").pack(padx=10, pady=(8, 2))
        self.val_defect = ctk.CTkLabel(c4, text="0.0%", font=ctk.CTkFont(size=24, weight="bold"), text_color="#FF9100")
        self.val_defect.pack(padx=10, pady=(0, 8))

        # Thanh trạng thái bên dưới
        detail_frame = ctk.CTkFrame(stats_frame, fg_color="#181A20", corner_radius=6)
        detail_frame.grid(row=1, column=0, columnspan=4, padx=6, pady=(0, 6), sticky="ew")
        detail_frame.grid_columnconfigure((0, 1), weight=1)

        self.lbl_active_fruits = ctk.CTkLabel(detail_frame, text="🔍 Đang theo dõi trên băng chuyền: 0 quả", font=ctk.CTkFont(size=12))
        self.lbl_active_fruits.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        self.lbl_recent_event = ctk.CTkLabel(detail_frame, text="Sự kiện: Chờ quả qua vạch đếm...", font=ctk.CTkFont(size=12), text_color="#90CAF9")
        self.lbl_recent_event.grid(row=0, column=1, padx=10, pady=5, sticky="e")

    # ==========================================================================
    # CÁC HÀM XỬ LÝ NGUỒN VIDEO
    # ==========================================================================
    def clear_and_load_new_video(self):
        """
        Nút ở phần NGUỒN ĐẦU VÀO:
        Lúc đang chạy video cũ -> Bấm nút này sẽ:
        1. Dừng ngay video cũ đang phát (giải phóng tài nguyên)
        2. Xóa khung hình video trên màn hình
        3. Reset bộ đếm số lượng của video cũ về 0
        4. Mở hộp thoại chọn file video MP4 mới
        5. Tự động phát video mới ngay lập tức
        """
        if self.running:
            self.stop_processing(update_message=False)

        # Xóa hình ảnh video cũ trên màn hình
        self.lbl_video.configure(image="", text="[Đang chọn video mới...]")
        self.lbl_video.image = None

        # Reset bộ đếm
        self.reset_counters()

        # Mở hộp thoại chọn video mới
        file_path = filedialog.askopenfilename(
            title="Chọn File Video Băng Chuyền Mới",
            filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv *.wmv"), ("Tất cả files", "*.*")]
        )

        if file_path:
            self._switch_source(file_path, f"Đã chọn: {os.path.basename(file_path)}")
        else:
            self.btn_start.configure(state="normal")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.lbl_video.configure(text="[Đã dừng video cũ. Nhấn 'Chọn File Video' để tải video mới]")

    def browse_video_file(self):
        file_path = filedialog.askopenfilename(
            title="Chọn File Video Băng Chuyền",
            filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv *.wmv"), ("Tất cả files", "*.*")]
        )
        if file_path:
            if self.running:
                self.stop_processing()
            self.video_source = file_path
            self.lbl_selected_source.configure(text=f"Đã chọn: {os.path.basename(file_path)}")

    def use_sample_video(self):
        sample_path = "demo_conveyor.mp4"
        if os.path.exists(sample_path):
            self._switch_source(sample_path, f"Đã chọn: {os.path.basename(sample_path)}")
        else:
            messagebox.showwarning("Cảnh báo", "Chưa tìm thấy file demo_conveyor.mp4!")

    def use_webcam(self):
        # Chọn webcam là chuyển nguồn và phát ngay, không cần bấm BẮT ĐẦU.
        self._switch_source(0, "Đã chọn: Webcam máy tính (Camera 0)")

    def _switch_source(self, source, label):
        """Chuyển nguồn an toàn và bắt đầu một phiên thống kê mới."""
        self.stop_processing(update_message=False)
        self.reset_counters()
        self.video_source = source
        self._apply_source_profile(source)
        self.lbl_selected_source.configure(text=label)
        self.lbl_video.configure(image="", text="[Đang mở nguồn video...]")
        self.lbl_video.image = None
        self.start_processing()

    def _apply_source_profile(self, source):
        """Dùng cấu hình nhạy hơn cho webcam, cấu hình chặt hơn cho file video."""
        if not self.bbox_tracker:
            return

        is_webcam = isinstance(source, int)
        is_single_stage = bool(getattr(self.bbox_tracker, "is_single_stage", False))
        det_conf = 0.25 if is_webcam else (0.35 if is_single_stage else 0.40)
        cls_conf = 0.50 if (is_webcam or is_single_stage) else 0.65
        self.bbox_tracker.detection_imgsz = 640 if (is_webcam or is_single_stage) else 320
        self.bbox_tracker.classification_samples = 4 if (is_webcam or is_single_stage) else 2
        self.bbox_tracker.reject_bias = 1.15 if is_webcam else (1.08 if is_single_stage else 1.10)
        self.bbox_tracker.box_padding_ratio = 0.08 if is_webcam else (0.04 if is_single_stage else 0.06)
        self.bbox_tracker.det_conf_thresh = det_conf
        self.bbox_tracker.cls_conf_thresh = cls_conf
        self.slider_det_conf.set(det_conf)
        self.slider_cls_thresh.set(cls_conf)
        self.lbl_det_conf.configure(
            text=f"🎯 Độ tin cậy Bounding Box (Det Conf): {int(det_conf * 100)}%"
        )
        self.lbl_cls_thresh.configure(
            text=f"🛡️ Ngưỡng lọc hoa quả (Cls Thresh): {int(cls_conf * 100)}%"
        )

    def _on_line_change(self, val):
        self.lbl_line.configure(text=f"Vị trí Vạch đếm DỌC (Vertical Line): {int(val*100)}%")
        if self.bbox_tracker:
            self.bbox_tracker.counting_line_ratio = val

    def _on_bbox_toggle(self):
        self._use_bbox_mode = bool(self.switch_bbox.get())

    def _on_heatmap_toggle(self):
        self._use_heatmap = bool(self.switch_cam.get())

    def _on_hide_box_toggle(self):
        if self.bbox_tracker:
            self.bbox_tracker.hide_box_after_line = bool(self.switch_hide_after_line.get())

    def _on_det_conf_change(self, val):
        self.lbl_det_conf.configure(text=f"🎯 Độ tin cậy Bounding Box (Det Conf): {int(val*100)}%")
        if self.bbox_tracker:
            self.bbox_tracker.det_conf_thresh = val

    def _on_cls_thresh_change(self, val):
        self.lbl_cls_thresh.configure(text=f"🛡️ Ngưỡng lọc hoa quả (Cls Thresh): {int(val*100)}%")
        if self.bbox_tracker:
            self.bbox_tracker.cls_conf_thresh = val

    def _load_calibration(self):
        try:
            if not os.path.exists(self.config_path):
                return
            with open(self.config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
            self.roi_enabled = bool(data.get("roi_enabled", self.roi_enabled))
            self.save_rejected_images = bool(
                data.get("save_rejected_images", self.save_rejected_images)
            )
            roi = data.get("roi", {})
            self.roi_x1 = float(roi.get("x1", self.roi_x1))
            self.roi_y1 = float(roi.get("y1", self.roi_y1))
            self.roi_x2 = float(roi.get("x2", self.roi_x2))
            self.roi_y2 = float(roi.get("y2", self.roi_y2))
            self._validate_roi()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Cấu hình lỗi sẽ dùng mặc định an toàn và có thể lưu lại từ cửa sổ hiệu chuẩn.
            pass

    def _load_demo_session(self):
        try:
            with open(self.demo_session_path, "r", encoding="utf-8") as session_file:
                data = json.load(session_file)
            self.batch_id = str(data.get("batch_id", self.batch_id))
            self.batch_fruit = "Trái cây"
            self.average_weight_g = float(data.get("average_weight_g", self.average_weight_g))
            self.purchase_price_per_kg = float(
                data.get("purchase_price_per_kg", self.purchase_price_per_kg)
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    def _generate_next_batch_id(self, prefix="DEMO"):
        """Tự động sinh mã lô tăng dần (VD: DEMO-001 -> DEMO-002 -> DEMO-003)."""
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
        max_num = 0

        def check_candidate(candidate):
            nonlocal max_num
            match = pattern.match(str(candidate or "").strip())
            if match:
                max_num = max(max_num, int(match.group(1)))

        check_candidate(self.batch_id)

        try:
            if os.path.exists(self.demo_session_path):
                with open(self.demo_session_path, "r", encoding="utf-8") as f:
                    check_candidate(json.load(f).get("batch_id"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        try:
            if os.path.exists(self.production_log_path):
                with open(self.production_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            check_candidate(json.loads(line).get("batch_id"))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass

        return f"{prefix}-{max_num + 1:03d}"

    def open_demo_session_window(self):
        window = ctk.CTkToplevel(self)
        window.title("Bắt đầu Lô")
        window.geometry("470x470")
        window.transient(self)
        window.grab_set()

        next_batch_id = self._generate_next_batch_id()

        ctk.CTkLabel(
            window, text="PHIÊN TRÌNH DIỄN MỚI",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#00D2FF"
        ).pack(pady=(18, 5))
        ctk.CTkLabel(
            window, text="Mỗi phiên mới sẽ tự động tăng mã lô và đặt lại thống kê trên GUI & dashboard.",
            text_color="#B0BEC5", wraplength=410
        ).pack(pady=(0, 12))

        form = ctk.CTkFrame(window, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=28)

        def add_entry(label, value, readonly=False):
            ctk.CTkLabel(form, text=label).pack(anchor="w", pady=(8, 3))
            entry = ctk.CTkEntry(form)
            entry.insert(0, str(value))
            if readonly:
                entry.configure(state="readonly", text_color="#00D2FF")
            entry.pack(fill="x")
            return entry

        add_entry("Mã lô tự động (tăng dần)", next_batch_id, readonly=True)
        ctk.CTkLabel(
            form, text="Kết quả AI: Phân loại QUẢ LÀNH / QUẢ HỎNG",
            text_color="#81C784", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", pady=(10, 4))
        weight_entry = add_entry("Khối lượng trung bình mỗi quả (gram)", self.average_weight_g)
        price_entry = add_entry("Giá trị trung bình (VNĐ/kg)", self.purchase_price_per_kg)

        def start_session():
            try:
                weight = float(weight_entry.get())
                price = float(price_entry.get())
                if weight <= 0 or price < 0:
                    raise ValueError("Thông tin phiên không hợp lệ.")
                self.batch_id = next_batch_id
                self.batch_fruit = "Trái cây"
                self.average_weight_g = weight
                self.purchase_price_per_kg = price
                data = {
                    "batch_id": self.batch_id, "fruit": self.batch_fruit,
                    "average_weight_g": weight, "purchase_price_per_kg": price,
                }
                with open(self.demo_session_path, "w", encoding="utf-8") as session_file:
                    json.dump(data, session_file, ensure_ascii=False, indent=2)
                self._dashboard_started_at = time.time()
                self.reset_counters()
                self._write_dashboard_snapshot(force=True)
                window.destroy()
                messagebox.showinfo("Phiên mới", f"Đã bắt đầu phiên: {self.batch_id}")
            except (ValueError, OSError) as exc:
                messagebox.showerror("Không thể bắt đầu phiên", str(exc))

        ctk.CTkButton(
            window, text="BẮT ĐẦU PHIÊN & RESET THỐNG KÊ",
            command=start_session, fg_color="#00A344", hover_color="#008A3B", height=38
        ).pack(fill="x", padx=28, pady=(12, 20))

    def end_demo_session(self):
        if self.running:
            self.stop_processing(update_message=False)
        self._write_dashboard_snapshot(force=True)
        try:
            report_path = generate_session_report(
                self.batch_id, self.production_log_path, os.path.join("output", "reports")
            ).resolve()
            webbrowser.open(report_path.as_uri())
            messagebox.showinfo(
                "Đã kết thúc phiên",
                f"Đã tạo báo cáo cuối phiên {self.batch_id}:\n{report_path}"
            )
        except OSError as exc:
            messagebox.showerror("Không thể tạo báo cáo", str(exc))

    def _validate_roi(self):
        self.roi_x1 = max(0.0, min(0.80, self.roi_x1))
        self.roi_y1 = max(0.0, min(0.80, self.roi_y1))
        self.roi_x2 = max(self.roi_x1 + 0.15, min(1.0, self.roi_x2))
        self.roi_y2 = max(self.roi_y1 + 0.15, min(1.0, self.roi_y2))

    def open_calibration_window(self):
        window = ctk.CTkToplevel(self)
        window.title("Hiệu chuẩn Camera & Vùng nhận diện")
        window.geometry("520x560")
        window.transient(self)
        window.grab_set()

        ctk.CTkLabel(
            window, text="HIỆU CHUẨN NHẬN DIỆN",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#00D2FF"
        ).pack(pady=(16, 4))
        ctk.CTkLabel(
            window,
            text="Khung ROI màu xanh sẽ giới hạn AI chỉ quan sát khu vực băng chuyền.",
            wraplength=460, text_color="#B0BEC5"
        ).pack(pady=(0, 10))

        roi_switch = ctk.CTkSwitch(window, text="Bật vùng nhận diện ROI")
        if self.roi_enabled:
            roi_switch.select()
        roi_switch.pack(anchor="w", padx=28, pady=6)

        save_switch = ctk.CTkSwitch(window, text="Tự lưu ảnh sản phẩm hỏng / bị loại")
        if self.save_rejected_images:
            save_switch.select()
        save_switch.pack(anchor="w", padx=28, pady=6)

        sliders = []
        values = [self.roi_x1, self.roi_x2, self.roi_y1, self.roi_y2]
        labels = ["Mép trái", "Mép phải", "Mép trên", "Mép dưới"]
        for label_text, value in zip(labels, values):
            row = ctk.CTkFrame(window, fg_color="transparent")
            row.pack(fill="x", padx=28, pady=5)
            value_label = ctk.CTkLabel(row, text=f"{label_text}: {int(value * 100)}%")
            value_label.pack(anchor="w")
            slider = ctk.CTkSlider(row, from_=0.0, to=1.0, number_of_steps=100)
            slider.set(value)
            slider.configure(
                command=lambda val, lbl=value_label, name=label_text:
                lbl.configure(text=f"{name}: {int(float(val) * 100)}%")
            )
            slider.pack(fill="x", pady=(2, 0))
            sliders.append(slider)

        def save_settings():
            self.roi_enabled = bool(roi_switch.get())
            self.save_rejected_images = bool(save_switch.get())
            self.roi_x1, self.roi_x2, self.roi_y1, self.roi_y2 = [
                float(slider.get()) for slider in sliders
            ]
            self._validate_roi()
            data = {
                "roi_enabled": self.roi_enabled,
                "save_rejected_images": self.save_rejected_images,
                "roi": {
                    "x1": self.roi_x1, "y1": self.roi_y1,
                    "x2": self.roi_x2, "y2": self.roi_y2
                }
            }
            try:
                with open(self.config_path, "w", encoding="utf-8") as config_file:
                    json.dump(data, config_file, ensure_ascii=False, indent=2)
                self.reset_counters()
                window.destroy()
                messagebox.showinfo(
                    "Đã lưu", "Đã lưu hiệu chuẩn. Bộ đếm đã được đặt lại từ đầu."
                )
            except OSError as exc:
                messagebox.showerror("Không thể lưu hiệu chuẩn", str(exc))

        ctk.CTkButton(
            window, text="LƯU VÀ ÁP DỤNG", command=save_settings,
            fg_color="#00A344", hover_color="#008A3B", height=36
        ).pack(fill="x", padx=28, pady=(16, 8))

    def reset_counters(self):
        # Đợi lượt nhận diện đang chạy hoàn tất trước khi xóa thống kê.
        # Sau stop_processing(), session cũ không thể bước vào lượt mới nữa.
        with self._processing_lock:
            if self.bbox_tracker:
                self.bbox_tracker.reset_counts()
            if self.controller:
                self.controller.reset_counters()
        self._update_stats_display()

    # ==========================================================================
    # VÒNG LẶP SUY LUẬN (INFERENCE LOOP)
    # ==========================================================================
    def start_processing(self):
        if self.running:
            return

        if isinstance(self.video_source, str) and not os.path.exists(self.video_source):
            messagebox.showerror("Lỗi", f"Không tìm thấy file: {self.video_source}")
            return

        # DirectShow thường mở webcam trên Windows nhanh và ổn định hơn.
        if isinstance(self.video_source, int) and os.name == "nt":
            cap = cv2.VideoCapture(self.video_source, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.video_source)
        else:
            cap = cv2.VideoCapture(self.video_source)

        if isinstance(self.video_source, int):
            # Ưu tiên khung hình HD, mới nhất và ít nén nhòe cho nhận diện webcam.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            if isinstance(self.video_source, int) and os.path.exists("demo_conveyor.mp4"):
                messagebox.showwarning(
                    "Webcam không khả dụng",
                    "Không thể mở webcam. Hệ thống sẽ tự chuyển sang video mẫu để tiếp tục trình diễn."
                )
                self.video_source = "demo_conveyor.mp4"
                self._apply_source_profile(self.video_source)
                self.lbl_selected_source.configure(text="Đang dùng dự phòng: demo_conveyor.mp4")
                self.after(100, self.start_processing)
                return
            messagebox.showerror("Lỗi", f"Không thể mở nguồn video: {self.video_source}")
            self.btn_start.configure(state="normal")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            return

        self._session_id += 1
        session_id = self._session_id
        self.cap = cap
        self.running = True
        self.paused = False
        self._dashboard_started_at = time.time()
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸ TẠM DỪNG")
        self.btn_stop.configure(state="normal")

        self.video_thread = threading.Thread(
            target=self._video_loop, args=(cap, session_id, self.video_source), daemon=True
        )
        self.video_thread.start()

    def toggle_pause(self):
        if not self.running:
            return
        self.paused = not self.paused
        if self.paused:
            self.btn_pause.configure(text="▶ TIẾP TỤC", fg_color="#2979FF")
        else:
            self.btn_pause.configure(text="⏸ TẠM DỪNG", fg_color="#FF9100")

    def stop_processing(self, update_message=True):
        self._session_id += 1
        self.running = False
        self.paused = False
        cap, self.cap = self.cap, None
        if cap:
            try:
                cap.release()
            except Exception:
                pass

        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        if update_message:
            self.lbl_video.configure(image="", text="[Đã dừng xử lý video]")
            self.lbl_video.image = None
        self._write_dashboard_snapshot(force=True)

    def _video_loop(self, cap, session_id, source):
        prev_time = time.time()
        fps_deque = deque(maxlen=20)
        latency_deque = deque(maxlen=20)

        while self.running and session_id == self._session_id:
            if self.paused:
                time.sleep(0.05)
                continue

            ret, frame = cap.read()
            if not ret or frame is None:
                if isinstance(source, str) and session_id == self._session_id:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    break

            t_start = time.time()
            try:
                processed_frame, active_count = self._process_frame(frame)
            except Exception as exc:
                if session_id == self._session_id and not self._closing:
                    self.after(0, self._on_processing_error, session_id, str(exc))
                break

            # Tính toán FPS & Độ trễ
            latency_ms = (time.time() - t_start) * 1000
            latency_deque.append(latency_ms)
            avg_latency = sum(latency_deque) / len(latency_deque)

            now = time.time()
            fps = 1.0 / (now - prev_time) if (now - prev_time) > 0 else 30.0
            prev_time = now
            fps_deque.append(fps)
            avg_fps = sum(fps_deque) / len(fps_deque)

            # Vẽ thêm thông số FPS & Latency góc trên bên phải
            cv2.putText(processed_frame, f"FPS: {avg_fps:.1f} | Latency: {avg_latency:.1f}ms", 
                        (processed_frame.shape[1] - 320, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            # Hiển thị lên giao diện
            if session_id == self._session_id and not self._closing:
                # Mọi cập nhật widget phải chạy trên luồng giao diện chính.
                self.after(
                    0, self._publish_frame, processed_frame.copy(), active_count,
                    session_id, avg_fps, avg_latency
                )

            elapsed = time.time() - now
            time.sleep(max(0.001, 0.020 - elapsed))

        cap.release()
        if session_id == self._session_id and not self._closing:
            self.after(0, self._on_stream_ended, session_id, source)

    def _process_frame(self, frame):
        """Xử lý một khung hình; khóa chung với thao tác reset bộ đếm."""
        with self._processing_lock:
            if self._use_bbox_mode:
                if not self.bbox_tracker:
                    raise RuntimeError("Mô hình Bounding Box chưa được tải thành công.")
                roi_frame, roi_bounds = self._extract_roi(frame)
                tracks = self.bbox_tracker.update(roi_frame)
                roi_visualized = self.bbox_tracker.draw_visualization(roi_frame)

                if self.roi_enabled:
                    x1, y1, x2, y2 = roi_bounds
                    processed_frame = frame.copy()
                    processed_frame[y1:y2, x1:x2] = roi_visualized
                    cv2.rectangle(processed_frame, (x1, y1), (x2 - 1, y2 - 1), (255, 180, 0), 2)
                    cv2.putText(
                        processed_frame, "ROI - VUNG NHAN DIEN", (x1 + 8, max(24, y1 + 24)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 180, 0), 2
                    )
                else:
                    processed_frame = roi_visualized

                self._save_pending_rejections(roi_frame)
                active_count = len([
                    track for track in tracks.values()
                    if not track.get('counted', False) and not track.get('already_past', False)
                ])
                return processed_frame, active_count

            if not self.cls_model or not self.controller:
                raise RuntimeError("Mô hình chưa được tải thành công.")

            is_detect = getattr(self.cls_model, "task", None) == "detect"
            if is_detect:
                conf_min = self.bbox_tracker.det_conf_thresh if self.bbox_tracker else 0.35
                results = self.cls_model(frame, imgsz=640, conf=conf_min, verbose=False)
                res = results[0]
                if res.boxes is not None and len(res.boxes) > 0:
                    best_box = max(res.boxes, key=lambda b: float(b.conf[0]))
                    cls_id = int(best_box.cls[0])
                    conf = float(best_box.conf[0])
                    names = res.names or self.cls_model.names
                    raw_name = names.get(cls_id, "unknown") if isinstance(names, dict) else str(names[cls_id])
                    raw_cls = normalize_class_name(raw_name)
                else:
                    raw_cls = "empty_conveyor"
                    conf = 1.0
            else:
                results = self.cls_model(frame, verbose=False)
                res = results[0]
                if res.probs is None:
                    raise RuntimeError("Mô hình không trả về kết quả phân loại.")
                top1_idx = int(res.probs.top1)
                conf = float(res.probs.top1conf)
                raw_cls = normalize_class_name(CLASS_NAMES.get(top1_idx, 'unknown'))

            filtered_cls, _state = self.controller.update(raw_cls, conf)

            heatmap = None
            if self._use_heatmap and self.cam_generator:
                heatmap = self.cam_generator.generate(frame.shape)

            processed_frame = frame.copy()
            if heatmap is not None:
                processed_frame = cv2.addWeighted(processed_frame, 0.65, heatmap, 0.35, 0)
            active_count = 1 if filtered_cls not in ('empty_conveyor', 'unknown') else 0
            return processed_frame, active_count

    def _extract_roi(self, frame):
        h, w = frame.shape[:2]
        if not self.roi_enabled:
            return frame, (0, 0, w, h)

        x1 = int(w * self.roi_x1)
        y1 = int(h * self.roi_y1)
        x2 = int(w * self.roi_x2)
        y2 = int(h * self.roi_y2)
        x1, y1 = max(0, min(w - 2, x1)), max(0, min(h - 2, y1))
        x2, y2 = max(x1 + 2, min(w, x2)), max(y1 + 2, min(h, y2))
        return frame[y1:y2, x1:x2], (x1, y1, x2, y2)

    def _save_pending_rejections(self, roi_frame):
        events = list(self.bbox_tracker.pending_rejections)
        self.bbox_tracker.pending_rejections.clear()
        if not events or not self.save_rejected_images:
            return

        os.makedirs(self.rejected_dir, exist_ok=True)
        os.makedirs(self.explanations_dir, exist_ok=True)
        safe_batch = re.sub(r"[^A-Za-z0-9-]+", "-", str(self.batch_id or "SESSION").strip()).strip("-") or "SESSION"
        h, w = roi_frame.shape[:2]
        for event in events:
            x1, y1, x2, y2 = event['bbox']
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(w, int(x2)), min(h, int(y2))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = roi_frame[y1:y2, x1:x2]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            confidence = int(event.get('confidence', 0.0) * 100)
            filename = (
                f"loai_batch_{safe_batch}_{timestamp}_id{event['track_id']}_conf{confidence}.jpg"
            )
            output_path = os.path.join(self.rejected_dir, filename)
            if not cv2.imwrite(output_path, crop):
                raise OSError(f"Không thể lưu ảnh sản phẩm loại: {output_path}")

            # Ảnh giải thích: bên trái là crop gốc, bên phải tô đỏ vùng thâm/nâu.
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            dark_mask = cv2.inRange(hsv, (0, 35, 0), (180, 255, 68))
            brown_mask = cv2.inRange(hsv, (4, 45, 25), (28, 255, 190))
            defect_mask = cv2.bitwise_or(dark_mask, brown_mask)
            explained = crop.copy()
            red_layer = np.zeros_like(explained)
            red_layer[:, :] = (20, 20, 255)
            highlighted = cv2.addWeighted(explained, 0.45, red_layer, 0.55, 0)
            explained[defect_mask > 0] = highlighted[defect_mask > 0]
            comparison = np.hstack([crop, explained])
            comparison = cv2.copyMakeBorder(
                comparison, 38, 0, 0, 0, cv2.BORDER_CONSTANT, value=(18, 22, 20)
            )
            visual_pct = int(event.get('visual_defect', 0.0) * 100)
            cv2.putText(
                comparison,
                f"AI LOAI | Tin cay: {confidence}% | Vung tham/nau: {visual_pct}%",
                (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1
            )
            explanation_name = filename.replace("loai_", "giai_thich_", 1)
            cv2.imwrite(os.path.join(self.explanations_dir, explanation_name), comparison)

    def _publish_frame(self, frame, active_count, session_id, fps, latency_ms):
        if self._closing or session_id != self._session_id or not self.running:
            return
        self._current_fps = fps
        self._current_latency_ms = latency_ms
        self._display_frame(frame)
        self._update_stats_display(active_count)

    def _on_stream_ended(self, session_id, source):
        if self._closing or session_id != self._session_id:
            return
        self.running = False
        self.cap = None
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        if isinstance(source, int):
            self.lbl_video.configure(image="", text="[Webcam đã ngắt hoặc không đọc được hình ảnh]")
            self.lbl_video.image = None
        self._write_dashboard_snapshot(force=True)

    def _on_processing_error(self, session_id, error_message):
        if self._closing or session_id != self._session_id:
            return
        self._session_id += 1
        self.running = False
        self.paused = False
        self.cap = None
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="⏸ TẠM DỪNG")
        self.btn_stop.configure(state="disabled")
        self.lbl_video.configure(image="", text="[Xử lý AI đã dừng do có lỗi]")
        self.lbl_video.image = None
        self._write_dashboard_snapshot(force=True)
        messagebox.showerror(
            "Lỗi xử lý AI",
            f"Không thể tiếp tục nhận diện:\n\n{error_message}\n\n"
            "Bạn có thể kiểm tra nguồn video rồi bấm BẮT ĐẦU CHẠY để thử lại."
        )

    def _on_close(self):
        self._closing = True
        self._session_id += 1
        self.running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self._write_dashboard_snapshot(force=True)
        self.destroy()

    def _display_frame(self, frame_bgr):
        container_w = self.video_container.winfo_width()
        container_h = self.video_container.winfo_height()

        if container_w > 50 and container_h > 50:
            h, w = frame_bgr.shape[:2]
            scale = min((container_w - 20) / w, (container_h - 20) / h)
            target_w = max(100, int(w * scale))
            target_h = max(100, int(h * scale))
            resized = cv2.resize(frame_bgr, (target_w, target_h))
        else:
            resized = cv2.resize(frame_bgr, (720, 480))

        frame_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(frame_rgb)
        img_tk = ImageTk.PhotoImage(image=img_pil)

        self.lbl_video.configure(image=img_tk, text="")
        self.lbl_video.image = img_tk

    def _update_stats_display(self, active_count=0):
        if self.switch_bbox.get() and self.bbox_tracker:
            total = self.bbox_tracker.total_counted
            good = self.bbox_tracker.count_fresh
            rejected = self.bbox_tracker.count_rotten
            defect = (rejected / total * 100) if total > 0 else 0.0

            self.val_total.configure(text=str(total))
            self.val_good.configure(text=str(good))
            self.val_rejected.configure(text=str(rejected))
            self.val_defect.configure(text=f"{defect:.1f}%")

            self.lbl_active_fruits.configure(text=f"🔍 Đang theo dõi trên băng chuyền: {active_count} quả")
            recent = self.bbox_tracker.recent_events[-1] if self.bbox_tracker.recent_events else "Chờ quả qua vạch..."
            self.lbl_recent_event.configure(text=f"Sự kiện: {recent}")
        else:
            if self.controller:
                total = self.controller.total_processed
                good = self.controller.total_good
                rejected = self.controller.total_rejected
                defect = (rejected / total * 100) if total > 0 else 0.0

                self.val_total.configure(text=str(total))
                self.val_good.configure(text=str(good))
                self.val_rejected.configure(text=str(rejected))
                self.val_defect.configure(text=f"{defect:.1f}%")
                self.lbl_active_fruits.configure(text="Chế độ: Phân loại toàn khung hình")
        self._write_dashboard_snapshot(active_count=active_count)

    def _write_dashboard_snapshot(self, active_count=0, force=False):
        """Gửi thống kê GUI sang web bằng tệp JSON; web chỉ có quyền đọc."""
        now = time.time()
        if not force and now - self._last_dashboard_write < 0.5:
            return
        self._last_dashboard_write = now

        if self.switch_bbox.get() and self.bbox_tracker:
            total = self.bbox_tracker.total_counted
            good = self.bbox_tracker.count_fresh
            rejected = self.bbox_tracker.count_rotten
            events = list(self.bbox_tracker.recent_events[-8:])
            fruit_breakdown = {"fruit": dict(self.bbox_tracker.counts_by_fruit["fruit"])}
            event_records = list(self.bbox_tracker.recent_event_records)
        elif self.controller:
            total = self.controller.total_processed
            good = self.controller.total_good
            rejected = self.controller.total_rejected
            events = list(self.controller.event_log)
            fruit_breakdown = {}
            event_records = []
        else:
            total = good = rejected = 0
            events = []
            fruit_breakdown = {}
            event_records = []

        source = (
            f"Webcam {self.video_source}" if isinstance(self.video_source, int)
            else os.path.basename(self.video_source)
        )
        waste_kg = rejected * self.average_weight_g / 1000.0
        estimated_loss = waste_kg * self.purchase_price_per_kg
        snapshot = {
            "running": bool(self.running), "paused": bool(self.paused),
            "source": source, "total": total, "good": good,
            "rejected": rejected,
            "defect_rate": round(rejected / total * 100, 1) if total else 0.0,
            "active_tracks": active_count,
            "fps": round(self._current_fps, 1),
            "latency_ms": round(self._current_latency_ms, 1),
            "uptime_seconds": int(now - self._dashboard_started_at) if self._dashboard_started_at else 0,
            "events": events[::-1],
            "batch": {
                "id": self.batch_id, "fruit": self.batch_fruit,
                "average_weight_g": self.average_weight_g,
                "purchase_price_per_kg": self.purchase_price_per_kg,
            },
            "fruit_breakdown": fruit_breakdown,
            "waste_kg": round(waste_kg, 3),
            "estimated_loss_vnd": round(estimated_loss),
            "updated_at": datetime.now().isoformat(), "updated_at_epoch": now,
        }
        try:
            os.makedirs(os.path.dirname(self.dashboard_state_path), exist_ok=True)
            temp_path = self.dashboard_state_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as state_file:
                json.dump(snapshot, state_file, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.dashboard_state_path)

            if total > self._last_logged_total:
                new_count = total - self._last_logged_total
                new_records = event_records[-new_count:] if event_records else [
                    {"event": "Đã ghi nhận sản phẩm", "fruit_type": "unknown", "quality": "unknown"}
                ] * new_count
                with open(self.production_log_path, "a", encoding="utf-8") as log_file:
                    for event_record in new_records:
                        record = {
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "created_at": datetime.now().isoformat(),
                            "source": source, "batch_id": self.batch_id,
                            "batch_fruit": self.batch_fruit,
                            "event": event_record.get("event", "Đã ghi nhận sản phẩm"),
                            "fruit_type": "fruit",
                            "quality": event_record.get("quality", "unknown"),
                            "confidence": event_record.get("confidence", 0.0),
                            "total": total, "good": good, "rejected": rejected,
                            "waste_kg": round(waste_kg, 3),
                            "estimated_loss_vnd": round(estimated_loss),
                        }
                        log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._last_logged_total = total
        except OSError:
            # Lỗi ghi log không được phép làm dừng pipeline nhận diện chính.
            pass

    def _dashboard_heartbeat(self):
        """Giữ trạng thái kết nối GUI chính xác kể cả khi đang tạm dừng."""
        if self._closing:
            return
        self._write_dashboard_snapshot(force=True)
        self.after(1000, self._dashboard_heartbeat)


if __name__ == "__main__":
    app = ConveyorApp()
    app.mainloop()
