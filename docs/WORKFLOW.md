# ARBY3 Workflow (ChatGPT ↔ Claude ↔ VSCode ↔ GitHub)

## Джерело істини
- Завжди: GitHub repo + Branch + HEAD SHA + Diff/Compare + актуальний Status*.md + артефакти runDir.
- Будь-яка зміна вважається “існуючою” лише після пуша в GitHub.

## PR правила
- 1 PR = 1 задача. 1–2 коміти максимум.
- Заборонено “megapack” без розбиття на логічні PR.
- PR не приймається, якщо `python -m pytest -q` не зелений.

## Мінімальний verify перед пушем (Windows PowerShell)
- `python -m pytest -q`
- `python -m strategy.jobs.run_scan --cycles 1 --output-dir data\runs\session_<ts>`
- Артефакти повинні створитись: scan_*.json, truth_report_*.json, reject_histogram_*.json, scan.log(+ paper_trades якщо є)

## Артефакти і Git
- `data/runs/**` НЕ комітимо (runtime).
- Комітимо лише “golden fixtures” у `docs/artifacts/<type>/<date>/` (4 json + scan.log.txt + README.md).
- Копіпаст дозволений тільки для коротких логів/traceback (5–30 рядків), не як заміна GitHub.

## Формат повідомлення для рев’ю (ChatGPT/Claude)
- Repo, Branch, HEAD SHA
- Compare link: `.../compare/main...<branch>` або `<oldSHA>...<newSHA>`
- Status*.md permalink
- `git diff --name-only origin/main...HEAD` (вставити список)
- Посилання/файли golden artifacts (або прикріплення)

## Ролі
- Claude: робить зміни в коді, дрібні PR, зелений pytest, оновлює Status*.md.
- ChatGPT: жорсткий рев’ю (10 проблем + 10 кроків), аналізує артефакти/Status/Roadmap.
- Я: координатор (VSCode/GitHub), запускаєш verify-команди, додаєш артефакти, менеджиш PR.
