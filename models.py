from passlib.hash import sha256_crypt
from sqlalchemy import Column, DateTime, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship
from db import db_session

class Base(DeclarativeBase):
    pass

#########################################
#sql table names must be in https://en.wikipedia.org/wiki/Snake_case
class Users(Base): 
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True) #automatically serial (auto-assigned, incremented value) with primary_key
    username = Column(String(50), nullable=False, unique=True)
    password = Column(String(100), nullable=False)
    isAdmin = Column(Boolean, default=False)
    isLoggedIn = Column(Boolean, default=False)
    roles = Column(String(50))
    created_on = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login = Column(DateTime(timezone=True), onupdate=func.now())
    def check_password(self, pwd):
        return sha256_crypt.verify(pwd, self.password)

class Columns(Base): 
    __tablename__ = 'columns'
    id = Column(Integer, primary_key=True)
    field = Column(Integer, nullable=False)
    name = Column(String(50), nullable=False)
    conversion = Column(String(50), default=False)

    #foreigh key to WoofList
    woof_id = Column(Integer, ForeignKey('woofs.woofId'))
    #relationship back to woof table
    woof = relationship('Woofs', back_populates='columns')
    # Enforcing uniqueness on the combination of `woof_id` and `field`
    __table_args__ = (
        UniqueConstraint('woof_id', 'field', name='uix_woof_field'),
    )

class Woofs(Base): 
    __tablename__ = 'woofs'
    id = Column('woofId', Integer, primary_key=True)
    url = Column(String(100), nullable=False, unique=True)
    name = Column(String(50), nullable=False)
    latest_seq_no = Column('latestSeqNo', Integer)

    #relationship to column data
    columns = relationship('Columns', back_populates='woof', cascade="all, delete-orphan") #cascade says delete columns entries if we delete this woof
    woofdata = relationship('WoofData', back_populates='woof', cascade="all, delete-orphan") #cascade says delete columns entries if we delete this woof
    def __repr__(self):
        return f"<Woofs(id={self.id}, url={self.url}, name={self.name}, latest={self.latest_seq_no}>"

class WoofData(Base): 
    __tablename__ = 'woofdata'
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    seqno = Column(Integer, nullable=False)
    data = Column(String(1048576), nullable=False)

    #foreigh key to WoofList
    woof_id = Column(Integer, ForeignKey('woofs.woofId'))
    #relationship back to woof table
    woof = relationship('Woofs', back_populates='woofdata')
    __table_args__ = (
        UniqueConstraint('woof_id', 'seqno', name='uix_woof_seqno'),
        Index('ix_woofdata_woof_seqno', 'woof_id', 'seqno'),
        Index('ix_woofdata_woof_ts', 'woof_id', 'ts'),
    )
    def __repr__(self):
        return f"<WoofData(id={self.id}, woofid={self.woof_id}, ts={self.ts} ({self.ts}), data={self.data}, seqno={self.seqno}>"

class State(Base): 
    __tablename__ = 'appstate'
    key = Column(String(50), nullable=False, primary_key=True)
    val = Column(String(100), nullable=False)


