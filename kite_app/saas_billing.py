"""Billing system and invoice management."""

from __future__ import annotations

import uuid
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kite_app.saas_models import (
    Organization, Subscription, BillingRecord, OrganizationUser,
)
from kite_app.saas_config import get_monthly_price
from kite_app.models import get_sessionmaker

router = APIRouter(tags=["billing"], prefix="/api/billing")


class InvoiceResponse(BaseModel):
    """Invoice details."""
    invoice_id: str
    subscription_id: str
    org_id: str
    amount: float
    currency: str
    status: str
    billing_date: str
    due_date: str
    payment_method: Optional[str]
    transaction_id: Optional[str]


class CreateInvoiceRequest(BaseModel):
    """Create invoice request."""
    org_id: str
    description: str = "Monthly subscription"


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(invoice_id: str) -> dict:
    """Get invoice details."""
    db = get_sessionmaker()()
    try:
        invoice = db.query(BillingRecord).filter(
            BillingRecord.invoice_number == invoice_id
        ).first()

        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return {
            "invoice_id": invoice.invoice_number,
            "subscription_id": str(invoice.subscription_id),
            "org_id": str(invoice.org_id),
            "amount": float(invoice.amount),
            "currency": invoice.currency,
            "status": invoice.status,
            "billing_date": invoice.created_at.date().isoformat(),
            "due_date": (invoice.created_at.date() + timedelta(days=30)).isoformat(),
            "payment_method": invoice.payment_method,
            "transaction_id": invoice.transaction_id,
        }
    finally:
        db.close()


@router.post("/invoices", response_model=InvoiceResponse)
def create_invoice(req: CreateInvoiceRequest) -> dict:
    """Create invoice for organization."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(req.org_id)
        ).first()

        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        sub = db.query(Subscription).filter(
            Subscription.org_id == org.org_id,
            Subscription.status == "active",
        ).first()

        if not sub:
            raise HTTPException(status_code=404, detail="No active subscription")

        # Generate invoice number
        invoice_num = f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        # Calculate amount based on tier and billing cycle
        amount = get_monthly_price(org.subscription_tier)
        if sub.billing_cycle == "yearly":
            amount *= 12

        billing = BillingRecord(
            billing_id=uuid.uuid4(),
            subscription_id=sub.subscription_id,
            org_id=org.org_id,
            invoice_number=invoice_num,
            amount=amount,
            currency="INR",
            status="pending",
            created_at=datetime.now(),
        )
        db.add(billing)
        db.commit()

        return {
            "invoice_id": billing.invoice_number,
            "subscription_id": str(billing.subscription_id),
            "org_id": req.org_id,
            "amount": amount,
            "currency": "INR",
            "status": "pending",
            "billing_date": datetime.now().date().isoformat(),
            "due_date": (datetime.now().date() + timedelta(days=30)).isoformat(),
            "payment_method": None,
            "transaction_id": None,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.post("/invoices/{invoice_id}/payment")
def record_payment(invoice_id: str, payment_method: str, transaction_id: str) -> dict:
    """Record payment for invoice."""
    db = get_sessionmaker()()
    try:
        invoice = db.query(BillingRecord).filter(
            BillingRecord.invoice_number == invoice_id
        ).first()

        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        if invoice.status != "pending":
            raise HTTPException(status_code=400, detail="Invoice already paid or cancelled")

        invoice.status = "paid"
        invoice.payment_method = payment_method
        invoice.transaction_id = transaction_id
        invoice.updated_at = datetime.now()

        db.commit()

        return {
            "invoice_id": invoice.invoice_number,
            "status": "paid",
            "payment_method": payment_method,
            "transaction_id": transaction_id,
            "paid_at": datetime.now().isoformat(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/organizations/{org_id}/invoices")
def list_org_invoices(org_id: str, limit: int = 50) -> list:
    """List invoices for organization."""
    db = get_sessionmaker()()
    try:
        invoices = db.query(BillingRecord).filter(
            BillingRecord.org_id == uuid.UUID(org_id)
        ).order_by(BillingRecord.created_at.desc()).limit(limit).all()

        return [
            {
                "invoice_id": inv.invoice_number,
                "amount": float(inv.amount),
                "currency": inv.currency,
                "status": inv.status,
                "billing_date": inv.created_at.date().isoformat(),
                "payment_method": inv.payment_method,
                "transaction_id": inv.transaction_id,
            }
            for inv in invoices
        ]
    finally:
        db.close()


def process_recurring_billing() -> dict:
    """Process recurring billing for subscriptions due for renewal."""
    db = get_sessionmaker()()
    try:
        today = date.today()
        
        # Find subscriptions that need renewal
        subs_to_renew = db.query(Subscription).filter(
            Subscription.status == "active",
            Subscription.auto_renew == True,
            Subscription.end_date <= today,
        ).all()

        results = {
            "processed": 0,
            "failed": 0,
            "invoices_created": [],
        }

        for sub in subs_to_renew:
            try:
                org = db.query(Organization).filter(
                    Organization.org_id == sub.org_id
                ).first()

                if not org:
                    results["failed"] += 1
                    continue

                # Renew subscription
                if sub.billing_cycle == "yearly":
                    new_end_date = today + timedelta(days=365)
                else:
                    new_end_date = today + timedelta(days=30)

                sub.end_date = new_end_date
                sub.next_billing_date = new_end_date

                # Create invoice
                invoice_num = f"INV-{today.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
                amount = get_monthly_price(org.subscription_tier)
                if sub.billing_cycle == "yearly":
                    amount *= 12

                billing = BillingRecord(
                    billing_id=uuid.uuid4(),
                    subscription_id=sub.subscription_id,
                    org_id=org.org_id,
                    invoice_number=invoice_num,
                    amount=amount,
                    currency="INR",
                    status="pending",
                    created_at=datetime.now(),
                )
                db.add(billing)
                results["invoices_created"].append(invoice_num)
                results["processed"] += 1

            except Exception:
                results["failed"] += 1
                continue

        db.commit()
        return results
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Billing process failed: {str(e)}")
    finally:
        db.close()
