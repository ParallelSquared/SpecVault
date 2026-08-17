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

1. `backend/app/models.py` — the SQLAlchemy column
2. `backend/app/schemas.py` — the Pydantic field on `LibraryBase` / `LibraryUpdate`
3. `frontend/src/libraryFields.js` — one registry entry, which drives the add
   form, the table column, and the filter control together
