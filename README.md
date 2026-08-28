# SRT 白板动画 Skill

将 SRT 字幕转为按叙事顺序绘制的白板手绘视频Skill。它结合了**分区遮罩编排**与**流式笔迹绘制**：每个元素跟随字幕依次出场，笔尖在区域内连续落墨，再逐步添彩，最终导出 MP4。

适合把知识讲解、故事口播、课程字幕或短视频文案制作成暖米黄色纸张底的手绘动画。

## Hướng dẫn nhanh

### 1. Chuẩn bị project và asset

Mỗi video cần một file JSON trong `input/` và các ảnh được tham chiếu trong `assets/`:

```text
input/
└── inflation-explained.json

assets/
├── drawing-hand.png
├── inflation/
│   ├── shopper.png
│   └── grocery-basket.png
└── common/
    └── arrow-up.png
```

Asset nên là PNG nền trong suốt, được cắt sát nội dung và có đủ độ phân giải cho video đầu ra. `assets/drawing-hand.png` là hình bàn tay dùng chung khi render.

Trong project JSON:

- `scenes[].segments[].ttsText` là lời thuyết minh.
- `segments[].elementIds` liệt kê các element xuất hiện trong segment; ID phải tồn tại trong `scenes[].elements`.
- Element `type: "image"` phải có `asset`, ví dụ `assets/inflation/shopper.png`. Chỉ dùng đường dẫn tương đối bắt đầu bằng `assets/`; không dùng đường dẫn tuyệt đối hoặc `..`.
- Element `type: "text"` phải có `content`.
- `position` hỗ trợ lưới 3×3: `top-left`, `top-center`, `top-right`, `left`, `center`, `right`, `bottom-left`, `bottom-center`, `bottom-right`.
- `size` nhận `small`, `medium` hoặc `large`; `sequence` quyết định thứ tự vẽ.

Kiểm tra input trước khi render:

```powershell
python scripts/validate_projects.py
```

### 2. Chuẩn bị môi trường

Trên Windows, tạo môi trường và cài dependency renderer:

```powershell
python scripts/prepare_env.py
.\.venv\Scripts\Activate.ps1
python -m pip install -e services/kokoro/kokoro
```

Cài FFmpeg và mở terminal mới sau khi cài:

```powershell
winget install Gyan.FFmpeg
ffmpeg -version
```

Kokoro có thể cần `espeak-ng` cho English fallback và một số ngôn ngữ.

### 3. Chạy

Terminal thứ nhất, kích hoạt môi trường và giữ Kokoro service tiếp tục chạy:

```powershell
.\.venv\Scripts\Activate.ps1
python services/kokoro/service.py
```

Terminal thứ hai, kích hoạt cùng môi trường và chạy toàn bộ pipeline:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_pipeline.py input/inflation-explained.json
```

Runner log `[START]`, `[OK]` hoặc `[FAILED]` cho từng bước. Video hoàn chỉnh được ghi tại:

```text
output/inflation-explained/final.mp4
```

## 效果示例

**场景：猴子山抢香蕉** —— 随着字幕的叙事顺序，依次绘制假山与小猴、抢香蕉的大猴，以及围观小朋友。

![猴子山抢香蕉：SRT 白板动画演示](examples/scene-01-monkey-mountain-stream.gif)

原始线稿：[查看 PNG](examples/scene-01-monkey-mountain.png)。

## 核心能力

- 解析 SRT 字幕，并按建议的 25–35 秒时长拆分场景
- 先输出分镜与配图策略，确保每一幕只表达一个核心意思
- 按字幕事件而非画面坐标，为元素建立语义化的绘制顺序
- 用 `annotation.json` 管理区域、时序、字幕关联和重叠保护区
- 每个区域采用连续流式笔迹：先 `ink` 铺线稿，再 `color` 添彩
- 支持浏览器预览台调整区域、顺序、时间和字幕关联
- 支持逐幕渲染与多幕合并，输出完整 MP4

## 工作方式

该 Skill 的关键在于“字幕驱动、逐步确认”。每一步完成后都等待确认，避免在分镜、线稿或标注尚未定稿时浪费渲染成本：

1. 解析 SRT，输出分镜与配图策略。
2. 确认后生成统一风格的线稿。
3. 确认线稿后，结合字幕和原图创建标注，并载入预览台。
4. 确认标注后，生成分区与方向检查图。
5. 在预览台调整区域、叙事顺序、时序和字幕关联并保存。
6. 确认最终标注后，逐幕渲染 MP4。
7. 多幕项目在确认各幕成片后合并。

## 视觉规范

- 暖米黄色纸张背景：建议 `#F5EBD7`
- 深灰色素描线条，红、橙、蓝仅作少量概念性点缀
- 极简手绘、干净背景与充足留白
- 不使用场景文字、标签、摄影感、3D 效果或复杂纹理

