"""
Fruit Detection, Classification & Vertical Line Counting Pipeline.

Hỗ trợ tự động 2 chế độ dựa theo loại model `best.pt`:
- Single-Stage Detection: dùng trực tiếp YOLO Detection (YOLO11n/YOLOv8 detect)
  để vừa tìm bounding box vừa phân loại loại quả & tươi/hỏng.
- Two-Stage Pipeline: dùng YOLOv8-detect tìm box + YOLOv8-cls phân loại theo batch.
"""

import math
import cv2
import numpy as np
import torch
from ultralytics import YOLO

try:
    torch.set_num_threads(4)
except Exception:
    pass


class FruitTracker2Stage:
    def __init__(
        self,
        cls_model_path="best.pt",
        det_model_path="yolov8n.pt",
        counting_line_ratio=0.50,
        line_orientation="vertical",
        cls_model=None,
    ):
        self.cls_model = cls_model if cls_model is not None else YOLO(cls_model_path)
        self.is_single_stage = getattr(self.cls_model, "task", None) == "detect"
        self.det_model = None if self.is_single_stage else YOLO(det_model_path)

        # Class COCO hoa quả cho chế độ Two-Stage: Chuối (46), Táo (47), Cam (49)
        self.target_coco_classes = [46, 47, 49]

        self.counting_line_ratio = counting_line_ratio
        self.line_orientation = line_orientation

        # Tham số phát hiện & lọc nhiễu
        self.det_conf_thresh = 0.35 if self.is_single_stage else 0.40
        self.cls_conf_thresh = 0.50 if self.is_single_stage else 0.65
        self.detection_imgsz = 640 if self.is_single_stage else 320
        self.classification_samples = 4 if self.is_single_stage else 2
        self.model_score_weight = 0.88 if self.is_single_stage else 0.82
        self.visual_defect_weight = 0.12 if self.is_single_stage else 0.18
        self.reject_bias = 1.08 if self.is_single_stage else 1.10
        self.box_padding_ratio = 0.04 if self.is_single_stage else 0.06
        self.nms_overlap_thresh = 0.35 if self.is_single_stage else 0.30
        self.min_box_area = 1200

        # Hiển thị & hướng băng chuyền
        self.hide_box_after_line = True
        self.flow_direction = "left_to_right"

        # Centroid Tracker
        self.next_track_id = 1
        self.tracks = {}
        self.max_lost_frames = 12

        # Thống kê đếm sản lượng (chỉ phân loại Quả Lành / Quả Hỏng)
        self.count_fresh = 0
        self.count_rotten = 0
        self.total_counted = 0
        self.recent_events = []
        self.pending_rejections = []
        self.recent_event_records = []
        self.counts_by_fruit = {"fruit": {"good": 0, "rejected": 0}}

    # ------------------------------------------------------------------
    # Helpers dùng chung
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_class_info(raw_name):
        """Phân tích tên class dạng fresh_apple / rotten_banana / freshapples..."""
        lower = str(raw_name or "").strip().lower()
        is_rotten = any(tok in lower for tok in ("rotten", "bad", "hong"))
        is_fresh = not is_rotten

        if "apple" in lower:
            fruit_type = "apple"
        elif "orange" in lower:
            fruit_type = "orange"
        elif "banana" in lower:
            fruit_type = "banana"
        else:
            fruit_type = "fruit"
        return is_fresh, fruit_type

    def _is_past_line(self, cx, line_x, margin=0):
        if self.flow_direction == "left_to_right":
            return cx >= (line_x + margin)
        return cx <= (line_x - margin)

    def _update_flow_direction(self, tracks):
        dx_vals = [
            tdata["history"][-1][0] - tdata["history"][-2][0]
            for tdata in tracks.values()
            if len(tdata["history"]) >= 2
        ]
        if len(dx_vals) >= 3:
            avg_dx = sum(dx_vals) / len(dx_vals)
            if avg_dx > 0.8:
                self.flow_direction = "left_to_right"
            elif avg_dx < -0.8:
                self.flow_direction = "right_to_left"

    def _match_tracks(self, bboxes, max_dist):
        """Khớp các track hiện có với danh sách bbox mới theo khoảng cách tâm."""
        matches = {}
        matched_indices = set()
        for tid, tdata in self.tracks.items():
            pcx, pcy = tdata["centroid"]
            best_idx = -1
            min_dist = float("inf")
            for idx, b in enumerate(bboxes):
                if idx in matched_indices:
                    continue
                bcx = int((b[0] + b[2]) / 2)
                bcy = int((b[1] + b[3]) / 2)
                dist = math.hypot(bcx - pcx, bcy - pcy)
                if dist < max_dist and dist < min_dist:
                    min_dist = dist
                    best_idx = idx
            if best_idx != -1:
                matched_indices.add(best_idx)
                matches[tid] = best_idx
        return matches, matched_indices

    def _create_track(self, bbox, line_x, is_fresh=True, conf=0.85,
                      fruit_type="fruit", initial_classified=0):
        cx = int((bbox[0] + bbox[2]) / 2)
        cy = int((bbox[1] + bbox[3]) / 2)
        already_past = self._is_past_line(cx, line_x, margin=10)
        return {
            "centroid": (cx, cy),
            "bbox": tuple(bbox),
            "is_fresh": is_fresh,
            "label": "QUA LANH" if is_fresh else "QUA HONG",
            "conf": float(conf),
            "counted": already_past,
            "already_past": already_past,
            "classified_count": initial_classified if already_past else 0,
            "fresh_score_sum": 0.0,
            "rotten_score_sum": 0.0,
            "fruit_type": fruit_type,
            "fruit_votes": {},
            "history": [(cx, cy)],
            "lost": 0,
        }

    def _compute_visual_defect(self, frame, bbox):
        """Tính tỷ lệ vùng thâm/nâu trên bề mặt quả (bỏ viền 8% để giảm nhiễu nền)."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if crop.shape[0] < 16 or crop.shape[1] < 16:
            return 0.0
        hsv_c = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        ch, cw = hsv_c.shape[:2]
        mx, my = max(1, int(cw * 0.08)), max(1, int(ch * 0.08))
        roi = hsv_c[my:max(my + 1, ch - my), mx:max(mx + 1, cw - mx)]
        dark_mask = cv2.inRange(roi, (0, 35, 0), (180, 255, 68))
        brown_mask = cv2.inRange(roi, (4, 45, 25), (28, 255, 190))
        defect_mask = cv2.bitwise_or(dark_mask, brown_mask)
        defect_ratio = float(np.count_nonzero(defect_mask)) / max(1, defect_mask.size)
        return float(np.clip((defect_ratio - 0.04) / 0.20, 0.0, 1.0))

    def _apply_quality_vote(
        self,
        tdata,
        prob_fresh,
        prob_rotten,
        visual_defect,
        fruit_type=None,
        fruit_conf=0.0,
        force_rotten=False,
    ):
        """Cộng dồn điểm đánh giá tươi/hỏng đa khung hình và cập nhật trạng thái track."""
        model_w = self.model_score_weight
        visual_w = self.visual_defect_weight
        combined_rotten = (model_w * prob_rotten + visual_w * visual_defect) * self.reject_bias
        combined_fresh = model_w * prob_fresh + visual_w * (1.0 - visual_defect)

        tdata["visual_defect"] = visual_defect
        tdata["fresh_score_sum"] = tdata.get("fresh_score_sum", 0.0) + combined_fresh
        tdata["rotten_score_sum"] = tdata.get("rotten_score_sum", 0.0) + combined_rotten

        if fruit_type:
            votes = tdata.setdefault("fruit_votes", {})
            votes[fruit_type] = votes.get(fruit_type, 0.0) + max(0.01, float(fruit_conf))
            tdata["fruit_type"] = max(votes.items(), key=lambda kv: kv[1])[0]

        prev_count = tdata.get("classified_count", 0)
        new_count = prev_count + 1
        fresh_score = tdata["fresh_score_sum"]
        rotten_score = tdata["rotten_score_sum"]

        if rotten_score > fresh_score or (prev_count == 0 and force_rotten):
            tdata["is_fresh"] = False
            tdata["label"] = "QUA HONG"
            tdata["conf"] = min(1.0, rotten_score / new_count)
        else:
            tdata["is_fresh"] = True
            tdata["label"] = "QUA LANH"
            tdata["conf"] = min(1.0, fresh_score / new_count)

        tdata["classified_count"] = new_count

    # ------------------------------------------------------------------
    # Chế độ Single-Stage Detection (best.pt task == 'detect')
    # ------------------------------------------------------------------
    def _detect_single_stage(self, frame):
        h, w = frame.shape[:2]
        raw_dets = []
        try:
            det_res = self.cls_model(
                frame,
                imgsz=self.detection_imgsz,
                conf=self.det_conf_thresh,
                iou=self.nms_overlap_thresh,
                verbose=False,
            )[0]
            if det_res.boxes is None or len(det_res.boxes) == 0:
                return []

            names = det_res.names or self.cls_model.names
            for box in det_res.boxes:
                b = box.xyxy[0].cpu().numpy().astype(int)
                bw, bh = b[2] - b[0], b[3] - b[1]
                if bw > 24 and bh > 24 and bw * bh >= self.min_box_area and bw < w * 0.85 and bh < h * 0.85:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    cname = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(names[cls_id])
                    is_fresh, fruit_type = self._parse_class_info(cname)
                    raw_dets.append({
                        "bbox": [max(0, int(b[0])), max(0, int(b[1])), min(w, int(b[2])), min(h, int(b[3]))],
                        "conf": conf,
                        "is_fresh": is_fresh,
                        "fruit_type": fruit_type,
                    })
        except Exception:
            return []

        if len(raw_dets) <= 1:
            return raw_dets

        # Class-agnostic NMS ưu tiên box có confidence cao nhất
        raw_dets.sort(key=lambda d: d["conf"], reverse=True)
        kept = []
        for det in raw_dets:
            x1, y1, x2, y2 = det["bbox"]
            area_a = max(1, (x2 - x1) * (y2 - y1))
            overlaps = False
            for k in kept:
                kx1, ky1, kx2, ky2 = k["bbox"]
                inter = max(0, min(x2, kx2) - max(x1, kx1)) * max(0, min(y2, ky2) - max(y1, ky1))
                area_b = max(1, (kx2 - kx1) * (ky2 - ky1))
                iou = inter / float(area_a + area_b - inter)
                ioa = inter / float(min(area_a, area_b))
                if iou > self.nms_overlap_thresh or ioa > 0.65:
                    overlaps = True
                    break
            if not overlaps:
                kept.append(det)
        return kept

    def _vote_single_stage(self, tdata, det, frame):
        conf = float(det["conf"])
        is_fresh = bool(det["is_fresh"])
        prob_fresh = conf if is_fresh else (1.0 - conf) * 0.35
        prob_rotten = conf if not is_fresh else (1.0 - conf) * 0.35
        visual_defect = self._compute_visual_defect(frame, det["bbox"])
        self._apply_quality_vote(
            tdata,
            prob_fresh=prob_fresh,
            prob_rotten=prob_rotten,
            visual_defect=visual_defect,
            fruit_type=det["fruit_type"],
            fruit_conf=conf,
        )

    def _update_single_stage(self, frame):
        h, w = frame.shape[:2]
        detections = self._detect_single_stage(frame)
        bboxes = [d["bbox"] for d in detections]
        line_x = int(w * self.counting_line_ratio)

        matches, matched_indices = self._match_tracks(bboxes, max_dist=75)
        updated_tracks = {}

        for tid, tdata in list(self.tracks.items()):
            if tid in matches:
                det = detections[matches[tid]]
                b = det["bbox"]
                cx, cy = int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2)
                tdata["centroid"] = (cx, cy)
                tdata["bbox"] = tuple(b)
                tdata["history"].append((cx, cy))
                if len(tdata["history"]) > 15:
                    tdata["history"].pop(0)

                if (not self._is_past_line(cx, line_x)
                        and not tdata.get("counted", False)
                        and tdata.get("classified_count", 0) < max(2, self.classification_samples)):
                    self._vote_single_stage(tdata, det, frame)

                self._check_line_crossing(tid, tdata, h, w)
                tdata["lost"] = 0
                updated_tracks[tid] = tdata
            else:
                tdata["lost"] = tdata.get("lost", 0) + 1
                if tdata["lost"] < self.max_lost_frames:
                    updated_tracks[tid] = tdata

        self._update_flow_direction(updated_tracks)

        for d_idx, det in enumerate(detections):
            if d_idx in matched_indices:
                continue
            nid = self.next_track_id
            self.next_track_id += 1
            tdata = self._create_track(
                det["bbox"],
                line_x=line_x,
                is_fresh=det["is_fresh"],
                conf=det["conf"],
                fruit_type=det["fruit_type"],
            )
            if not tdata["already_past"]:
                self._vote_single_stage(tdata, det, frame)
            updated_tracks[nid] = tdata

        self.tracks = updated_tracks
        return self.tracks

    # ------------------------------------------------------------------
    # Chế độ Two-Stage (fallback nếu best.pt là model Classification)
    # ------------------------------------------------------------------
    def detect_candidate_boxes(self, frame):
        h, w = frame.shape[:2]
        boxes = []

        try:
            det_res = self.det_model(
                frame, imgsz=self.detection_imgsz,
                conf=self.det_conf_thresh, verbose=False,
            )[0]
            for box in det_res.boxes:
                if int(box.cls[0]) in self.target_coco_classes:
                    b = box.xyxy[0].cpu().numpy().astype(int)
                    bw, bh = b[2] - b[0], b[3] - b[1]
                    if bw > 30 and bh > 30 and bw * bh >= self.min_box_area and bw < w * 0.75 and bh < h * 0.75:
                        boxes.append(self._expand_box(b, w, h))
        except Exception:
            pass

        # Quét bổ trợ bằng phân đoạn màu HSV khi YOLO chưa bắt được quả nào
        if not boxes:
            f_small = frame[::2, ::2]
            hsv_s = cv2.cvtColor(f_small, cv2.COLOR_BGR2HSV)
            m1 = cv2.inRange(hsv_s, (0, 70, 70), (30, 255, 255))
            m2 = cv2.inRange(hsv_s, (165, 70, 70), (180, 255, 255))
            m3 = cv2.inRange(hsv_s, (35, 70, 70), (85, 255, 255))
            dist_s = cv2.distanceTransform(m1 | m2 | m3, cv2.DIST_L2, 3)
            if dist_s.max() > 0:
                _, sure_fg = cv2.threshold(dist_s, 0.40 * dist_s.max(), 255, 0)
                nl, _, stats, centroids = cv2.connectedComponentsWithStats(np.uint8(sure_fg))
                for i in range(1, nl):
                    if stats[i, cv2.CC_STAT_AREA] > 150:
                        cx, cy = int(centroids[i][0] * 2), int(centroids[i][1] * 2)
                        peak = dist_s[int(centroids[i][1]), int(centroids[i][0])]
                        r = int(max(28, min(85, peak * 3.5)))
                        if (2 * r) ** 2 >= self.min_box_area:
                            boxes.append([max(0, cx - r), max(0, cy - r), min(w, cx + r), min(h, cy + r)])

        if not boxes:
            return []
        return self._fast_nms(np.array(boxes), overlapThresh=self.nms_overlap_thresh)

    def _expand_box(self, box, frame_w, frame_h):
        x1, y1, x2, y2 = [int(v) for v in box]
        pad_x = max(3, int((x2 - x1) * self.box_padding_ratio))
        pad_y = max(3, int((y2 - y1) * self.box_padding_ratio))
        return [max(0, x1 - pad_x), max(0, y1 - pad_y), min(frame_w, x2 + pad_x), min(frame_h, y2 + pad_y)]

    def _fast_nms(self, boxes, overlapThresh=0.40):
        if len(boxes) == 0:
            return []
        if boxes.dtype.kind == "i":
            boxes = boxes.astype("float")

        pick = []
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        idxs = np.argsort(y2)

        while len(idxs) > 0:
            last = len(idxs) - 1
            i = idxs[last]
            pick.append(i)
            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])
            w_ = np.maximum(0, xx2 - xx1 + 1)
            h_ = np.maximum(0, yy2 - yy1 + 1)
            overlap = (w_ * h_) / area[idxs[:last]]
            idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlapThresh)[0])))

        return boxes[pick].astype("int")

    def _update_two_stage(self, frame):
        h, w = frame.shape[:2]
        clean_boxes = self.detect_candidate_boxes(frame)
        line_x = int(w * self.counting_line_ratio)

        matches, matched_indices = self._match_tracks(clean_boxes, max_dist=65)
        updated_tracks = {}
        crops_to_classify = []
        crop_target_ids = []

        for tid, tdata in list(self.tracks.items()):
            if tid in matches:
                b = clean_boxes[matches[tid]]
                cx, cy = int((b[0] + b[2]) / 2), int((b[1] + b[3]) / 2)
                tdata["centroid"] = (cx, cy)
                tdata["bbox"] = tuple(b)
                tdata["history"].append((cx, cy))
                if len(tdata["history"]) > 15:
                    tdata["history"].pop(0)

                if (not self._is_past_line(cx, line_x)
                        and not tdata.get("counted", False)
                        and tdata.get("classified_count", 0) < self.classification_samples):
                    crop = frame[max(0, b[1]):min(h, b[3]), max(0, b[0]):min(w, b[2])]
                    if crop.shape[0] > 15 and crop.shape[1] > 15:
                        crops_to_classify.append(crop)
                        crop_target_ids.append(tid)

                self._check_line_crossing(tid, tdata, h, w)
                tdata["lost"] = 0
                updated_tracks[tid] = tdata
            else:
                tdata["lost"] = tdata.get("lost", 0) + 1
                if tdata["lost"] < self.max_lost_frames:
                    updated_tracks[tid] = tdata

        self._update_flow_direction(updated_tracks)

        for b_idx, b in enumerate(clean_boxes):
            if b_idx in matched_indices:
                continue
            nid = self.next_track_id
            self.next_track_id += 1
            tdata = self._create_track(b, line_x=line_x, initial_classified=2)
            updated_tracks[nid] = tdata
            if not tdata["already_past"]:
                crop = frame[max(0, b[1]):min(h, b[3]), max(0, b[0]):min(w, b[2])]
                if crop.shape[0] > 15 and crop.shape[1] > 15:
                    crops_to_classify.append(crop)
                    crop_target_ids.append(nid)

        if crops_to_classify:
            batch_res = self.cls_model(crops_to_classify, verbose=False)
            for tid, res in zip(crop_target_ids, batch_res):
                if tid not in updated_tracks:
                    continue
                probs = res.probs.data.cpu().numpy()
                prob_empty = float(probs[0])
                prob_fresh = float(probs[1] + probs[2] + probs[3])
                prob_rotten = float(probs[4] + probs[5] + probs[6])

                if prob_empty > 0.45 or (prob_fresh + prob_rotten) < self.cls_conf_thresh:
                    del updated_tracks[tid]
                    continue

                visual_defect = self._compute_visual_defect(frame, updated_tracks[tid]["bbox"])
                top1_name = self.cls_model.names[int(res.probs.top1)]
                self._apply_quality_vote(
                    updated_tracks[tid],
                    prob_fresh=prob_fresh,
                    prob_rotten=prob_rotten,
                    visual_defect=visual_defect,
                    force_rotten="rotten" in top1_name,
                )

        self.tracks = updated_tracks
        return self.tracks

    # ------------------------------------------------------------------
    # API chính: update / counting / visualization / reset
    # ------------------------------------------------------------------
    def update(self, frame):
        if self.is_single_stage:
            return self._update_single_stage(frame)
        return self._update_two_stage(frame)

    def _check_line_crossing(self, track_id, track_data, h, w):
        if track_data["counted"] or len(track_data["history"]) < 2:
            return

        prev_x = track_data["history"][-2][0]
        curr_x = track_data["history"][-1][0]
        line_x = int(w * self.counting_line_ratio)

        if (prev_x <= line_x <= curr_x) or (prev_x >= line_x >= curr_x):
            track_data["counted"] = True
            self.total_counted += 1
            fruit_type = "fruit"
            fruit_display = "QUA"
            quality = "good" if track_data["is_fresh"] else "rejected"
            self.counts_by_fruit["fruit"][quality] += 1

            if track_data["is_fresh"]:
                self.count_fresh += 1
                self.recent_events.append(f"#{track_id}: +1 {fruit_display} DAT")
            else:
                self.count_rotten += 1
                self.recent_events.append(f"#{track_id}: +1 {fruit_display} HONG [LOAI]")
                self.pending_rejections.append({
                    "track_id": track_id,
                    "bbox": tuple(track_data["bbox"]),
                    "confidence": float(track_data.get("conf", 0.0)),
                    "fruit_type": fruit_type,
                    "visual_defect": float(track_data.get("visual_defect", 0.0)),
                })

            self.recent_event_records.append({
                "track_id": track_id,
                "fruit_type": fruit_type,
                "quality": quality,
                "confidence": float(track_data.get("conf", 0.0)),
                "event": self.recent_events[-1],
            })

            if len(self.recent_events) > 8:
                self.recent_events.pop(0)
            if len(self.recent_event_records) > 20:
                self.recent_event_records.pop(0)

    def draw_visualization(self, frame):
        out = frame.copy()
        h, w = out.shape[:2]

        # 1. Vạch đếm dọc
        line_x = int(w * self.counting_line_ratio)
        cv2.line(out, (line_x, 0), (line_x, h), (0, 215, 255), 2)
        cv2.putText(out, "VACH DEM DOC", (line_x + 6, h // 2 - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 215, 255), 2)
        cv2.putText(out, "(COUNTING)", (line_x + 6, h // 2 + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1)

        # 2. Bounding box & nhãn từng quả
        for track_id, track_data in self.tracks.items():
            cx, cy = track_data["centroid"]
            if self.hide_box_after_line:
                if (track_data.get("counted", False)
                        or track_data.get("already_past", False)
                        or self._is_past_line(cx, line_x)):
                    continue

            x1, y1, x2, y2 = track_data["bbox"]
            is_fresh = track_data["is_fresh"]
            label_text = f"#{track_id} {'LANH' if is_fresh else 'HONG'}"

            box_color = (0, 255, 60) if is_fresh else (20, 30, 255)
            cv2.rectangle(out, (x1, y1), (x2, y2), box_color, 2)
            (tw, _), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 2)
            cv2.rectangle(out, (x1, max(0, y1 - 20)), (x1 + tw + 8, y1), box_color, -1)
            cv2.putText(out, label_text, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 2)
            cv2.circle(out, (cx, cy), 4, (0, 255, 255), -1)

        # 3. HUD bộ đếm sản lượng
        hud_w, hud_h = 340, 105
        overlay = out.copy()
        cv2.rectangle(overlay, (10, 10), (10 + hud_w, 10 + hud_h), (18, 20, 24), -1)
        cv2.addWeighted(overlay, 0.82, out, 0.18, 0, out)
        cv2.rectangle(out, (10, 10), (10 + hud_w, 10 + hud_h), (0, 215, 255), 1)

        hud_title = (
            "BO DEM SAN LUONG (YOLO11 DETECT)"
            if self.is_single_stage
            else "BO DEM SAN LUONG (TWO-STAGE AI)"
        )
        cv2.putText(out, hud_title, (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 215, 255), 2)
        cv2.putText(out, f"QUA LANH (TUOI):  {self.count_fresh}", (20, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (50, 255, 80), 2)
        cv2.putText(out, f"QUA HONG (LOAI): {self.count_rotten}", (20, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (30, 60, 255), 2)

        defect_pct = (self.count_rotten / self.total_counted * 100) if self.total_counted > 0 else 0.0
        cv2.putText(
            out,
            f"Tong: {self.total_counted} | Ty le hong: {defect_pct:.1f}%",
            (20, 104),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (220, 220, 220),
            1,
        )
        return out

    def reset_counts(self):
        self.count_fresh = 0
        self.count_rotten = 0
        self.total_counted = 0
        self.recent_events.clear()
        self.pending_rejections.clear()
        self.recent_event_records.clear()
        for counts in self.counts_by_fruit.values():
            counts["good"] = 0
            counts["rejected"] = 0
        self.tracks.clear()
