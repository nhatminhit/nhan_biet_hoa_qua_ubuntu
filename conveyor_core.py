"""Shared classification state and explainability helpers for the desktop GUI."""

import time
from collections import deque

import cv2
import numpy as np


CLASS_NAMES = {
    0: "empty_conveyor",
    1: "freshapples",
    2: "freshbanana",
    3: "freshoranges",
    4: "rottenapples",
    5: "rottenbanana",
    6: "rottenoranges",
}

CLASS_NAME_ALIASES = {
    "empty_conveyor": "empty_conveyor",
    "freshapples": "freshapples",
    "fresh_apple": "freshapples",
    "freshapple": "freshapples",
    "freshbanana": "freshbanana",
    "fresh_banana": "freshbanana",
    "freshbananas": "freshbanana",
    "freshoranges": "freshoranges",
    "fresh_orange": "freshoranges",
    "freshorange": "freshoranges",
    "rottenapples": "rottenapples",
    "rotten_apple": "rottenapples",
    "rottenapple": "rottenapples",
    "rottenbanana": "rottenbanana",
    "rotten_banana": "rottenbanana",
    "rottenbananas": "rottenbanana",
    "rottenoranges": "rottenoranges",
    "rotten_orange": "rottenoranges",
    "rottenorange": "rottenoranges",
}


def normalize_class_name(raw_name):
    """Chuẩn hóa tên class từ cả model Classification cũ và YOLO11 Detection mới."""
    if not raw_name:
        return "unknown"
    key = str(raw_name).strip().lower().replace("-", "_").replace(" ", "_")
    return CLASS_NAME_ALIASES.get(key, "unknown")


CLASS_DISPLAY = {
    "empty_conveyor": ("Bang chuyen trong", (130, 130, 130), "EMPTY"),
    "freshapples": ("Tao tuoi (Loai 1)", (50, 205, 50), "GATE_1"),
    "freshbanana": ("Chuoi tuoi (Loai 1)", (0, 215, 255), "GATE_2"),
    "freshoranges": ("Cam tuoi (Loai 1)", (0, 140, 255), "GATE_3"),
    "rottenapples": ("Tao hong (Loai bo)", (30, 30, 220), "GATE_REJECT"),
    "rottenbanana": ("Chuoi hong (Loai bo)", (30, 30, 220), "GATE_REJECT"),
    "rottenoranges": ("Cam hong (Loai bo)", (30, 30, 220), "GATE_REJECT"),
    "unknown": ("Vat the khong xac dinh", (180, 180, 0), "NONE"),
}

ACTUATORS = {
    "GATE_1": {"name": "Cong 1 (Tao tuoi)", "color": (50, 205, 50), "active_until": 0},
    "GATE_2": {"name": "Cong 2 (Chuoi tuoi)", "color": (0, 215, 255), "active_until": 0},
    "GATE_3": {"name": "Cong 3 (Cam tuoi)", "color": (0, 140, 255), "active_until": 0},
    "GATE_REJECT": {"name": "Can gat Loai bo (Qua hong)", "color": (30, 30, 220), "active_until": 0},
}


class EigenCAM:
    def __init__(self, model):
        self.model = model
        self.activations = None
        self.hook_handle = None
        self._find_and_register_target_layer()

    def _find_and_register_target_layer(self):
        target_layer = None
        if hasattr(self.model, "model") and hasattr(self.model.model, "model"):
            layers = self.model.model.model
            for layer in reversed(layers):
                cls_name = layer.__class__.__name__
                if any(token in cls_name for token in ("C3k2", "C2PSA", "C2f", "Conv")):
                    target_layer = layer
                    break

        if target_layer is not None:
            def forward_hook(module, inputs, output):
                self.activations = output.detach()

            self.hook_handle = target_layer.register_forward_hook(forward_hook)

    def generate(self, original_img_shape):
        if self.activations is None:
            return None
        activation = self.activations[0].cpu().float().numpy()
        if activation.ndim != 3:
            return None
        channels, height, width = activation.shape
        flattened = activation.reshape(channels, -1).T
        flattened -= np.mean(flattened, axis=0, keepdims=True)
        try:
            _, _, eigenvectors = np.linalg.svd(flattened, full_matrices=False)
            cam = flattened @ eigenvectors[0, :]
        except Exception:
            cam = np.mean(flattened, axis=1)

        cam = np.maximum(cam.reshape(height, width), 0)
        max_value = np.max(cam)
        if max_value > 0:
            cam /= max_value
        cam = cv2.resize(cam, (original_img_shape[1], original_img_shape[0]))
        return cv2.applyColorMap(np.uint8(255 * cam), cv2.COLORMAP_JET)


