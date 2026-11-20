"""Run with: streamlit run app.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from procurement.agent import ProcurementAgent  # noqa: E402
from procurement.approval import ApprovalService  # noqa: E402
from procurement.auth import UserStore  # noqa: E402
from procurement.llm import BedrockClient  # noqa: E402
from procurement.notifications import AlertStore, CompositeNotifier, InAppNotifier, SnsEmailNotifier  # noqa: E402
from procurement.po import FilePurchaseOrderIssuer  # noqa: E402
from procurement.quotes import QuoteRepository  # noqa: E402
from procurement.store import SqliteCaseStore  # noqa: E402
from procurement.ui import render  # noqa: E402

DATA = ROOT / "data"


@st.cache_resource
def get_agent() -> ProcurementAgent:
    # Simulated per-supplier catalogue response time, e.g. "0.4,1.2" seconds; "0" turns it off.
    lo, _, hi = os.getenv("MOCK_SUPPLIER_LATENCY", "0.4,1.2").partition(",")
    repo = QuoteRepository(os.getenv("QUOTES_PATH", DATA / "quotes.json"),
                           latency=(float(lo or 0), float(hi or lo or 0)))
    return ProcurementAgent(BedrockClient(), repo)


@st.cache_resource
def get_users() -> UserStore:
    return UserStore(os.getenv("USERS_PATH", DATA / "users.json"))


@st.cache_resource
def get_alerts() -> AlertStore:
    return AlertStore(os.getenv("CASES_DB", DATA / "cases.db"))


def build_notifier() -> CompositeNotifier:
    channels = [InAppNotifier(get_alerts(), get_users())]
    topic = os.getenv("APPROVAL_SNS_TOPIC_ARN", "").strip()
    if topic:  # email alerts, see scripts/setup_email_alerts.md
        channels.append(SnsEmailNotifier(topic, app_url=os.getenv("APP_URL", "")))
    return CompositeNotifier(channels)


@st.cache_resource
def get_approval_service() -> ApprovalService:
    # Shared across browser sessions; cases are stored in SQLite and survive restarts.
    return ApprovalService(
        os.getenv("AUDIT_PATH", DATA / "audit.jsonl"),
        po_issuer=FilePurchaseOrderIssuer(os.getenv("PO_DIR", DATA / "purchase_orders")),
        store=SqliteCaseStore(os.getenv("CASES_DB", DATA / "cases.db")),
        notifier=build_notifier(),
    )


render(get_agent(), get_approval_service(), get_users(), alerts=get_alerts(),
       poll_seconds=int(os.getenv("ALERT_POLL_SECONDS", "15")) or None)
