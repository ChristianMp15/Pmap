"""PinkMap backend: stores saved addresses in a database.

Run locally:   uvicorn main:app --reload
Database:      set DATABASE_URL to a PostgreSQL address on Render.
               If it is not set, a local SQLite file (pinkmap.db) is used so you can test with no setup.
"""
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///pinkmap.db")
if DATABASE_URL.startswith("postgres://"):          # Render gives this older form; SQLAlchemy wants the next one
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Web addresses allowed to call this API (your Netlify / Vercel / GitHub Pages site), comma separated.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")]
MAX_PER_DEVICE = 50

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass


class SavedAddress(Base):
    __tablename__ = "saved_addresses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)  # anonymous id of the browser
    label: Mapped[str] = mapped_column(String(60), default="")
    address: Mapped[str] = mapped_column(String(300))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(engine)


class AddressIn(BaseModel):
    label: str = Field("", max_length=60)
    address: str = Field(..., min_length=3, max_length=300)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class AddressOut(AddressIn):
    id: int


def get_db():
    with Session(engine) as db:
        yield db


def device(x_device_id: str = Header(..., min_length=8, max_length=64)):
    return x_device_id


app = FastAPI(title="PinkMap API")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/addresses", response_model=list[AddressOut])
def list_addresses(dev: str = Depends(device), db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedAddress).where(SavedAddress.device_id == dev).order_by(SavedAddress.id)).all()
    return [AddressOut(id=r.id, label=r.label, address=r.address, lat=r.lat, lon=r.lon) for r in rows]


@app.post("/addresses", response_model=AddressOut, status_code=201)
def add_address(body: AddressIn, dev: str = Depends(device), db: Session = Depends(get_db)):
    count = len(db.scalars(select(SavedAddress.id).where(SavedAddress.device_id == dev)).all())
    if count >= MAX_PER_DEVICE:
        raise HTTPException(400, f"Limit of {MAX_PER_DEVICE} saved addresses reached.")
    row = SavedAddress(device_id=dev, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return AddressOut(id=row.id, label=row.label, address=row.address, lat=row.lat, lon=row.lon)


@app.delete("/addresses/{address_id}", status_code=204)
def delete_address(address_id: int, dev: str = Depends(device), db: Session = Depends(get_db)):
    row = db.get(SavedAddress, address_id)
    if not row or row.device_id != dev:   # you can only delete your own
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)