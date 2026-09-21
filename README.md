# Pet Breed Eval — сравнение LLM и CNN-классификаторов на определение пород собак

Python-фреймворк для тестирования vision-LLM (OpenAI-совместимый API) и CNN-сервиса
на задаче определения породы собаки по фотографии. Поддержка произвольных видов —
через конфиги `configs/species/*.yaml` (собаки и кошки готовы).

## Результаты финального прогона (2026-09-21, web-фото обновлены)

**Датасет**: 300 фото, 20 пород собак (12 из Oxford-IIIT Pet + 8 web) × 15 фото.
**Модель LLM**: agnes-3.0-flash · **CNN**: действующий сервис Dog Breed Auto Identify (~400 классов, протокол восстановлен из APK).
Полный прогон 900/900 вызовов LLM и 300/300 CNN, ноль ошибок API.

### Сводная таблица

| Система            | Top-1  | Top-3  | Macro-F1 | Примечание                 |
|--------------------|--------|--------|----------|----------------------------|
| **CNN сервис**     | **95.0%** | 96.0%  | **96.5%** | 300 фото, латентность ~4.3s |
| LLM reasoning      | 86.3%  | **97.0%** | 86.3%  | CoT: признаки перед ответом |
| LLM closed         | 84.7%  | 96.0%  | 84.4%    | список из 20 кандидатов    |
| LLM open           | 61.0%  | 64.3%  | 67.3%    | свободный ответ            |

### Ключевые выводы

1. **CNN-сервис сильнее LLM на этой задаче**: 95.0% vs 86.3% top-1 при том,
   что CNN не получает списка кандидатов (400 классов против 20 у LLM).
2. **Но системы ошибаются на РАЗНЫХ фото**: CNN добавляет 42 исправления
   к closed-режиму LLM (36 к reasoning), LLM исправляет CNN лишь на 11 фото (10).
3. **Ансамбль CNN+LLM**: **98.7%** top-1 (closed), 98.3% (reasoning) —
   ошибки только на 4 из 300 фото.
4. Слабые места LLM: Bassett↔Beagle, Akita↔Shiba, тонкие различия ретриверов.
5. Reasoning-режим (CoT) добавляет +1.6 п.п. к top-1 ценой возросшей латентности.
6. Подробности: `reports/report_dog_agnes-3.0-flash_*.html` (автономный отчёт
   с галереями ошибок и путаницами).

### Эксперименты с провайдерами (2026-09-21)

| Провайдер | Модель | Статус |
|-----------|--------|--------|
| apihub.agnes-ai.com | agnes-3.0-flash | рабочий, полный прогон завершён |
| free.empero.org | Qwen/Qwen3.8-27B-FP8 | 503 maintenance: «ждём новой ёмкости»; конфиг `configs/eval_empero.yaml` готов |
| inference.dahl.global | zai-org/GLM-5.3-Flash | **vision недоступен**: шлюз отклоняет все image-блоки
  (`unsupported value "image_url"`), в документации прямо сказано
  «Vision is not offered on current models». Квота 100M токенов, лимит —
  конкурентный (429 `model_concurrency`, платные приоритетнее). Конфиг
  `configs/eval_dahl.yaml` сохранён — пригодится, если vision появится |

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

## Датасет (хранится в репозитории)

Извлечённые фото закоммичены, чтобы восстановление окружения занимало секунды
(git clone) вместо ~18 минут (S3 811MB + image-search + загрузки):

- `data/oxford/dog/` — 180 фото, 12 пород Oxford-IIIT Pet × 15 (лицензия датасета допускает исследование)
- `data/web/dog/` — 120 фото, 8 web-пород × 15 — найдены через image-search, источники
  в `data/web/dog/_search/*.json`. Использование — исследовательский бенчмарк;
  права на оригиналы принадлежат их владельцам (при претензии — удалю по запросу).
- Сырой архив Oxford (811MB) НЕ хранится: лимит GitHub 100MB/файл.
  С нуля: `scripts/prepare_oxford.py` + `scripts/fetch_web_photos.py` + `scripts/build_manifest.py`.

## Воспроизведение

```bash
pip install requests pillow pyyaml
git clone https://github.com/NikasAl/animal_classifier.git && cd animal_classifier
python run_eval.py --species dog --config configs/eval.yaml          # agnes-3.0-flash
python run_eval.py --species dog --config configs/eval_empero.yaml   # Qwen3.8-27B-FP8 (empero, free)
# NB: configs/eval_dahl.yaml (GLM-5.3-Flash) — пока только text, без vision
python scripts/run_cnn.py --species dog                              # CNN-сервис kreagenium.ru
python make_report.py --species dog --config configs/eval_empero.yaml --cnn results/results_dog_cnn.jsonl
python make_compare.py --a results/results_dog_agnes-3.0-flash.jsonl \
                       --b results/results_dog_qwen3.8-27b-fp8.jsonl \
                       --cnn results/results_dog_cnn.jsonl           # сравнение моделей
```