## 安装与环境

Skill 自带独立的 Python 虚拟环境准备脚本。首次运行时执行：

```bash
python scripts/prepare_env.py --check
python scripts/prepare_env.py
```

成功后第一条命令会输出 `ENV_PY=<路径>`；后续渲染请使用该解释器，确保依赖隔离。

## 项目素材结构

### Project JSON đầu vào

Đặt một hoặc nhiều project JSON và các ảnh được tham chiếu theo cấu trúc:

```text
input/
└── inflation.json

assets/
├── inflation/
│   ├── shopper.png
│   └── grocery-basket.png
└── common/
    └── arrow-up.png
```

Mỗi `input/*.json` có cấu trúc bắt buộc sau:

```json
{
  "projectId": "inflation-explained",
  "title": "How Inflation Shrinks Your Money",
  "resolution": { "width": 1920, "height": 1080 },
  "fps": 30,
  "voice": { "id": "af_heart", "speed": 0.95 },
  "timing": {
    "sceneEndPaddingMs": 500,
    "completedSceneHoldMs": 500,
    "minimumElementDurationMs": 800
  },
  "scenes": [
    {
      "id": "scene-01",
      "segments": [
        {
          "id": "segment-01",
          "ttsText": "Imagine that you have one hundred dollars.",
          "elementIds": ["shopper", "money-label"]
        }
      ],
      "elements": [
        {
          "id": "shopper",
          "type": "image",
          "asset": "assets/inflation/shopper.png",
          "position": "left",
          "size": "large",
          "sequence": 1
        },
        {
          "id": "money-label",
          "type": "text",
          "content": "$100 today",
          "position": "center",
          "size": "medium",
          "sequence": 2
        }
      ]
    }
  ]
}
```

- `segments[].ttsText` là lời đọc dùng để tạo TTS ở phase sau.
- `elements[].content` là text hiển thị trên video và bắt buộc với element `type: "text"`.
- `segments[].elementIds` xác định các element xuất hiện theo segment; mỗi ID phải tồn tại trong `elements` của cùng scene.
- `elements[].asset` là đường dẫn ảnh và bắt buộc với element `type: "image"`. Đường dẫn phải bắt đầu bằng `assets/`, phải tồn tại, không được là absolute path và không được chứa `..`.

Chạy validation từ thư mục gốc của repo:

```bash
python scripts/validate_projects.py
```

Script tự quét mọi file `.json` trực tiếp trong `input/`. File hợp lệ chỉ in `[VALID] <filename>`; file không hợp lệ in `[INVALID] <filename>`, JSON path và nguyên nhân lỗi. Validation không tạo file hay thư mục output.

### Chạy toàn bộ pipeline bằng một lệnh

Sau khi Kokoro service đã chạy, validate input, tạo TTS, build scene, render và ghép video bằng:

```bash
python scripts/run_pipeline.py input/inflation-explained.json
```

Runner log trạng thái `[START]`, `[OK]` hoặc `[FAILED]` cho từng bước và dừng ngay khi có lỗi. Bỏ tham số project để xử lý tất cả file JSON trong `input/`.

### Tạo giọng đọc bằng Kokoro local

Source Kokoro chính thức được clone tại `services/kokoro/kokoro`. Cài source và dependency vào Python environment đang dùng:

```bash
python -m pip install -e services/kokoro/kokoro
```

Kokoro dùng `espeak-ng` cho English fallback và một số ngôn ngữ. Trên Windows, cài `espeak-ng` từ trang release chính thức; trên Ubuntu/Debian chạy `sudo apt-get install espeak-ng`.

Khởi động Kokoro service local ở terminal riêng:

```bash
python services/kokoro/service.py
```

