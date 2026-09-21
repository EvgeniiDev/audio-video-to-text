# giga-transcribe — видео/аудио в текст через GigaAM v3

## Установка (один раз)

```bash
cd ~/projects/giga-transcribe
git clone https://github.com/salute-developers/GigaAM
uv venv && source .venv/bin/activate   # или python3 -m venv
pip install -r requirements.txt
pip install -e ./GigaAM                # сам GigaAM (~1GB весов докачаются при первом запуске)
```

## Запуск

```bash
source .venv/bin/activate
uvicorn src.app:app --host 0.0.0.0 --port 8099
# открыть http://localhost:8099
```

## Как устроено

`ffmpeg → wav 16kHz → VAD-нарезка на фразы (как qwen_talker, кап 25с) → GigaAM v3_e2e_ctc → склейка → .txt + .srt`

- `src/vad.py` — EnergyVAD + нарезка (порт из `qwen_talker/src/asr/realtime_asr.py`, но из файла, не с микрофона)
- `src/engine.py` — модель (warm, грузится один раз) + фоновые задачи; `python -m src.engine` — self-check без модели
- `src/app.py` — FastAPI: `POST /upload`, `GET /jobs`, `GET /jobs/{id}`, `.../text`, `.../srt`
- `static/index.html` — морда: drag-n-drop, прогресс, превью, скачивание

Потолок: CPU, час видео ≈ 2–4 часа. Один воркер (threading.Lock).
