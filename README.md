# Smart Inventory & Billing System

Flask + one JSON file (`data/store.json`) for storage. No database needed.

## Run
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 and sign in with `admin@example.com` / `admin123`.

`data/store.json` is created automatically with sample data on first run.
Delete it to reset everything.

## Files
| File | Purpose |
|---|---|
| `app.py` | Routes, data layer (`load_data` / `save_data`), billing, dashboard stats, PDF invoice |
| `templates/app.html` | Whole UI: login, dashboard, products, inventory, billing, sales, customers |
| `requirements.txt` | Flask, ReportLab |
| `data/store.json` | Auto-generated data file |

## Limits (say this in your presentation)
JSON storage suits a local prototype. For many simultaneous users, move to PostgreSQL/MySQL.
Change `SECRET_KEY` (env var) and the admin password before real use.
