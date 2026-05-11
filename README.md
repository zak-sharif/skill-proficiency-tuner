# Skill Proficiency Threshold Tuner

Streamlit app for tuning skill-proficiency thresholds against Fall 2025 + Spring 2026 Rize backtest data.

## What it does

- Lets you adjust per-level thresholds (L1–L4) for Meets/Exceeds/Outstanding counts, course-level criteria source, enrollment requirements, final-project rating, and capstone-criterion toggles
- Computes proficiency level per (student, skill) across either the full Rize journey or per-course in real time
- Surfaces per-skill and per-course distributions with cumulative ≥L1 / ≥L2 / ≥L3 metrics
- Computes a parallel **Skill Points** view: tune rating values and course-level multipliers to see average per-student point accumulation by skill

## Data

Pre-computed parquet files in `data/backtest/`:
- `criterion_facts.parquet` — one row per matched rubric criterion (262,865 rows, both terms)
- `student_enrollments.parquet` — (student, course, term) tuples
- `skill_meta.parquet` — skill metadata incl. Path A (Benchmark) vs Path B (LO) classification

Coverage: 2,284 unique students across Fall 2025 (970) + Spring 2026 (1,702), 45 skills, 17 courses.

### Anonymization

Student IDs have been replaced with salted SHA-256 hashes (12 hex chars). The salt is not committed to this repo and the original Canvas user_ids are not recoverable from the hashed IDs. No names, emails, or other identifying fields are present in the data.

## Run locally

```bash
pip install -r webapp/requirements.txt
streamlit run webapp/app.py
```

## Deploy on Streamlit Community Cloud

1. Connect this repo at https://share.streamlit.io
2. Main file: `webapp/app.py`
3. Python version: 3.11
4. To enable password protection, add a `APP_PASSWORD` value in the app's Secrets settings (TOML format):
   ```toml
   APP_PASSWORD = "your-shared-password"
   ```
   Without this, the app is open.
