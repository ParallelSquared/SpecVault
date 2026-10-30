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

## Running it in development

Two processes, two terminals. Vite proxies `/libraries` to the backend, so the
browser sees one origin — the same as deployed, and no CORS either way.

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

## Deploying it

One process, one port. The backend serves the built UI from `frontend/dist`
alongside the API, so there is no second server, no CORS, and no hostname
baked into the bundle — the same build works at `http://specvault`, at an IP,
or anywhere else it is reached from.

```bash
cd frontend && npm install && npm run build
```

```bash
cd backend && venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 80
```

Rebuild the UI whenever the frontend changes; the backend picks it up from
disk with no rebuild of its own. Migrations run at startup, so deploying is
"update the code, rebuild the UI, restart".

### What the host needs

**A machine that stays up and that nobody logs into casually.** Any PC on the
PTI network will do — people reach SpecVault by URL, so it is not a Guacamole
session and the host does not have to be a machine anyone signs into. If
someone does, a reboot or a sign-out takes the catalog down with it.

**A stable address.** A DNS name or a static IP reservation; a DHCP address
that changes breaks everyone's bookmark.

**An inbound firewall rule** for the port — Windows Firewall blocks it by
default:

```bash
netsh advfirewall firewall add rule name="SpecVault" dir=in action=allow protocol=TCP localport=80
```

**A service account that can read the share.** Run it as a Windows service
(NSSM, or a scheduled task at boot) so it survives reboots and sign-outs — but
a service running as `LocalSystem` reaches the network as the *machine*
account, and mapped drives do not exist for services at all. So:

- run the service as a domain account with read access to `\\PTI\Lab`
- set `server_root` in `share.json` to the UNC path, never `L:\`

This is the mistake that works perfectly when tested by hand and then fails
for every library once it is a service.

**One process, not several.** Do not use `uvicorn --workers`. The analysis
caches live in the process: Auto-fill starts hashing and reading a library and
Save collects the result, so with two workers a Save landing on the other one
re-reads the whole file. It still works, just slowly — on a 28-million-row
library, noticeably so. One process serves 25 people reading a catalog
comfortably.

### Backups

The database is a single file. Copy it on a schedule, to the share rather than
beside itself:

```bash
sqlite3 C:\ProgramData\SpecVault\specvault.db ".backup '\\PTI\Lab\Backups\specvault.db'"
```

`.backup` rather than copying the file: it is consistent even while the server
is writing. **Keep the database itself on the host's local disk**, never on the
share — SQLite over SMB corrupts.

## Configuration

| File | Variable | Default |
|---|---|---|
| `backend/.env` | `DATABASE_URL` | `sqlite:///./specvault.db` |
| `backend/.env` | `SHARE_CONFIG` | `backend/share.json` |
| `backend/.env` | `UI_DIR` | `frontend/dist` |
| `backend/.env` | `CORS_ORIGINS` | unset — not needed either way |
| `frontend/.env` | `VITE_DEV_API` | `http://127.0.0.1:8000` (dev proxy only) |
| `frontend/.env` | `VITE_API_BASE` | unset — same origin |

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

## The lab share

The same library file has a different path on every machine — `L:\Libraries\foo.tsv`
on a Windows box with the drive mapped, `\\PTI\Lab\Libraries\foo.tsv` on one
without, `/Volumes/Lab/Libraries/foo.tsv` on a Mac, `/mnt/lab/Libraries/foo.tsv`
on Linux. There is no absolute path that works everywhere, so the catalog does
not store one: it stores `Libraries/foo.tsv`, the path *within* the share, and
each side renders it the way its own machine writes paths.

A library can be in more than one place. The same file is often copied — kept
beside the runs it came from and again in a shared folder — and those copies
are one library, not several, so an entry holds a list of paths. Saving a file
the catalog already has (same SHA-256) is refused with the entry it matched,
and the path can be added to that entry instead. A path belongs to exactly one
entry, enforced by a unique constraint across every path in the catalog.

A library counts as found when **any** of its paths has the file, so one copy
being offline does not make it missing; the files panel marks which copies are
not there.

Three things follow from storing paths share-relative:

- Adding the same library from a Mac and from Windows produces the same stored
  path, so it is one entry rather than two.
- Everyone is shown — and copies — paths their own machine understands. The
  browser's `User-Agent` decides which.
- A path matching none of the known mounts is not on the share, so it is
  refused. A catalog entry only its author can open claims the library is
  available to everyone when it is not.

`backend/share.json` says how each machine reaches the share:

```json
{
  "server_root": "\\\\PTI\\Lab",
  "mounts": [
    { "os": "windows", "prefix": "\\\\PTI\\Lab" },
    { "os": "windows", "prefix": "L:" },
    { "os": "mac", "prefix": "/Volumes/Lab" },
    { "os": "linux", "prefix": "/mnt/lab" }
  ],
  "require_on_share": true
}
```

| Key | |
|---|---|
| `server_root` | how **this server** reaches the share. Use the UNC path — a mapped drive belongs to a logged-in session and does not exist for a Windows service |
| `mounts` | every prefix someone might paste, and which flavour to show back. Where a flavour has several, **the first is the one displayed** |
| `require_on_share` | `false` allows libraries outside the share. Leave it `true` |

Check the `mac` and `linux` prefixes against how people actually mount the
share. A wrong one does not fail quietly — it rejects those users' paths as
not being on the share.

Without `share.json`, or with a malformed one, the catalog stores paths exactly
as they are typed and refuses nothing, which is how it behaved before any of
this existed. `SHARE_CONFIG` points somewhere else if you need it to.

**Put `share.json` in place before the server's first start on a catalog that
already holds libraries.** The migration that converts existing paths can only
run once; started without a share it would have nothing to convert against,
and the paths would stay absolute for good. Rather than let that happen
quietly it refuses to run, naming what to do — an empty catalog has nothing to
lose and starts normally either way.

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
