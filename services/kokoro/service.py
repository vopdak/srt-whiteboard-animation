import io
import json
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parent / "kokoro"
sys.path.insert(0, str(SOURCE_DIR))

try:
    import numpy as np
    from kokoro import KPipeline
except ImportError as exc:
    print("Kokoro dependencies are missing.", file=sys.stderr)
    print("Install them with:", file=sys.stderr)
    print("python -m pip install -e services/kokoro/kokoro", file=sys.stderr)
    raise SystemExit(1) from exc


SAMPLE_RATE = 24000
pipelines = {}


def synthesize(text, voice, speed):
    lang_code = voice[0]
    pipeline = pipelines.get(lang_code)
    if pipeline is None:
        pipeline = KPipeline(lang_code=lang_code)
        pipelines[lang_code] = pipeline

    chunks = []
    for _, _, audio in pipeline(text, voice=voice, speed=speed):
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        raise RuntimeError("Kokoro returned no audio")

    samples = np.clip(np.concatenate(chunks), -1.0, 1.0)
    pcm = (samples * 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        body = b'{"status":"ok","provider":"kokoro"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            text = request.get("text", "")
            voice = request.get("voice", "")
            speed = request.get("speed")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
            if not isinstance(voice, str) or not voice.strip():
                raise ValueError("voice must be a non-empty string")
            if isinstance(speed, bool) or not isinstance(speed, (int, float)) or speed <= 0:
                raise ValueError("speed must be greater than 0")
            body = synthesize(text, voice, speed)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message, *args):
        print(f"[kokoro] {message % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8880), Handler)
    print("Kokoro service listening on http://127.0.0.1:8880")
    server.serve_forever()
