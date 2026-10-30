from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class LibraryPath(Base):
    """One place a library's file is. A library has at least one.

    The same file is often copied -- kept beside the runs it came from and
    again in a shared folder -- and those copies are one library, not several.
    Rather than a second entry per copy, the entry grows another path.

    *path* is unique across the whole table, not per library: a path names one
    file, so it can only belong to one entry, and trying to record it twice is
    caught here rather than producing two entries that disagree.
    """
    __tablename__ = "library_paths"

    id = Column(Integer, primary_key=True, index=True)
    library_id = Column(
        Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path = Column(String, nullable=False, unique=True)


class Library(Base):
    __tablename__ = "libraries"

    id = Column(Integer, primary_key=True, index=True)
    # Ordered by id, so the first is the one the library was catalogued at --
    # the copy whose file was read for the counts, hash and mod table.
    # selectin: the list is wanted for every library in every listing, and
    # loading it per row turned one query into one per library.
    paths = relationship(
        "LibraryPath",
        cascade="all, delete-orphan",
        order_by="LibraryPath.id",
        lazy="selectin",
    )
    date_created = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    creator = Column(String, nullable=False)
    instrument = Column(String, nullable=True)
    acquisition_type = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
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

    @property
    def path(self) -> str:
        """Where the library was catalogued: the first of its paths.

        Read-only on purpose. Everything that opens the file -- the hash, the
        counts, the mod table -- works from this one, while the rest are other
        places the same bytes are known to be.
        """
        return self.paths[0].path if self.paths else None