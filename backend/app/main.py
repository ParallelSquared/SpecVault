from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import migrate
from .routers import libraries

# Migrations, not create_all(): see app/migrate.py for why the difference
# matters once the catalog holds data that cannot be rebuilt.
migrate.run()

app = FastAPI(title="SpecVault API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],  # or the browser cannot read it
)

app.include_router(libraries.router)