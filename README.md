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

### Updating

Write and test the change on your own machine, push it, and pull it on the
host. On the host, in order:

```bash
cd C:\SpecVault; git pull
```

```bash
cd C:\SpecVault\backend; .\venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
cd C:\SpecVault\frontend; npm install; npm run build
```

```bash
Restart-Service SpecVault
```

`frontend/dist` is **not in git** — the build output is gitignored, so pulling
never updates the UI. Rebuilding it is what deploys a frontend change, and
skipping that step leaves everyone on the old interface while the API is new.

Restarting is what runs any new migrations. **Back the database up first when
the update contains one**, because going back means downgrading the schema as
well as the code, and a downgrade that drops a column drops its data:

```bash
sqlite3 C:\ProgramData\SpecVault\specvault.db ".backup 'C:\ProgramData\SpecVault\before-update.db'"
```

`backend/.env` is gitignored, so the host's own database path and settings
survive every pull. `backend/share.json` **is** committed, because the share
is the same for everyone: edit it on your machine and commit it, rather than
on the host, where a pull would collide with the change. If a host ever does
need its own copy, point `SHARE_CONFIG` at one outside the repository.

The host needs Node only to build the UI. To keep the toolchain off it, run
`npm run build` on your own machine, copy `frontend/dist` across, and set
`UI_DIR` to wherever you put it.

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
   Adding it to `LibraryUpdate` is also what puts it in the history, since
   `VERSIONED_FIELDS` is read off that class.
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

**Source runs** — the raw files a library was built from — are stored the
same way when they are on the share, so each machine is shown them the way it
writes paths. They are the one kind of path **never refused**: a run on an
instrument's own disk is kept exactly as written and shown as written,
because it records where the data came from rather than a file the catalog
has to open, and a library should not be turned away because its runs moved.

To add several runs at once, select them in Explorer and **Copy as path**
(Ctrl+Shift+C on Windows 11; Option-Cmd-C on a Mac), then paste once into the
Source Runs box: a pasted block becomes one run per line, quotes stripped. A
browser cannot offer a real multi-file picker here — the file picker gives a
page a file's name and contents but never its path.

A library counts as found when **any** of its paths has the file, so one copy
being offline does not make it missing; the files panel marks which copies are
not there.

## Editing a library

The `⋯` menu on each row edits it. The edit form is the Add form — the same
one component, given a library instead of nothing — so the two can never offer
different fields or different dropdowns.

Two things are deliberately not editable there:

- **What the file says.** Precursor and protein counts, the hash, the mod
  table and the library stats are read from the file, not typed. Letting them
  be edited would mean the catalog could no longer tell a measured number from
  a typed one. The registry already marks them, with `form: false`.
- **Where the library is.** Paths are a list rather than a field, so the form
  shows them as one — every place the file is, each marked present or not,
  with **Remove** beside each. Removing one only stops SpecVault recording
  that copy; the file is not touched. The last path cannot go: an entry with
  none says nothing about where its library is, and is the shape that broke
  the listing once already.

  Removal is **not** restricted to copies whose file is missing. A path
  pasted by mistake may well point at something real, and that is exactly the
  one worth being able to take back — the history records what went either
  way.

Paths come back from the API in two spellings and only one of them is valid
input: `creation_log_path` is stored share-relative (`Libraries/report.log.txt`)
while `display_creation_log_path` is the same file written for the machine
that asked. **Send back the display one.** The stored spelling matches no
mount, so it is refused as being off the share — which is baffling, since it
is the path the catalog just handed over. `valueOf()` in `libraryFields.js` is
what picks the right one.

Protease, carbamidomethylation and PTMs *are* editable even though they are
detected, because detection is a guess and wants correcting.

## Who changed something

There are no accounts. The page header asks once who you are, keeps it in that
browser, and sends it with every request that changes a library
(`X-SpecVault-User`). The dropdown offers the creators already in the catalog,
which is what stops one person becoming `ZC`, `zc` and `Zach`.