Service lắng nghe tại `http://127.0.0.1:8880`. Lần tổng hợp đầu tiên có thể tải model Kokoro về máy. Nếu Kokoro chưa được cài, service dừng và in đúng command cài đặt; pipeline không tự chuyển sang provider hoặc voice khác.

Ở terminal khác, xử lý tất cả project JSON hợp lệ trong `input/`:

```bash
python scripts/generate_tts.py
```

Hoặc chỉ xử lý một project:

```bash
python scripts/generate_tts.py input/inflation.json
```

Mỗi segment dùng `scenes[].segments[].ttsText`, cùng `voice.id` và `voice.speed` trong project. Timestamp được tính từ số frame WAV thực tế. `sceneEndPaddingMs` được thêm vào cuối từng scene. Output có cấu trúc:

```text
output/<projectId>/
├── timeline.json
└── audio/
    ├── narration.wav
    ├── <sceneId>.wav
    └── <sceneId>/
        └── <segmentId>.wav
```

`timeline.json` chứa thời gian bắt đầu/kết thúc/duration của project, scene và segment theo millisecond. Nếu một `ttsText` rỗng hoặc Kokoro lỗi, toàn project đó dừng, báo rõ `<sceneId>/<segmentId>` và không publish output mới.

### Tạo scene PNG và annotation

Scene builder cần Pillow:

```bash
python -m pip install Pillow
```

Sau khi project đã có đầy đủ `timeline.json` và audio từ bước TTS, xử lý tất cả project trong `input/`:

```bash
python scripts/build_scenes.py
```

Hoặc xử lý một project:

```bash
python scripts/build_scenes.py input/inflation.json
```

Builder đọc asset `image`, render `content` của element `text`, và chuyển `position`/`size` thành pixel bằng layout 3×3 cố định. Vùng dưới 15% canvas được chừa cho phụ đề. Các element cùng position được chia thành các slot theo `sequence`, không dùng AI hay tọa độ ngẫu nhiên.

Output bổ sung:

```text
output/<projectId>/scenes/
├── <sceneId>.png
└── <sceneId>.annotation.json
```

Annotation dùng bounding box thực tế, thứ tự `elements[].sequence` và timing segment từ `timeline.json`. `completedSceneHoldMs` được chừa ở cuối scene; builder dừng project và báo lỗi nếu thiếu timeline, narration, scene/segment WAV hoặc asset.

### Render whiteboard animation theo scene

Sau khi đã tạo scene PNG và annotation, render tất cả project:

```bash
python scripts/render_scenes.py
```

Hoặc render một project:

```bash
python scripts/render_scenes.py input/inflation.json
```

Command tái sử dụng `render_stream_whiteboard.py`, truyền FPS từ project và duration từ timeline, sau đó render `ink` rồi `color` với hình bàn tay `assets/drawing-hand.png`. Mỗi scene tạo:

```text
output/<projectId>/scenes/<sceneId>-whiteboard.mp4
```

Video chưa ghép narration. Scene được bỏ qua nếu video hiện có mới hơn cả PNG và annotation; thay đổi một trong hai input sẽ render lại scene đó.

### Ghép narration và video hoàn chỉnh

Composer yêu cầu FFmpeg có trong `PATH`. Sau khi cài, kiểm tra:

```bash
ffmpeg -version
```

Ghép tất cả project trong `input/`:

```bash
python scripts/compose_video.py
```

Hoặc ghép một project:

```bash
python scripts/compose_video.py input/inflation.json
```

Mỗi scene được chuẩn hóa theo resolution/FPS của project, kéo dài frame cuối nếu animation ngắn hơn timeline, cắt phần video dư, rồi ghép scene WAV bằng AAC 48 kHz. Composer không dùng `-shortest`; khoảng nghỉ `sceneEndPaddingMs` đã nằm trong scene WAV và timeline.

Output:

```text
output/<projectId>/
├── final.mp4
└── scenes/
    ├── <sceneId>-whiteboard.mp4
    └── <sceneId>-with-audio.mp4
```

Video dùng H.264, AAC và `yuv420p`. Kiểm tra file hoàn chỉnh:

```bash
ffmpeg -v error -i output/<projectId>/final.mp4 -f null -
```

Nếu command không in lỗi và trả exit code `0`, FFmpeg đã đọc được toàn bộ video.

