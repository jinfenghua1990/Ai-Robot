from sqlalchemy import Column, Integer, String, Date, Numeric, DateTime, UniqueConstraint, func
from db.connection import Base

class SectorFlow(Base):
    __tablename__ = "sector_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    sector = Column(String(50), nullable=False, index=True)
    money_inflow = Column(Numeric(18, 2))
    money_outflow = Column(Numeric(18, 2))
    net_flow = Column(Numeric(18, 2))
    rise_ratio = Column(Numeric(6, 2))
    limit_up_count = Column(Integer, default=0)
    avg_chg = Column(Numeric(6, 2))
    leader_stock = Column(String(20))
    leader_strength = Column(Numeric(6, 2))
    heat_score = Column(Numeric(8, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "sector", name="uq_sector_date"),)

class StockFlow(Base):
    __tablename__ = "stock_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    sector = Column(String(50), index=True)
    net_inflow = Column(Numeric(18, 2))
    main_force_inflow = Column(Numeric(18, 2))
    retail_flow = Column(Numeric(18, 2))
    price_chg = Column(Numeric(6, 2))
    volume_change = Column(Numeric(10, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_stock_date"),)

class LeaderLifecycle(Base):
    __tablename__ = "leader_lifecycle"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    sector = Column(String(50))
    stage = Column(String(10), nullable=False)
    strength = Column(Numeric(6, 2))
    change_rate = Column(Numeric(6, 2))
    consecutive_days = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_leader_date"),)
