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


class LibraryVersion(Base):
    """What a library looked like after something was done to it.

    One row per event -- catalogued, edited, deleted, restored, a path added
    -- holding a snapshot of the fields people type. Reading two neighbours
    and comparing them is what "creator: Mike -> Sarah" comes from, so the
    history needs no separate record of the change itself.

    Only the typed fields are snapshotted. Everything read from the file --
    the hash, the counts, the mod table -- is a property of the bytes, and
    those cannot change without the entry being pointed at a different file,
    which is its own event.

    *changed_by* is self-reported: there are no accounts, so it is whoever the
    browser said it was. It answers "who should I ask about this", not "who do
    I hold responsible", and it is nullable because an older browser, or a
    request made by hand, says nothing at all.
    """
    __tablename__ = "library_versions"

    id = Column(Integer, primary_key=True, index=True)
    library_id = Column(
        Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    changed_by = Column(String, nullable=True)
    # The computer the change came from: its network name where it has one,
    # otherwise its address. Not proof of anything either -- but on a shared
    # remote desktop, where one Windows account means one remembered name for
    # everybody, it is what tells "ZC did this" apart from "someone at the
    # desk ZC last used did this".
    changed_from = Column(String, nullable=True)
    event = Column(String, nullable=False)   # see routers.libraries.EVENTS
    data = Column(JSON, nullable=False)


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
    # When this entry was deleted, or NULL for one that has not been. Deleting
    # is reversible: the row stays and the catalog stops listing it. Nothing
    # here touches the library's file, which lives on the share and is only
    # ever read.
    #
    # The row staying means its paths keep the unique constraint on
    # library_paths.path, so adding the same file again finds the deleted entry
    # rather than making a second one -- and is offered it back.
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
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