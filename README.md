# FruitGuard AI

Hệ thống phân loại nông sản bằng thị giác máy tính, gồm:

- GUI Desktop điều khiển webcam/video và chạy AI.
- FastAPI + React chỉ đọc log để hiển thị dashboard.
- Phân loại nhị phân: **Quả lành — Đạt** và **Quả hỏng — Loại**.
- Lưu lịch sử từng phiên, ảnh bằng chứng, ảnh giải thích quyết định AI và báo cáo cuối phiên.

## Chạy triển lãm

Nhấp đúp `CHAY_TRIEN_LAM_AN_TOAN.bat`.

Launcher sẽ kiểm tra model, thư viện, video mẫu và webcam; khởi động dashboard; sau đó mở GUI. Nếu webcam không dùng được, GUI tự chuyển sang video mẫu.

## Chạy từng thành phần

- `CHAY_GIAO_DIEN_GUI.bat`: chỉ mở GUI vận hành.
- `CHAY_WEB_DASHBOARD.bat`: build React và mở dashboard tại `http://127.0.0.1:8000`.

GUI là thành phần duy nhất được phép mở webcam/video và chạy pipeline YOLO. Dashboard không điều khiển camera hoặc quá trình nhận diện.

## File chính

- `app_gui.py`: giao diện và luồng vận hành.
- `conveyor_bbox_detector.py`: nhận diện, theo dõi và phân loại lành/hỏng.
- `conveyor_core.py`: trạng thái phân loại và Eigen-CAM dùng chung.
- `api_server.py`: API chỉ đọc log và phục vụ React.
- `report_generator.py`: tạo báo cáo HTML cuối phiên.
- `exhibition_launcher.py`: kiểm tra và khởi động chế độ triển lãm an toàn.
- `arduino_conveyor_controller.ino`: chương trình điều khiển phần cứng.

## Dữ liệu sinh ra

- `output/production_log.jsonl`: lịch sử sự kiện.
- `output/dashboard_state.json`: trạng thái gần nhất.
- `output/rejected_products/`: ảnh sản phẩm bị loại.
- `output/explanations/`: ảnh giải thích quyết định AI.
- `output/reports/`: báo cáo cuối phiên.

Không xóa thư mục `output` nếu muốn giữ lịch sử triển lãm.
