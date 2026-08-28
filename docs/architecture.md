# Kiến trúc dự kiến

Pipeline hoàn chỉnh dự kiến:

```text
input/project.json
→ validate JSON và asset
→ tạo TTS
→ tự tính timeline
→ tạo scene và annotation
→ render animation
→ ghép audio/video
→ output/final.mp4
```

Phase hiện tại đã triển khai:

```text
input/project.json
→ validate JSON và asset
→ tạo TTS
→ tự tính timeline
→ tạo scene PNG và annotation
→ render whiteboard animation
→ ghép narration
→ ghép các scene
→ output/<projectId>/final.mp4
```

`scripts/validate_projects.py` đọc mọi file `.json` trực tiếp trong `input/`, kiểm tra cấu trúc project, quan hệ giữa segment và element, đồng thời xác minh asset ảnh nằm trong `assets/` và tồn tại.

`scripts/generate_tts.py` chỉ xử lý project vượt qua validation. Script gọi Kokoro service local cho từng `ttsText`, đo số frame thực tế của WAV, ghép audio theo scene và toàn project, thêm `sceneEndPaddingMs`, rồi ghi `timeline.json` và `subtitles.srt` có timestamp khớp với narration.

`scripts/build_scenes.py` đọc project và timeline, bố trí image/text trên canvas bằng layout deterministic, rồi tạo PNG hoàn chỉnh và annotation tương thích với renderer hiện tại.

`scripts/render_scenes.py` kiểm tra input của từng scene và gọi renderer hiện có với FPS của project, duration của timeline, chế độ `ink` rồi `color`, cùng hình bàn tay. Video được tạo riêng theo scene và chưa có narration.

`scripts/compose_video.py` dùng FFmpeg để chuẩn hóa duration/resolution/FPS, ghép scene WAV vào từng animation, rồi nối các scene theo thứ tự trong project. Kết quả cuối là H.264/AAC `yuv420p` tại `output/<projectId>/final.mp4`.
