# giga-transcribe

Видео/аудио любой длины → текст через [GigaAM v3](https://github.com/salute-developers/GigaAM) (русский ASR, офлайн, CPU).
Фразы режутся нейросетевым Silero VAD, на выходе — текст или субтитры SRT/VTT.

## Запуск

```bash
pip install -r requirements.txt && pip install -e ./GigaAM  # веса ~1GB докачаются сами
uvicorn src.app:app --port 8099  # → http://localhost:8099 (drag-n-drop морда)
```

Или в Docker (веса ~422MB уже внутри образа):

```bash
docker compose up --build -d
```

## API

```bash
# Async — для файлов любой длины (часы):
curl -F f=@long.mp4 http://localhost:8099/upload        # -> {"id": ...}
curl http://localhost:8099/jobs/<id>                    # poll: status/progress/preview
curl http://localhost:8099/jobs/<id>/text               # готовый текст (/srt, /vtt — субтитры)

# Sync, OpenAI-совместимый — для коротких файлов:
curl -F file=@a.mp3 -F model=gigaam-v3 http://localhost:8099/v1/audio/transcriptions
# response_format: json | text | verbose_json | srt | vtt
```

## Как устроено

`ffmpeg → wav 16kHz → Silero VAD (фразы до 25с) → GigaAM v3_e2e_ctc → склейка`

`src/vad.py` — нарезка на фразы, `src/engine.py` — модель + фоновые задачи, `src/app.py` — FastAPI, `static/index.html` — веб-морда.

Потолок: CPU, час видео ≈ 2–4 часа транскрибации, один воркер.