**Changing a library that already exists is refused without one** — editing,
deleting, restoring, adding or removing a path, in the API as well as the UI.
An edit destroys the value it replaces, and that value survives only in the
history, which is worth little if half of it says "someone".

**Cataloguing a new library is the exception.** Nothing is being overwritten,
and `creator` already names a person, so a bulk import is not locked out of
the one job it has. Those rows record no name and the column stays nullable,
which is also what rows written before any of this need.

The UI asks where the change is being made rather than sending people to the
header, and carries straight on into the change once answered.

This is **self-reported and must not be read as a login**: anyone can type any
name, and nothing is kept out by it. It answers "who should I ask about this
entry", which is the question people actually have. It is also per browser, so
on a shared machine the second person inherits the first one's name — which is
why it sits in the header where a wrong name is obvious and one click to fix.

If accounts are ever added, the column is already there and already populated;
the name just stops being self-reported.

## History

Every change is recorded in `library_versions`: one row per event
(catalogued, edited, deleted, restored, path added, path removed, file
changed) holding a snapshot of the typed fields and who said they did it. **Show history** on a
row compares neighbouring snapshots and shows what changed.

Snapshots rather than a list of changes: reverting is then a single PATCH from
a stored row, and a diff is cheap to compute from two of them. Only the typed
fields are kept — everything read from the file is a property of the bytes,
which cannot change unless the entry is pointed at a different file, and that
is recorded as its own kind of event.

A PATCH that changes nothing records nothing; a history full of empty saves is
one nobody reads. The fields covered are read off `LibraryUpdate`, so a new
field is versioned without anyone having to remember this file.

Lists say what came and went (`Tags: + reprocessed`) instead of repeating
themselves (`demo → demo, reprocessed`), which matters most for paths, where
the whole list twice is unreadable.

## Finding a library by its contents

**Content Hash** under *More filters* takes a file from anywhere the person can
open one — their own Desktop as much as the share — and lists the catalogued
libraries with exactly the same bytes, whatever they are called or wherever
they have been moved to.

The hashing happens **in the browser**, in `src/hashFile.js`. The server could
not do it: it can only open paths on its own disks, so a path to someone's
Desktop would be looked for on the host's. The file never leaves the person's
machine; only its SHA-256 is used to search.

`hash-wasm` does the hashing rather than the browser's own `crypto.subtle`,
which only exists over HTTPS or on localhost — SpecVault is reached over plain
HTTP. It also hashes in 8 MB pieces, where `crypto.subtle` wants the whole
file in memory, and libraries run to gigabytes.

`POST /libraries/hash-file` still exists and still refuses paths off the
share; the UI no longer calls it.

## Deleting a library

The `⋯` menu on each row deletes it, behind a confirmation. Deleting is a
catalog operation: **nothing on the share is touched**, because SpecVault only
ever reads library files.

It is also reversible. The row stays, marked with the day it went, and stops
being listed — so it is gone from the table, the total, `GET /libraries/{id}`
and the dropdown options, but keeps its metadata, its hash and its paths.

Keeping the paths is what makes it recoverable without a "deleted libraries"
screen. They stay subject to the unique constraint, so adding the same file
again matches the deleted entry rather than starting a second one. That is the
way back from a wrong click: add the file again.

**Auto-fill says so, not Save.** It has just read and hashed the file, so it
can say the catalog already holds it while the form is still empty — rather
than after it has all been filled in, which is where the news used to arrive.

## What counts as a library

Two things, both read from the header alone — no data is loaded to decide.

**Precursors**: a `Modified.Sequence` and a `Precursor.Charge` column (or the
Spectronaut-style spellings `ModifiedPeptide` / `PrecursorCharge`). That is
what a precursor is; without both, the file describes something else.

**Fragments**: at least one of the columns `library_stats` reads —
`Fragment.Type`, `Fragment.Series.Number`, `Fragment.Charge`,
`Fragment.Loss.Type`, `Product.Mz`, or their no-dot spellings. This is the
check that matters, and the reason is `report.parquet`.

