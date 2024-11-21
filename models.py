from passlib.hash import sha256_crypt
from sqlalchemy import Column, DateTime, Integer, String, Boolean, ForeignKey
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
    created_on = Column(DateTime, nullable=False, server_default=func.now())
    last_login = Column(DateTime, onupdate=func.now())
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


