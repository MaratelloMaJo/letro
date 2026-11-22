# Промпт для продолжения работы над LETRO

Ты — инженер-исполнитель в репозитории `D:\documents\Projects\letro` (Windows, PowerShell). Продолжай работу по официальному чеклисту Genesis FinTech. Не начинай с нового аудита: аудит уже сделан, решения зафиксированы в плане.

## Что читать первым

1. `docs/superpowers/plans/2026-11-22-official-judge-adapter.md` — план с milestone M0–M5, задачами, интерфейсами и TDD-шагами. Это главный документ.
2. `D:\downloads\fintech-checks.txt` — официальный чеклист (280 строк, опубликован 2026-11-20). Если файла нет, попроси его у пользователя; не выдумывай требования.
3. `docs/CONTINUATION_PROMPT.md` — этот файл.
4. `README.md`, `DESIGN.md`, `letro/env.py`, `letro/evaluator.py`, `letro/matcher.py`, `letro/schema.py`, `letro/reward.py`, `letro/generator/episode.py`, `letro/generator/errors.py`, `letro/generator/company.py`.

## Текущее состояние

- Ветка: `fix/official-judge-adapter` (создана от `master`).
- Базовая точка: `40846e9` (`Merge branch 'letro-proof-pack'`), рабочее дерево было чистым.
- План сохранён: `docs/superpowers/plans/2026-11-22-official-judge-adapter.md`.
- `judge_adapter.py` ещё не создан. Это блокер №1: без него жюри не может вызвать проект, и Blocks 1–4 (90 баллов) не начисляются.
- Текущая самооценка проекта `python -m letro.verify` = 100/100, но это **собственная** рубрика LETRO, а не официальный чеклист. Официальная оценка «как есть» ≈ 10/100 (только engineering), потому что обязательный адаптер отсутствует.
- Целевая оценка после плана: ~88–96/100. 100/100 не гарантируется: остаются риски независимой проверки бухгалтерии жюри и официальных fixture-ов.

## Ключевые требования чеклиста (не переформулировать)

- Обязательный `judge_adapter.py` в контейнере команды. Три entry point:
  - `generate_episode(seed: int, config: dict, output_dir: str) -> None`
  - `make_env()` -> объект с `reset(seed, config)` и `step(action)`
  - `score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict`
- Closed reset: `{"mode": "closed", "episode_dir": "<dir>", "team_config": {...}}`. Загрузить именно этот эпизод, не генерировать заново, не менять ID. Повторный reset перезапускает тот же эпизод.
- Train reset: `mode="train"`, без `episode_dir` — генератор команды по seed/team_config.
- Действие: `{"name": "<action>", "args": {...}}`; имена: `list_records`, `get_record`, `get_document`, `calculator`, `submit`.
- Первое observation: `{task, manifest, policy, remaining_steps}`. Дальше: `{result, error, remaining_steps}`.
- `list_records` -> `{records: [...], next_cursor: null|string}`.
- `calculator` -> десятичная строка.
- `submit` -> `{"accepted": true}` или ограниченная структурная ошибка; никогда не возвращать correctness.
- `score_episode` valid -> `{tp, fp, fn, precision, recall, f1, return}`; invalid -> `return=-1`, остальные шесть `null`.
- Closed reward для политики = 0, включая termination. Истинный reward считается только на стороне жюри/evaluator.
- 60 секунд на эпизод от reset, включая время политики; просрочка -> `truncated=true`, пустые findings.
- Submit входит в 100 действий, но не в `inspection_steps`; ошибки входят в `inspection_steps`.
- Block 3: точные ID (без strip/case-fold), точная валюта, evidence IDs должны существовать в открытых данных, неизвестный string type = FP (не структурная ошибка), τ по умолчанию 0, максимум 30 findings / 10 evidence / 1000 символов, maximum-cardinality matching, допуск чисел 1e-9 (не округлять до 6 знаков).
- Block 2: нужны D09–D11 (хотя бы один полный missing allocation и один partial) и D19–D20 (чистый второй composite-сценарий, не только первый).
- Block 4: pair checks через копию эпизода и `episode_dir`; отдельный transform-код не обязателен, если closed reset + score работают.
- Engineering 10 баллов уже сильные: один launch command, версии, trajectories.jsonl, measured failure analysis, honest limitations.

## Milestones

### M0 — ветка, план, промпт
Статус: ветка и план готовы; этот промпт — часть M0. Сделай коммит M0.

### M1 — адаптер, closed mode, канонический интерфейс
Файлы: `judge_adapter.py`, `tests/test_judge_adapter.py`, при необходимости `letro/factory.py`, `letro/evaluator.py`.

Порядок:
1. `generate_episode`: вызвать `letro.generator.generate_episode(seed, team_config)`, затем `write_episode(episode, output_dir, include_closed=True)`. `team_config = config.get("team_config", config)`.
2. `JudgeEnv.reset`: closed -> `load_episode(config["episode_dir"], load_closed=True)` + `env_from_episode(episode, mode="eval")`; train -> сгенерировать. Сохранить `_episode`, `_closed`, `_deadline = time.monotonic() + 60`.
3. Канонические observation/action: перевод `{name,args}` -> внутренний `{type,...}`; `rows` -> `records`; int cursor -> str; calculator unwrap; submit -> `accepted`.
4. `score_episode`: `load_episode`, строгая валидация, `score(..., strict=True, available_evidence=...)`, `terminal_reward(..., exact=True)`, вернуть ровно 7 ключей.
5. `available_evidence_ids`: ledger `row_id`; invoice `doc_id`/`invoice_id`; payment `doc_id`/`payment_id`.