A **DIA-NN report describes the same precursors a library does**, so it
carries every precursor column a library carries. It used to be accepted with
no warning at all and plausible-looking counts — an entry that looked right
and was a search result. What a report has not got is fragments, because it
records what was found in a run rather than what to look for. Where a file
also has `Run`, `Q.Value` or `Precursor.Quantity`, the refusal says so by
name, since knowing it is a report tells you which file to go and find.

`Protein.Group` and `Stripped.Sequence` stay warnings rather than refusals —
the second is derivable from the modified sequence, and neither decides
whether the thing is a library.

Formats are still decided by extension alone: `.tsv`, `.txt`, `.csv`,
`.parquet`. `.speclib` is not among them, so DIA-NN's native binary libraries
are refused — worth revisiting, and deliberately not special-cased now.

### Column spellings

Every tool names these differently, and the aliases come from **JMod's own
table** — it reads DIA-NN, JMod, Spectronaut and FragPipe libraries, so it is
the list that has actually met them.

| | DIA-NN | Spectronaut | FragPipe |
|---|---|---|---|
| sequence | `Modified.Sequence` | `ModifiedPeptide` | `ModifiedPeptideSequence` |
| protein | `Protein.Group` | `ProteinGroup` | `ProteinId` |
| fragment m/z | `Product.Mz` | `FragmentMz` | `ProductMz` |
| fragment number | `Fragment.Series.Number` | `FragmentNumber` | `FragmentSeriesNumber` |
| intensity | — | `RelativeIntensity` | `LibraryIntensity` |

`tests/test_dialects.py` writes one library per tool and checks each is
accepted, counted and read. A spelling dropped from the table turns a real
library into "not a spectral library" — a confident refusal of a perfectly
good file — so the guard matters more than the usual test.

FragPipe and Spectronaut also wrap each sequence in `_` terminus markers —
`_[527.18773]PEPTIDEK`. These are stripped on read, the outer ones only: an
N-terminal label is recognised by sitting at the start of the sequence, so
behind the `_` every one was dropped, while mod names such as `H_DM_mod`
contain underscores of their own that have to survive.

The first alias present wins, which is why the dotted DIA-NN names lead.
Intensity columns are not read for anything yet; they are listed because they
are evidence a file holds fragment rows.

## A file that cannot be read

Two cases, with two different answers.

**No file at that path is refused outright**, with no way to confirm past it.
The hash is a library's identity — how the same file is recognised somewhere
else, how a duplicate is matched, how a deleted entry is offered back, and
what a check that a library has not been altered compares against. Nothing
re-reads a file once it is catalogued, so an entry saved without a hash can
never acquire one: a row that looks like a library and is not one.

**A file that will not parse is a question, not a refusal.** It has been read
— it is really there and it has a hash, so the entry can still be recognised
later. What it costs is everything the library itself would have said, so the
save names that and asks. A format SpecVault does not know yet is not the same
as a file that is gone, and `save_unreadable: true` is the answer.

Once catalogued, a library whose file later moves or goes keeps its entry and
everything read from it. The rule is about cataloguing, not about staying
catalogued — a library that moves is something to notice, not something to
lose.

Saving then offers two ways back, because the entry's old metadata and what
has just been typed are both plausibly right:

| | |
|---|---|
| **Restore with these details** | the form replaces what the entry held — for somebody who deleted it *because* it was catalogued wrongly |
| **Restore as it was** | the entry comes back untouched |

**The file is read again either way.** Counts, the mod table and the library
details are worked out from the file rather than brought back, so a library
catalogued before an improvement to the reading picks it up on restore. Only
a file with the same bytes is read, and if none can be reached the stored
reading is kept rather than emptied.

**The path is recorded either way.** It says where the file is now rather than
what the entry should claim, and a library is usually being added again
because something about it moved — restoring it pointing only at somewhere
the file has left would be no use. If the old path is now stale, remove it
from the edit form.

`POST /libraries/{id}/restore` does the same thing directly, for an entry whose
file has since moved or gone.

A deleted entry's history stays readable at `/libraries/{id}/history`, which
is where "who took this out, and when" is answered — the entry itself is a 404
by then.

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