```text
assets/whiteboard/<项目名>/
├── scene-01-<名称>.png
├── scene-01-<名称>.annotation.json
├── scene-01-<名称>-whiteboard.mp4
└── scene-01-<名称>-preview.mp4
```

图片与标注必须同名，例如 `scene-01-demo.png` 对应 `scene-01-demo.annotation.json`。

## 标注格式

每个元素使用原图的整数像素坐标，并通过 `sequence`、`subtitle` 与 `narrativeRole` 关联字幕中的事件。区域应按“场景铺垫 → 关键人物/物体 → 动作或变化 → 反应/结果”排序。

```json
{
  "sceneId": "scene-01",
  "canvas": { "width": 1672, "height": 941 },
  "storyBasis": "小猴在猴子山上拿着香蕉，大猴抢走香蕉，孩子们在旁观看。",
  "sceneDurationMs": 9000,
  "elements": [
    {
      "id": "rockery",
      "label": "猴子山场景",
      "sequence": 1,
      "narrativeRole": "故事的场景铺垫",
      "subtitle": "小猴子坐在猴子山顶，手里拿着香蕉。",
      "type": "structure",
      "region": { "x": 20, "y": 120, "width": 540, "height": 780 },
      "reveal": {
        "direction": "top_to_bottom",
        "startMs": 300,
        "durationMs": 2600,
        "maskPaddingPx": 22,
        "protectedRegions": []
      },
      "handPath": { "start": [290, 130], "end": [290, 890], "easing": "easeInOut" }
    }
  ]
}
```

`direction` 和 `handPath` 用于预览台的矩形代理；最终成片的真实笔迹由流式绘制器自动生成。对于相互遮挡的对象，在较早元素的 `protectedRegions` 中标出需要延后显示的区域，避免后续内容提前露出。

## 常用命令

解析字幕并生成建议分镜：

```bash
python scripts/parse_srt.py <字幕.srt> --target-sec 30 --min-sec 25 --max-sec 35
```

生成区域检查图：

```bash
python scripts/render_annotation_preview.py <图片路径> <标注路径> <预览图输出路径>
```

打开 `assets/preview.html`，使用“打开文件夹”载入场景目录，即可编辑区域、顺序、时间与字幕关联。

渲染单幕：

```bash
<ENV_PY> scripts/render_stream_whiteboard.py <图片路径> <标注路径> <输出.mp4> assets/drawing-hand.png \
  --ink-path grid --color-fill contour-wipe
```

合并多幕：

```bash
<ENV_PY> scripts/merge_scenes.py --inputs 幕1.mp4 幕2.mp4 幕3.mp4 --output final.mp4
```

## 质量检查

- 首帧是干净的暖米黄纸张底色，没有提前露出的线条
- `canvas` 与原图尺寸一致，所有区域都是画布内的整数像素坐标
- `sequence`、`startMs` 与字幕的叙事顺序一致
- 中段帧中，未开始区域和保护区不会提前出现
- 笔尖贴近当前流式笔迹；线稿清晰时可选择 `--ink-path skeleton`
- 每幕结束后至少停留 0.5 秒完整画面；多幕合并顺序与字幕分镜一致

## 仓库内容

```text
srt-whiteboard-animation/
├── SKILL.md                         # 完整工作流与约束
├── assets/
│   ├── drawing-hand.png              # 手部素材
│   ├── preview.html                  # 本地编辑预览台
├── examples/                         # README 案例素材
├── scripts/
│   ├── parse_srt.py                  # 字幕解析与分镜建议
│   ├── render_annotation_preview.py  # 标注检查图
│   ├── render_stream_whiteboard.py   # 流式笔迹 MP4 渲染器
│   ├── merge_scenes.py               # 多幕合并
│   └── prepare_env.py                # 依赖环境准备
└── agents/openai.yaml                # Codex 元数据
```

## 贡献

欢迎提交 Issue 或 Pull Request。任何涉及绘制逻辑的改动，都应使用真实的字幕、标注和成片检查遮罩保护、时序与最终画面。

## 许可证

本项目基于 MIT License 开源，详见 [LICENSE](LICENSE)。

## 关于作者

一个爱养鱼的老登 / AI Builder / 用 AI 团队打造一人公司。

抖音、B站、公众号：江哥是老登啊
