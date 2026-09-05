# Headless Core API (единый Bottle/WSGI-стек)

Статус: стабильный runtime-режим. Все запуски web-контура работают на одном
Bottle-приложении поверх чистого WSGI-сервера из stdlib
(`src/gp_control_plane/web/server.py`). Split-прокси (`web/proxy.py`) и
флаг `--core-url` удалены; миксины `BaseHTTPRequestHandler`-стека выпилены.

## Режимы запуска

- **Монолит**: `gp-control-plane web [--host H] [--port P]`
  — Bottle-app c UI (`/`, `/static/*`) и полным API (`/api/core`, `/api/web`,
  `/api/service`, OpenAPI/Swagger). Фабрика: `create_app(ui_enabled=True)`.
- **Headless Core**: `gp-control-plane core [--host 127.0.0.1] [--port 8081]`
  — тот же `create_app(ui_enabled=False)` на чистом WSGI: UI-роут `/`,
  статика и `/api/web/*` не регистрируются; доступны Core/Service/OpenAPI.

Единая точка сборки: `src/gp_control_plane/web/bottle_server/_routes.py`
`create_bottle_app(config, runner, *, runtime_role, ui_enabled)`; маршруты
регистрируются обходом контракта `web/routes.py::ROUTES`, JSON-эндпоинты
диспетчеризуются через канонический слой `web/api/*` (`handle(ctx) →
(payload, status)`).

## HTTP-контракт и авторизация

- JSON API `/api/*` — единые хэндлеры в `web/api/{auth,core,service,web}.py`;
  внешние вызовы (`bs_triage_domain`, `export_nfconf`, …) замоканы в одной
  точке. Мок-лимиты/медиа — в `web/limits.py`.
- Auth: Bearer-токен. `require_bearer_token` резолвится через модуль
  `gp_control_plane.auth` в момент вызова (у обоих режимов один хук).
- Ошибки хранилища — нормализованный `503 storage_unavailable` в хуках
  `before_request` и в JSON/SSE/NDJSON-потоках.
- Streaming: NDJSON-экспорт кандидатов стримится инкрементально (ошибка до
  первой строки → `503` JSON; mid-stream — тихое обрезание); SSE после
  storage-ошибки отдаёт один `event-error` и закрывает соединение.

## Структура модулей

- `web/server.py` — чистый потоковый WSGI-сервер (`ThreadingMixIn` +
  `wsgiref.WSGIServer`), активные соединения отслеживаются для принудительного
  закрытия при shutdown.
- `web/api/*` — канонический JSON-слой (GET/POST таблицы), общий для всех
  режимов.
- `web/bottle_server/` — регистрация маршрутов из `ROUTES` + transport-адаптеры
  (docs, NDJSON export, download, upload, SSE) и `serve_web_bottle`.
- `web/core_server.py` — `serve_core` = `create_app(ui_enabled=False)`.
- `web/ui/` — внешние ассеты `static/{css,js,html}` и SPA-shell
  `views/index.tpl` (SimpleTemplate; без inline `<style>`/`<script>`).
- `web/limits.py` — лимиты тел/upload и `NDJSON_CONTENT_TYPE`.

## Примечания по миграции

- Старый split-деплой (Core service + Web proxy service) не используется:
  headless-core предназначен для случаев, где web-панель не нужна, а UI при
  необходимости поднимается монолитом на том же хосте или отдельным
  экземпляром, обращающимся к Core по HTTP-контракту напрямую.
- `web/app.py` остаётся compatibility-алиасом на `web.api_server` для старых
  импортов (`serve`, `serve_core`, `core_api`, …).
