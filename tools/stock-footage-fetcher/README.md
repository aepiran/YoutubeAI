# Stock Footage Finder

Ứng dụng desktop tìm, chấm và tải stock video Pexels + Pixabay theo
`script_beat.csv`. Giao diện sử dụng phong cách dark dashboard tương tự
Footage Finder AI.

## Chạy giao diện

```powershell
cd D:\yt-src\TOOL-YOUTUBE
python .\stock-footage-fetcher\main.py
```

Bạn cũng có thể chạy `stock_footage_app.py` hoặc `run_gui.bat`.

`main.py` không có tham số sẽ mở GUI. Khi truyền các tham số như
`--project-dir`, file này vẫn chạy CLI Pexels cũ để giữ tương thích.

Trong ứng dụng:

1. Chọn thư mục project hoặc file `script_beat.csv`.
2. Mở Settings và nhập Pexels/Pixabay API key.
3. Bật Dry Run nếu muốn chỉ kiểm tra lựa chọn.
4. Bấm **Start Search**.
5. Xem queue, log và kết quả trong `selected-footage.json`.

Video được lưu trong thư mục `video` cạnh CSV.

## Build Windows

```powershell
cd D:\yt-src\TOOL-YOUTUBE\stock-footage-fetcher
.\build_windows.ps1
```

Hoặc chạy `build_windows.bat`.

File chạy được tạo tại:

```text
dist/DawnWithGod-FootageFinder/DawnWithGod-FootageFinder.exe
```

Bản build dùng `onedir` vì PySide6, PyTorch và Transformers có dung lượng lớn.
Executable có hai chế độ: GUI và worker nền, vì vậy máy sử dụng không cần cài
Python riêng.

Lần tìm đầu tiên cần Internet để tải model SigLIP. Model được lưu tại
`data/stock_footage_finder/model-cache` cạnh ứng dụng và được tái sử dụng cho
các lần chạy sau.

## Chạy CLI

```powershell
cd D:\yt-src\TOOL-YOUTUBE\stock-footage-fetcher
..\.venv\Scripts\python.exe .\multi_source.py `
  --project-dir "E:\NE\scripts\dawn-001"
```

## Định dạng CSV

```csv
ma_beat,y_chinh,tu_khoa,hinh_can_tim,tranh
```

Dùng dấu `|` phân cách các truy vấn thay thế trong `tu_khoa`.

CSV kế hoạch bổ sung do Footage Video Builder tạo có thể thêm các cột:

```csv
recommended_additional_files,target_downloaded_files,min_duration,missing_seconds,target_additional_seconds
```

`target_downloaded_files` và `min_duration` được áp dụng riêng cho từng Beat.
Kế hoạch bổ sung dùng manifest `.cache/stock-footage-supplement.json`, không
ghi đè manifest tải footage chính.

Xem thêm:

- [Hướng dẫn đa nguồn](docs/MULTI_SOURCE.md)
- [Prompt tạo CSV cho Dawn With God](PRAYER_SCRIPT_TO_FOOTAGE_CSV.md)

## Cài dependency

```powershell
cd D:\yt-src\TOOL-YOUTUBE
.\.venv\Scripts\python.exe -m pip install -r .\stock-footage-fetcher\requirements.txt
```

## Kiểm thử

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m unittest discover `
  -s .\stock-footage-fetcher -p "test*.py" -v
```
