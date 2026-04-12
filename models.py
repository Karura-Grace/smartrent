# Example using SQLAlchemy (adapt to your ORM)
from your_app import db
from datetime import datetime

class Transaction(db.Model):
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    external_reference = db.Column(db.String(100), unique=True, nullable=False)
    payhero_reference = db.Column(db.String(100), nullable=True)
    checkout_request_id = db.Column(db.String(200), nullable=True)
    tenant_id = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    bills = db.Column(db.Text, nullable=True)        # JSON string
    phone = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING/PAID/FAILED
    mpesa_receipt = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    
    @classmethod
    def get_by_external_reference(cls, ref):
        return cls.query.filter_by(external_reference=ref).first()
    
    @classmethod
    def get_by_payhero_reference(cls, ref):
        return cls.query.filter_by(payhero_reference=ref).first()