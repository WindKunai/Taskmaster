# Taskmaster

> A clean and simple task manager built with Flask. Add tasks, check things off, and get things done.

---

## Features

- **Text or list tasks** — write a description, or build a checklist with individual completable items
- **Due dates** — set deadlines, get visual warnings when things are overdue or due today
- **Filter views** — switch between All, Active, and Done in one click
- **Inline checklist progress** — see `3/5 done` at a glance without opening anything
- **Minimal UI** — fast, clean, no clutter

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python · Flask |
| Database | SQLAlchemy ORM · SQLite (dev) |
| Frontend | Jinja2 templates · Vanilla JS · CSS |
| Config | python-dotenv |

---

## Getting started

**1. Clone and enter the project**

```bash
git clone https://github.com/yourname/taskmaster.git
cd taskmaster
```

**2. Create a virtual environment**

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Configure environment**

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

```ini
SECRET_KEY=your-secret-key-here
SQLALCHEMY_DATABASE_URI=sqlite:///taskmaster.db
SQLALCHEMY_TRACK_MODIFICATIONS=False
FLASK_DEBUG=1
```

**5. Run**

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) and start checking things off.

---

## Project structure

```
taskmaster/
├── app.py              
├── requirements.txt
├── .env.example
├── static/
│   └── style.css
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── add_task.html
│   └── edit_task.html
└── tests/
    └── test_app.py
```

---

## Data model

```
Task
 ├── id, title, description, done, created_at, due_date
 └── TaskList (optional, one-to-one)
      └── TaskListItem[]
           └── id, position, text, completed
```

A task holds either a plain text description **or** a checklist — not both. Switching modes in the edit form cleans up the old data automatically.

---

## Running tests

```bash
python -m pytest tests/
```

Tests use an in-memory SQLite database so there's no cleanup needed between runs.

---

## Database migrations

This project uses `db.create_all()` for simplicity. If you add columns to existing models, either:

- Delete the `.db` file and let it recreate (dev), or
- Run the `ALTER TABLE` manually against your database

For production use, drop in [Flask-Migrate](https://flask-migrate.readthedocs.io/) and swap `db.create_all()` for `flask db upgrade`.

---

## License

MIT — do whatever you want with it.