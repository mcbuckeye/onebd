"""SQLAlchemy models for the Cortellis Deals database."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float,
    ForeignKey, Table, Enum, UniqueConstraint, Index, create_engine
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, Session
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from pgvector.sqlalchemy import Vector
import enum


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class DealStatus(enum.Enum):
    ACTIVE = "Active"
    TERMINATED = "Terminated"
    COMPLETED = "Completed"
    PENDING = "Pending"


class CompanyType(enum.Enum):
    PHARMA = "Pharma"
    BIOTECH = "Biotech"
    DEVICE = "Device"
    DIAGNOSTICS = "Diagnostics"
    OTHER = "Other"


class CompanyRole(enum.Enum):
    PRINCIPAL = "Principal"
    PARTNER = "Partner"


class TerritoryType(enum.Enum):
    INCLUDED = "Included"
    EXCLUDED = "Excluded"


class ActionType(enum.Enum):
    PRIMARY = "Primary"
    SECONDARY = "Secondary"


# Junction Tables
deal_indications = Table(
    "deal_indications",
    Base.metadata,
    Column("deal_id", Integer, ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True),
    Column("indication_id", Integer, ForeignKey("indications.id", ondelete="CASCADE"), primary_key=True),
    Column("is_principal", Boolean, default=False),
)

deal_technologies = Table(
    "deal_technologies",
    Base.metadata,
    Column("deal_id", Integer, ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True),
    Column("technology_id", Integer, ForeignKey("technologies.id", ondelete="CASCADE"), primary_key=True),
    Column("is_principal", Boolean, default=False),
)

deal_patents = Table(
    "deal_patents",
    Base.metadata,
    Column("deal_id", Integer, ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True),
    Column("patent_id", String(50), ForeignKey("patents.id", ondelete="CASCADE"), primary_key=True),
)


class Company(Base):
    """Company lookup table."""
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    company_type: Mapped[Optional[str]] = mapped_column(String(50))
    hq_location: Mapped[Optional[str]] = mapped_column(String(100))

    # Relationships
    deal_associations: Mapped[List["DealCompany"]] = relationship(back_populates="company")

    __table_args__ = (
        Index("ix_companies_name", "name"),
    )


class DealCompany(Base):
    """Association table linking deals to companies with role."""
    __tablename__ = "deal_companies"

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)  # Principal or Partner

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="company_associations")
    company: Mapped["Company"] = relationship(back_populates="deal_associations")


class Indication(Base):
    """Medical indications."""
    __tablename__ = "indications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    deals: Mapped[List["Deal"]] = relationship(secondary=deal_indications, back_populates="indications")

    __table_args__ = (
        Index("ix_indications_name", "name"),
    )


class Technology(Base):
    """Technology types."""
    __tablename__ = "technologies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    deals: Mapped[List["Deal"]] = relationship(secondary=deal_technologies, back_populates="technologies")


class Action(Base):
    """Mechanisms of action."""
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    deal_actions: Mapped[List["DealAction"]] = relationship(back_populates="action")


class DealAction(Base):
    """Association table for deals and actions with type (primary/secondary)."""
    __tablename__ = "deal_actions"

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(20), primary_key=True)  # Primary or Secondary

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="action_associations")
    action: Mapped["Action"] = relationship(back_populates="deal_actions")


class Territory(Base):
    """Geographic territories."""
    __tablename__ = "territories"

    id: Mapped[str] = mapped_column(String(10), primary_key=True)  # e.g., "WO", "US", "JP"
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Relationships
    deal_territories: Mapped[List["DealTerritory"]] = relationship(back_populates="territory")


class DealTerritory(Base):
    """Association table for deals and territories (included/excluded)."""
    __tablename__ = "deal_territories"

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True)
    territory_id: Mapped[str] = mapped_column(ForeignKey("territories.id", ondelete="CASCADE"), primary_key=True)
    territory_type: Mapped[str] = mapped_column(String(20), primary_key=True)  # Included or Excluded

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="territory_associations")
    territory: Mapped["Territory"] = relationship(back_populates="deal_territories")


class Drug(Base):
    """Drug information."""
    __tablename__ = "drugs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_display: Mapped[str] = mapped_column(String(1000), nullable=False)
    phase_highest_start_id: Mapped[Optional[str]] = mapped_column(String(10))
    phase_highest_start: Mapped[Optional[str]] = mapped_column(String(100))
    phase_highest_now_id: Mapped[Optional[str]] = mapped_column(String(10))
    phase_highest_now: Mapped[Optional[str]] = mapped_column(String(100))

    # Relationships
    deal_drugs: Mapped[List["DealDrug"]] = relationship(back_populates="drug")


class DealDrug(Base):
    """Association table for deals and drugs."""
    __tablename__ = "deal_drugs"

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True)
    drug_id: Mapped[int] = mapped_column(ForeignKey("drugs.id", ondelete="CASCADE"), primary_key=True)

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="drug_associations")
    drug: Mapped["Drug"] = relationship(back_populates="deal_drugs")


class Patent(Base):
    """Patent information."""
    __tablename__ = "patents"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g., "PA3002153"
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    deals: Mapped[List["Deal"]] = relationship(secondary=deal_patents, back_populates="patents")


class TherapyArea(Base):
    """Therapy areas."""
    __tablename__ = "therapy_areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Relationships
    deals: Mapped[List["Deal"]] = relationship(back_populates="therapy_area")


class Deal(Base):
    """Main deal records."""
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    deal_type: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    is_optional: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_merger_acquisition: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_contract: Mapped[Optional[bool]] = mapped_column(Boolean)

    # Therapy Area
    therapy_area_id: Mapped[Optional[int]] = mapped_column(ForeignKey("therapy_areas.id"))
    therapy_area: Mapped[Optional["TherapyArea"]] = relationship(back_populates="deals")

    # Dates
    date_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_event_most_recent: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_change_last: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_added: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Summary
    summary: Mapped[Optional[str]] = mapped_column(Text)

    # Category fields
    agreement_type: Mapped[Optional[str]] = mapped_column(String(200))
    asset_type: Mapped[Optional[str]] = mapped_column(String(200))
    transaction_type: Mapped[Optional[str]] = mapped_column(String(200))

    # Phase info
    phase_highest_start: Mapped[Optional[str]] = mapped_column(String(100))
    phase_highest_now: Mapped[Optional[str]] = mapped_column(String(100))

    # Raw data for complex nested structures
    category_raw: Mapped[Optional[dict]] = mapped_column(JSONB)
    cross_references_raw: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Relationships
    company_associations: Mapped[List["DealCompany"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    indications: Mapped[List["Indication"]] = relationship(secondary=deal_indications, back_populates="deals")
    technologies: Mapped[List["Technology"]] = relationship(secondary=deal_technologies, back_populates="deals")
    action_associations: Mapped[List["DealAction"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    territory_associations: Mapped[List["DealTerritory"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    drug_associations: Mapped[List["DealDrug"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    patents: Mapped[List["Patent"]] = relationship(secondary=deal_patents, back_populates="deals")
    finance_summary: Mapped[Optional["DealFinanceSummary"]] = relationship(back_populates="deal", uselist=False, cascade="all, delete-orphan")
    timeline_events: Mapped[List["DealTimelineEvent"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    contracts: Mapped[List["DealContract"]] = relationship(back_populates="deal", cascade="all, delete-orphan")
    ma_summary: Mapped[Optional["DealMASummary"]] = relationship(back_populates="deal", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_deals_status", "status"),
        Index("ix_deals_date_start", "date_start"),
        Index("ix_deals_date_added", "date_added"),
        Index("ix_deals_date_change_last", "date_change_last"),
    )


class DealFinanceSummary(Base):
    """High-level financial summary for a deal."""
    __tablename__ = "deal_finance_summary"

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True)

    # Total Paid
    total_paid_amount: Mapped[Optional[float]] = mapped_column(Float)
    total_paid_currency: Mapped[Optional[str]] = mapped_column(String(10))
    total_paid_unit: Mapped[Optional[str]] = mapped_column(String(20))
    total_paid_disclosure_status: Mapped[Optional[str]] = mapped_column(String(50))

    # Total Projected Current
    total_projected_current_amount: Mapped[Optional[float]] = mapped_column(Float)
    total_projected_current_currency: Mapped[Optional[str]] = mapped_column(String(10))
    total_projected_current_unit: Mapped[Optional[str]] = mapped_column(String(20))
    total_projected_current_disclosure_status: Mapped[Optional[str]] = mapped_column(String(50))

    # Total Projected Signing
    total_projected_signing_amount: Mapped[Optional[float]] = mapped_column(Float)
    total_projected_signing_currency: Mapped[Optional[str]] = mapped_column(String(10))
    total_projected_signing_unit: Mapped[Optional[str]] = mapped_column(String(20))
    total_projected_signing_disclosure_status: Mapped[Optional[str]] = mapped_column(String(50))

    # Raw finance detail for complex nested payment structures
    finance_detail_raw: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="finance_summary")


class DealTimelineEvent(Base):
    """Timeline events for a deal."""
    __tablename__ = "deal_timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"))
    event_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    event_type: Mapped[Optional[str]] = mapped_column(String(100))
    stage_id: Mapped[Optional[str]] = mapped_column(String(10))
    stage: Mapped[Optional[str]] = mapped_column(String(100))
    stage_notes: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)

    # Payments as JSON for complex nested structure
    payments_to_principal: Mapped[Optional[dict]] = mapped_column(JSONB)
    payments_to_partner: Mapped[Optional[dict]] = mapped_column(JSONB)
    drugs: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="timeline_events")

    __table_args__ = (
        Index("ix_deal_timeline_events_deal_id", "deal_id"),
        Index("ix_deal_timeline_events_date", "event_date"),
    )


class DealContract(Base):
    """Contract documents associated with a deal."""
    __tablename__ = "deal_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Contract ID from API
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"))
    contract_types: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated types
    has_pdf: Mapped[bool] = mapped_column(Boolean, default=False)
    has_text: Mapped[bool] = mapped_column(Boolean, default=False)
    date_filing: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_contract: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    pdf_file_path: Mapped[Optional[str]] = mapped_column(String(500))
    text_file_path: Mapped[Optional[str]] = mapped_column(String(500))
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="contracts")
    content: Mapped[Optional["ContractContent"]] = relationship(back_populates="contract", uselist=False)
    chunks: Mapped[List["ContractChunk"]] = relationship(back_populates="contract")

    __table_args__ = (
        Index("ix_deal_contracts_deal_id", "deal_id"),
    )


class DealMASummary(Base):
    """M&A summary for applicable deals."""
    __tablename__ = "deal_ma_summary"

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True)
    company_type: Mapped[Optional[str]] = mapped_column(String(100))
    business_description: Mapped[Optional[str]] = mapped_column(Text)
    prior_relationship: Mapped[Optional[bool]] = mapped_column(Boolean)
    overall_product_phase_highest: Mapped[Optional[str]] = mapped_column(String(100))
    ownership: Mapped[Optional[str]] = mapped_column(String(50))
    attitude: Mapped[Optional[str]] = mapped_column(String(50))
    top_3_products: Mapped[Optional[str]] = mapped_column(Text)
    major_investors: Mapped[Optional[str]] = mapped_column(Text)

    # M&A Financial
    cash_at_acquisition: Mapped[Optional[float]] = mapped_column(Float)
    cash_at_acquisition_currency: Mapped[Optional[str]] = mapped_column(String(10))
    price_per_share: Mapped[Optional[float]] = mapped_column(Float)
    price_per_share_currency: Mapped[Optional[str]] = mapped_column(String(10))
    total_revenue_year_prior: Mapped[Optional[float]] = mapped_column(Float)
    total_shares_outstanding: Mapped[Optional[float]] = mapped_column(Float)
    closing_price_day_one: Mapped[Optional[float]] = mapped_column(Float)
    closing_price_day_five: Mapped[Optional[float]] = mapped_column(Float)
    closing_price_day_thirty: Mapped[Optional[float]] = mapped_column(Float)

    # Relationships
    deal: Mapped["Deal"] = relationship(back_populates="ma_summary")


class ContractContent(Base):
    """Full text content of contracts for search."""
    __tablename__ = "contract_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("deal_contracts.id", ondelete="CASCADE"))
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tsvector: Mapped[Optional[str]] = mapped_column(TSVECTOR)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    contract: Mapped["DealContract"] = relationship(back_populates="content")
    deal: Mapped["Deal"] = relationship()

    __table_args__ = (
        Index("ix_contract_content_tsvector", "content_tsvector", postgresql_using="gin"),
        Index("ix_contract_content_deal_id", "deal_id"),
    )


class ContractChunk(Base):
    """Chunked contract text with embeddings for RAG."""
    __tablename__ = "contract_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(Integer, ForeignKey("deal_contracts.id", ondelete="CASCADE"))
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(1536))  # OpenAI text-embedding-3-small dimension
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    contract: Mapped["DealContract"] = relationship(back_populates="chunks")
    deal: Mapped["Deal"] = relationship()

    __table_args__ = (
        Index("ix_contract_chunks_embedding", "embedding", postgresql_using="ivfflat", postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_contract_chunks_deal_id", "deal_id"),
        UniqueConstraint("contract_id", "chunk_index", name="uq_contract_chunk"),
    )


class SyncLog(Base):
    """Track synchronization runs."""
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sync_type: Mapped[str] = mapped_column(String(20))  # "full" or "incremental"
    status: Mapped[str] = mapped_column(String(20))  # "running", "completed", "failed"
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    contracts_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_sync_log_started_at", "started_at"),
    )


def create_tables(engine):
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


def get_engine(connection_string: str):
    """Create a database engine."""
    return create_engine(connection_string, echo=False)
