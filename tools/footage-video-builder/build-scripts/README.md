# Build scripts

PyInstaller không thể cross-build. File Windows phải được tạo trên Windows; file
`.app` phải được tạo trực tiếp trên macOS.

`ft-video-builder.spec` tại thư mục gốc là cấu hình build duy nhất cho cả hai
nền tảng. Khi cần thêm asset, metadata hoặc hidden import, cập nhật file spec;
không thêm cờ PyInstaller riêng lẻ vào từng script.

## Windows

```powershell
.\build-scripts\build_windows.ps1 -Version 1.0.0 -InstallDependencies -Clean
```

Hoặc chạy wrapper:

```bat
build-scripts\build_windows.bat -Version 1.0.0 -Clean
```

Kết quả:

- `dist/windows/FootageVideoBuilder/FootageVideoBuilder.exe`
- `release/FootageVideoBuilder-1.0.0-windows-x64.zip`, hoặc
  `windows-arm64.zip` tùy kiến trúc máy build.

## macOS

```bash
chmod +x build-scripts/build_macos.sh
./build-scripts/build_macos.sh --version 1.0.0 --install-dependencies --clean
```

Kết quả phụ thuộc kiến trúc máy build:

- `dist/macos/FootageVideoBuilder.app`
- `release/FootageVideoBuilder-1.0.0-macos-arm64.zip`, hoặc `macos-x86_64.zip`

Muốn có icon chuẩn cho macOS, thêm
`assets/yt-vidbuilder.icns`. Nếu chưa có, ứng dụng vẫn build được với icon mặc
định. Script chưa ký số hoặc notarize ứng dụng.

## Nội dung package

- Entry point: `main.py` (UI mặc định, CLI khi có tham số).
- Tên ứng dụng/executable: `FootageVideoBuilder`.
- Dạng build: `onedir`, `windowed`, tắt UPX để ổn định với Torch/OpenCV.
- Bao gồm toàn bộ `assets`, metadata MoviePy/ImageIO/Transformers và các module
  động cần cho Whisper, CLIP, SigLIP/SigLIP 2 và keyring.
- Model Whisper/CLIP không đóng gói trọng số vào release; ứng dụng tiếp tục dùng
  cache/download theo cấu hình runtime.

## Tùy chọn

- Windows: `-SkipTests`, `-InstallDependencies`, `-Clean`.
- macOS: `--skip-tests`, `--install-dependencies`, `--clean`.
- Mặc định build dạng thư mục (`onedir`) để khởi động ổn định hơn với PySide6,
  Torch, Whisper và Transformers.