Тесты M1: файлы эпизода; closed reset с тем же manifest; повторный reset; list_records/cursor; calculator `0.1+0.2 -> "0.3"`; get_record; submit accepted + closed reward 0; score_episode test 1 = 0.98; invalid 31 findings = -1/null.

### M2 — строгий matcher/validator/reward
Файлы: `letro/matcher.py`, `letro/schema.py`, `letro/evaluator.py`, `letro/reward.py`, `tests/test_official_matcher.py`.

- `validate_findings_payload_strict`: те же лимиты; unknown string type разрешён; ID не strip; валюта не upper/не проверяется по списку; amount int non-bool.
- `finding_matches(..., strict=False, available_evidence=None)`: strict — точная валюта, evidence IDs должны быть в available, ID без strip; default — текущее поведение.
- `match`/`score`: прокинуть strict/available; сохранить augmenting-path max matching.
- `terminal_reward(..., exact=False)`: exact=True — без round(...,6).
- `Evaluator(strict=False)`: strict использует strict-validator и strict matcher; default не меняется.

Тесты: официальные 20 тестов Block 3 + M01–M12, особенно test 5 (47/150), test 12 (-871/1050), test 13 (47/150), M04 (лишний U -> FP), M06 (kzt -> FP), M08 (τ=1), M10/M11 (max matching).

### M3 — 60 секунд и cursor
Файлы: `letro/env.py`, `judge_adapter.py`, `tests/test_judge_adapter.py`.

- Добавить `AuditEnv.truncate()`.
- `JudgeEnv.step` проверяет deadline до перевода действия; при просрочке — truncate, reward 0, terminated/truncated true.
- Тест: `env._deadline = 0.0` -> step возвращает truncated.
- Тест пагинации: пройти все страницы, собрать row_id, проверить отсутствие дублей и совпадение с manifest.

### M4 — детерминированные сценарии генератора
Файлы: `letro/constants.py`, `letro/schema.py`, `letro/generator/errors.py`, `letro/generator/company.py`, `tests/test_generator_scenarios.py`.

- `gap_mode`: `partial` (default), `missing`, `mixed`. `missing` — AR credit = 0, вся сумма в suspense; truth expected amount = полная сумма.
- `composite_scenario`: `alternate` (default), `first`, `second`, `both`. `second` + `composite:1` -> `_composite_gap_cutoff` (scope `gap_cutoff_payment`).
- Флаги `split_payment`, `refund`, `recurring` (default true) отключают соответствующие случайные ветки в `company.py`.
- Обновить `DEFAULT_CONFIG` и `validate_config`; default output не должен меняться.

### M5 — README, audit report, verify
- README: секция «Official judge adapter» с рабочей директорией, launch command, тремя entry point, примером closed reset, таблицей четырёх типов ошибок, схемой `score_episode`, closed reward 0, 60s.
- `docs/OFFICIAL-CHECKLIST-AUDIT.md`: таблица Block 1–4 + engineering, текущая оценка, что исправлено, что осталось.
- Команды:
  - `python -m unittest discover -s tests -v`
  - `python -m letro.verify`
  - `python -c "import judge_adapter; print(judge_adapter.make_env())"`

## Официальная таблица оценки (для отчёта)

| Блок | Баллы | Что проверяет | Текущий риск |
|---|---:|---|---|
| Block 1 — contract tests | 25 | 20 тестов C01–C20: reset, observation, manifest, list/get/calculator, ошибки, submit, лимиты, 60s, no leak | адаптер отсутствует; canonical envelope; 60s |
| Block 2 — closed episodes | 25 | 20 эпизодов D01–D20: clean, duplicates, gaps, FX, period, composites | нет full missing allocation; нет чистого second composite |
| Block 3 — matcher/reward | 25 | 20 unit-тестов + M01–M12: exact IDs/currency/evidence, limits, matching, τ, 1e-9 | upper currency, evidence existence, 6-decimal rounding |
| Block 4 — pair checks | 15 | P01–P20: reorder + bijective ID replacement, replay, inverse mapping | структурно поддержано closed reset/score, нужен адаптер |
| Engineering | 10 | launch command, versions, trajectories, failure analysis, limitations | уже сильно, 10/10 вероятно |

Текущая официальная оценка «как есть»: ≈10/100. После M1–M3: ≈88–91/100. После M4–M5: ≈92–96/100 при отсутствии независимых претензий жюри к бухгалтерии.

## Правила работы

- TDD: сначала падающий тест, потом минимальная реализация, потом полный прогон.
- Не менять default-поведение LETRO без необходимости; официальная строгость — только через `strict=True` / `exact=True`.
- Не логировать truth/provenance/seed в observation, info или error.
- Не добавлять внешние зависимости.
- Коммит после каждого milestone, сообщения по шаблону `feat:` / `docs:` / `test:`.
- Если лимиты заканчиваются: остановись на границе milestone, запиши в этот файл статус (что сделано, какие тесты падают, следующий шаг), закоммить и передай пользователю.

## Следующее действие прямо сейчас

Начать M1, Task 1: создать `tests/test_judge_adapter.py` с тестом `test_generate_episode_writes_open_and_closed_files`, убедиться, что он падает, затем создать `judge_adapter.py` с `generate_episode`.
