from sqlalchemy import Boolean, Column, Date, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class Library(Base):
    __tablename__ = "libraries"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, nullable=False, unique=True)
    date_created = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    creator = Column(String, nullable=False)
    instrument = Column(String, nullable=True)
    acquisition_type = Column(String, nullable=True)
    species = Column(String, nullable=True)
    tags = Column(JSON, nullable=True)
    project = Column(String, nullable=True)
    finetuning = Column(String, nullable=True)
    search_algorithm = Column(String, nullable=True)
    software_version = Column(String, nullable=True)   # e.g. "2.5.0", from the creation log
    date_generated = Column(Date, nullable=True)       # when the library was built
    mbr = Column(Boolean, nullable=True)               # built with match-between-runs
    source_runs = Column(JSON, nullable=True)          # list[str], the runs it was built from
    notes = Column(Text, nullable=True)
    cell_types = Column(JSON, nullable=True)      # list[str]
    tissues = Column(JSON, nullable=True)          # list[str]
    protease = Column(String, nullable=True)
    carbamidomethylated = Column(Boolean, nullable=True)
    ptms = Column(JSON, nullable=True)              # list[str]
    mod_details = Column(JSON, nullable=True)       # list[dict], see schemas.ModDetail
    library_stats = Column(JSON, nullable=True)     # dict, see app/library_stats.py
    creation_log_path = Column(String, nullable=True)
    precursors = Column(Integer, nullable=True)
    proteins = Column(Integer, nullable=True)
    content_hash = Column(String, nullable=True, index=True)
    fasta_path = Column(String, nullable=True)
    in_silico = Column(String, nullable=True)