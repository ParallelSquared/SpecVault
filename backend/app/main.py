import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import migrate
from .routers import libraries

# Migrations, not create_all(): see app/migrate.py for why the difference
# matters once the catalog holds data that cannot be rebuilt.
migrate.run()

app = FastAPI(title="SpecVault API")

# Only when the UI is served from somewhere other than this server. It is not,
# in either of the ways SpecVault runs: deployed, one process serves the API
# and the built UI together; in development, Vite proxies /libraries here, so
# the browser sees one origin both times. Set CORS_ORIGINS (comma separated)
# if you serve the UI from its own host.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],  # or the browser cannot read it
    )

app.include_router(libraries.router)

# The built UI, served by this same process. Mounted last and at "/", because
# a mount there answers everything not already claimed -- so /libraries and
# /docs have to be registered first.
#
# Missing in development, where Vite serves the UI instead; the API then runs
# on its own and this is simply skipped.
UI_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "dist",
)
UI_DIR = os.getenv("UI_DIR", UI_DIR)

if os.path.isdir(UI_DIR):
    # html=True serves index.html for "/", which is the whole UI: it has no
    # client-side routing, so there are no other pages to fall back for.
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
