# giga-transcribe — видео/аудио в текст через GigaAM v3

## Установка (один раз)

```bash
cd ~/projects/giga-transcribe
git clone https://github.com/salute-developers/GigaAM   # или git submodule update --init
uv venv && source .venv/bin/activate   # или python3 -m venv
uv pip install --no-deps silero-vad    # резолвер uv висит на torchaudio<2.10, ставим без депов
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

`ffmpeg → wav 16kHz → Silero VAD-нарезка на фразы (любая длина, кап 25с) → GigaAM v3_e2e_ctc → склейка → text/srt/vtt`

- `src/vad.py` — Silero VAD v6 (нейросетевой, веса в pip-пакете, офлайн), lazy singleton
- `src/engine.py` — модель (warm, грузится один раз) + фоновые задачи; `python -m src.engine` — self-check без модели
- `src/app.py` — FastAPI: свой async API + OpenAI-совместимый sync API (см. ниже)
- `static/index.html` — морда: drag-n-drop, прогресс, превью, скачивание

Потолок: CPU, час видео ≈ 2–4 часа. Один воркер (threading.Lock).

## Docker

```bash
docker compose up --build -d     # образ ~2.5GB (torch CPU + веса 422MB внутри)
docker compose logs -f transcribe
```

Слои (снизу вверх): `base` (OS+ffmpeg) → `weights` (ckpt, md5-check) →
`torch` → `pydeps` (pip + код GigaAM) → `runtime` (только наш `src/`).
Правка `src/` пересобирает только последний слой (секунды); бамп пакетов —
`pydeps`+, веса/OS из кэша. Версии пинятся build-arg'ами
(`PYTHON_IMAGE`, `TORCH_VER`, `GIGAAM_REF`, `MODEL_NAME`).

Веса можно вынести наружу: раскомментируй `- ./models:/models` в
`docker-compose.yml` — entrypoint докачает ~422MB при первом старте и
переиспользует при пересборках.

## API для других сервисов

### A. OpenAI-совместимый (sync, для коротких файлов)

`POST /v1/audio/transcriptions` — multipart (`file*`, `model`, `language`,
`prompt`, `response_format`, `temperature`, `timestamp_granularities[]`).
Ждёт результата, как настоящий OpenAI. `model` принимается, игнорируется
(одна локальная модель). `response_format`: `json` (дефолт), `text`,
`verbose_json` (segments со start/end/text), `srt`, `vtt`.

```bash
curl -F file=@a.mp3 -F model=gigaam-v3 \
  http://localhost:8099/v1/audio/transcriptions
curl -F file=@a.mp4 -F model=gigaam-v3 -F response_format=verbose_json \
  http://localhost:8099/v1/audio/transcriptions
```

### B. Свой async (для файлов любой длины — часы)

```bash
curl -F f=@long.mp4 http://localhost:8099/upload        # -> {"id": ...}
curl http://localhost:8099/jobs/<id>                    # poll: status/progress/preview
curl http://localhost:8099/jobs/<id>/text               # готовый текст
curl http://localhost:8099/jobs/<id>/srt                # субтитры
curl http://localhost:8099/jobs/<id>/vtt
```
