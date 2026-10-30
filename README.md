# SpecVault

A catalog for spectral libraries. Register a library file once, and SpecVault
records where it lives, who made it, and what's in it — then lets you search
across all of them.

Point it at a DIA-NN-style library (`.tsv`, `.csv`, `.parquet`) and it will read
the file and fill in precursor and protein counts, the likely protease, whether
cysteines are carbamidomethylated, and any UniMod PTMs it finds. It also stores a
SHA-256 of the file contents, so you can identify a library you already have by
hashing it — even if it's been renamed or moved.

## Layout

```
SpecVault/
├── backend/     FastAPI + SQLAlchemy API, Polars-based file analysis
└── frontend/    React 19 + Vite UI
```

## Running it

Two processes, two terminals.

**Backend** (http://127.0.0.1:8000, docs at `/docs`):

```bash
cd backend
python -m venv venv
venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

**Frontend** (http://localhost:5173):

```bash
cd frontend
npm install
npm run dev
```

## Configuration

| File | Variable | Default |
|---|---|---|
| `backend/.env` | `DATABASE_URL` | `sqlite:///./specvault.db` |
| `frontend/.env` | `VITE_API_BASE` | `http://127.0.0.1:8000` |

Both are gitignored; each directory has a committed `.env.example` to copy.

The backend defaults to SQLite, which needs no setup

## Adding a field

Library metadata fields are declared in one place per tier:

1. `backend/app/models.py` — the SQLAlchemy column. Nullable: every library
   already in the catalog has nothing for it.
2. `backend/app/schemas.py` — the Pydantic field, on `LibraryBase` *and* on
   `LibraryUpdate`. `LibraryUpdate` is a flat class rather than a subclass, so
   that PATCH can tell "not sent" from "set to nothing" — which means a field
   added only to `LibraryBase` saves on create and is quietly dropped on edit.
3. `frontend/src/libraryFields.js` — one registry entry, which drives the add
   form, the table column, and the filter control together
4. `backend/app/routers/libraries.py` — for a `combobox` or `multicombobox`,
   the field's name in `simple_fields` or `list_fields` in `/options`. Without
   it the field still works, but its dropdown never offers what other libraries
   already use, and one value ends up spelled five ways.
5. a migration, so the column reaches databases that already exist:

```bash
cd backend
alembic revision --autogenerate -m "Add <field>"
```

Read what it generated before committing it — autogenerate is a good first
draft, not an answer. It cannot see a rename in particular: renaming a column
comes out as a drop and an add, which discards that column's data, and wants a
hand-written `batch_op.alter_column(..., new_column_name=...)` instead.

`tests/test_migrations.py` fails if you skip step 5, and names the column.

## Migrations

The schema is owned by Alembic, in `backend/migrations/`. The server upgrades
the database to the newest migration at startup (`app/migrate.py`), so
deploying is "update the code, restart" with no separate migration step to
forget.

`Base.metadata.create_all()` is deliberately not used. It creates missing
tables and silently leaves existing ones alone, so it adds no column to a
database that already has the table — every database after the first run. A
catalog built that way before migrations existed is detected at startup and
stamped at the baseline rather than rebuilt; its rows are untouched.

| Command (from `backend/`) | |
|---|---|
| `alembic current` | which migration this database is on |
| `alembic history` | the chain |
| `alembic upgrade head` | upgrade by hand (startup does this anyway) |
| `alembic downgrade -1` | step back one |

Migrations run against whatever `DATABASE_URL` the app itself would use, so
there is no second place to keep the address in step.
