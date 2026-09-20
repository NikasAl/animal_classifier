# Pet Breed Eval — сравнение LLM и CNN-классификаторов на определение пород собак

Python-фреймворк для тестирования vision-LLM (OpenAI-совместимый API) и CNN-сервиса
на задаче определения породы собаки по фотографии. Поддержка произвольных видов —
через конфиги `configs/species/*.yaml` (собаки и кошки готовы).

## Результаты расширенного прогона (2026-09-20)

**Датасет**: 300 фото, 20 пород собак (12 из Oxford-IIIT Pet + 8 web) × 15 фото.
**Модель LLM**: agnes-3.0-flash · **CNN**: действующий сервис Dog Breed Auto Identify (~400 классов, протокол восстановлен из APK).

### Сводная таблица

| Система            | Top-1  | Top-3  | Macro-F1 | Латентность | Примечание                 |
|--------------------|--------|--------|----------|-------------|----------------------------|
| **CNN сервис**     | **95.7%** | 97.3%  | **96.7%** | 4.7s        | 300 фото, ноль ошибок API  |
| LLM reasoning      | 87.0%  | **98.3%** | 87.1%  | ~19s        | CoT: признаки перед ответом|
| LLM closed         | 85.7%  | 97.0%  | 85.4%    | ~4s         | список из 20 кандидатов    |
| LLM open           | 60.0%  | 63.0%  | 67.4%    | ~7s         | свободный ответ, 26% отказов|

### Ключевые выводы

1. **CNN-сервис сильнее LLM на этой задаче**: 95.7% vs 85.7% top-1 при том,
   что CNN не получает списка кандидатов (400 классов против 20 у LLM).
2. **Но системы ошибаются на РАЗНЫХ фото** (совпадение топ-1 ответов — 83%):
   CNN прав в 40 из 43 случаев ошибок LLM, LLM (reasoning) прав в 11 из 13 ошибок CNN.
3. **Ансамбль CNN+LLM**: 99.0% top-1 (closed), **99.3%** (reasoning) — ошибок всего 2 из 300.
4. Слабые места CNN: Havanese (4 из 13 ошибок — порода отсутствует/нераспознаваема),
   American Bulldog→Boxer, Shiba Inu→Akita.
5. Слабые места LLM: Bassett↔Beagle, Akita↔Shiba, тонкие различия ретриверов.
6. Reasoning-режим (CoT) стабильно добавляет +1.3 п.п. к top-1 и +1.3 п.п. к top-3
   ценой 6× латентности.
7. «Заученности» Oxford нет ни у CNN (95.0% oxford vs 96.7% web), ни у LLM (84.4% vs 87.5%).

### Сравнение с пилотом на кошках (n=100, тот же протокол)

| Вид   | LLM closed top-1 | LLM open top-1 | Oxford vs Web      |
|-------|------------------|----------------|--------------------|
| кошки | 62%              | 43%            | oxford выше на 15.8 п.п. |
| собаки| 86% (n=300)      | 60%            | web выше на 3 п.п. |

## Протокол CNN-сервиса (восстановлен из APK ru.electronikas.dogsexpert)

```
POST https://kreagenium.ru/client/dogs/jsondogfindinjpeg
Content-Type: application/json

{"imageJpg": "<base64 JPEG>"}

-> {"fileHash": "...",
    "breedList": [{"nameID": "karelian bear dog", "value": 31}, ...],
    "errorMessage": null}
```

`value` — оценка уверенности (0-100). Спец-класс `no any dog` = «не собака».
Второй эндпоинт enum: `jsonusermarkcorrectness` (обратная связь по корректности).

## Структура

- `configs/eval.yaml` — API, параметры запроса, режимы, настройки CNN-сравнения
- `configs/species/*.yaml` — породы, алиасы ru/en, маркеры отказа
- `src/api_client.py` — vision LLM (ретраи, backoff, resume-совместим)
- `src/prompt_builder.py` — 3 режима промпта (closed/open/reasoning)
- `src/cnn_client.py` — клиент CNN-сервиса + эвристический парсер ответа
- `src/normalizer.py` — алиасы + fuzzy-match (0.82) к каноническим породам
- `src/evaluator.py` — пул потоков, JSONL resume-кэш по (item_id, mode)
- `src/metrics.py` — top-1/top-3, per-breed P/R/F1, by-source, калибровка, путаницы
- `src/report_html.py` — автономный HTML (ECharts встроен, галерея ошибок, сравнение)
- `scripts/` — prepare_oxford, fetch_web_photos, build_manifest, run_cnn, probe_cnn,
  dex_fields (мини-парсер DEX для извлечения enum/DTO из APK)
- `results/results_dog_agnes-3.0-flash.jsonl` — 900 записей (300×3 режима LLM)
- `results/results_dog_cnn.jsonl` — 300 записей CNN
- `reports/report_dog_*.html` — итоговый отчёт (открывается офлайн)

## Воспроизведение

```bash
pip install requests pillow pyyaml
python scripts/prepare_oxford.py --species dog --per-breed 15
python scripts/fetch_web_photos.py --species dog --max-per-breed 15
python scripts/build_manifest.py --species dog --per-breed 15
python run_eval.py --species dog          # LLM (resume: обрывы безопасны)
python scripts/run_cnn.py --species dog   # CNN-сервис
python make_report.py --species dog --cnn results/results_dog_cnn.jsonl
```

Фото не хранятся в репозитории (web-фото — чужие копирайты; Oxford — скачайте
с S3 fast.ai). Готовый пакет с фото: папка download.
