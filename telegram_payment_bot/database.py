import peewee as pw
from config import DB_FILE
import datetime

db = pw.SqliteDatabase(DB_FILE)

class BaseModel(pw.Model):
    class Meta:
        database = db

class Admin(BaseModel):
    user_id = pw.BigIntegerField(unique=True)

class Chat(BaseModel):
    chat_id = pw.BigIntegerField(unique=True)
    title = pw.CharField()
    amount = pw.FloatField()
    currency = pw.CharField(default="USDT")
    duration_days = pw.IntegerField()

class UserSettings(BaseModel):
    user_id = pw.BigIntegerField(unique=True, primary_key=True)
    language = pw.CharField(default="en")

class User(BaseModel):
    user_id = pw.BigIntegerField()
    chat = pw.ForeignKeyField(Chat, backref='users')
    expires_at = pw.DateTimeField()

    class Meta:
        primary_key = pw.CompositeKey('user_id', 'chat')

class Payment(BaseModel):
    tx_hash = pw.CharField(unique=True)
    user = pw.ForeignKeyField(User, backref='payments')
    amount = pw.FloatField()
    paid_at = pw.DateTimeField(default=datetime.datetime.now)

def initialize_db():
    """Creates the database tables if they don't exist."""
    db.connect()
    db.create_tables([Admin, Chat, User, Payment, UserSettings], safe=True)
    db.close()