class ConveyorController:
    STATE_EMPTY = "EMPTY"
    STATE_STABILIZING = "STABILIZING"
    STATE_LOCKED = "LOCKED"
    STATE_COOLDOWN = "COOLDOWN"

    def __init__(self, debounce_frames=5, conf_thresh=0.80, unknown_thresh=0.65,
                 cooldown_frames=8, serial_port=None, baudrate=9600):
        self.debounce_frames = debounce_frames
        self.conf_thresh = conf_thresh
        self.unknown_thresh = unknown_thresh
        self.cooldown_frames = cooldown_frames
        self.history = deque(maxlen=debounce_frames)
        self.state = self.STATE_EMPTY
        self.current_candidate = None
        self.cooldown_counter = 0
        self.counters = {
            "freshapples": 0, "freshbanana": 0, "freshoranges": 0,
            "rottenapples": 0, "rottenbanana": 0, "rottenoranges": 0,
        }
        self.total_processed = 0
        self.total_good = 0
        self.total_rejected = 0
        self.event_log = deque(maxlen=6)

    def update(self, raw_class_name, confidence):
        filtered_class = raw_class_name
        if confidence < self.unknown_thresh:
            filtered_class = "unknown"
        elif raw_class_name == "empty_conveyor":
            filtered_class = "empty_conveyor"
        self.history.append((filtered_class, confidence))

        if self.state == self.STATE_EMPTY:
            if filtered_class not in ("empty_conveyor", "unknown") and confidence >= self.conf_thresh:
                self.state = self.STATE_STABILIZING
                self.current_candidate = filtered_class
        elif self.state == self.STATE_STABILIZING and len(self.history) == self.debounce_frames:
            matches = all(
                name == self.current_candidate and score >= self.conf_thresh
                for name, score in self.history
            )
            if matches:
                self._trigger_classification(self.current_candidate, confidence)
                self.state = self.STATE_LOCKED
            elif sum(name == "empty_conveyor" for name, _ in self.history) >= 2:
                self.state = self.STATE_EMPTY
                self.current_candidate = None
        elif self.state == self.STATE_LOCKED:
            self.state = self.STATE_COOLDOWN
            self.cooldown_counter = 0
        elif self.state == self.STATE_COOLDOWN and filtered_class == "empty_conveyor":
            self.cooldown_counter += 1
            if self.cooldown_counter >= self.cooldown_frames:
                self.state = self.STATE_EMPTY
                self.current_candidate = None
        return filtered_class, self.state

    def _trigger_classification(self, class_name, confidence):
        self.total_processed += 1
        if "fresh" in class_name:
            self.total_good += 1
        elif "rotten" in class_name:
            self.total_rejected += 1
        if class_name in self.counters:
            self.counters[class_name] += 1

        action_code = CLASS_DISPLAY.get(class_name, ("", (), "NONE"))[2]
        if action_code in ACTUATORS:
            ACTUATORS[action_code]["active_until"] = time.time() + 1.5
        display_name = CLASS_DISPLAY[class_name][0]
        timestamp = time.strftime("%H:%M:%S")
        self.event_log.append(
            f"[{timestamp}] +1 {display_name} ({confidence * 100:.1f}%) -> {action_code}"
        )

    def reset_counters(self):
        for key in self.counters:
            self.counters[key] = 0
        self.total_processed = 0
        self.total_good = 0
        self.total_rejected = 0
        self.event_log.clear()
        self.state = self.STATE_EMPTY
        self.history.clear()
