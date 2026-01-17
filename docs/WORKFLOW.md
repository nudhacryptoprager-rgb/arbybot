# ARBY3 Dev Workflow (Windows + PR)

## Rule #1: PR is the workspace
Everything needed to continue work must be in the PR:
- docs/Status_*.md updated
- artifacts under data/runs/YYYY-MM-DD/<run_id>/
- brief log snippet or scan.log.txt

## Standard cycle
1) Create a branch
   - git checkout -b m3/<topic>

2) Create run folder
   - powershell -ExecutionPolicy Bypass -File tools/new_run.ps1 -RunId "smoke_01"
   - copy the printed path

3) Run scan and capture log
   - Run from VS Code task OR terminal
   - Save console output to: data/runs/<date>/<run_id>/scan.log.txt
   - Ensure truth_report/reject_histogram/snapshots are in same folder (copy or export)

4) Update docs/Status_*.md
   - include:
     - what changed
     - how to reproduce
     - key metrics (attempted/fetched/passed, top reject reasons)
     - link to run folder path

5) Commit + push
   - git add .
   - git commit -m "M3: <topic> (run artifacts + status)"
   - git push -u origin <branch>

6) Open PR
   - Fill PR template
   - Link run folder + artifacts

## Assistant context block (paste into Claude/ChatGPT)
- PR link:
- Status file:
- Run folder:
- Goal / expected outcome:
