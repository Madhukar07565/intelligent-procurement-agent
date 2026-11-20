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
from procurement.po import FilePurchaseOrderIssuer  # noqa: E402
from procurement.quotes import QuoteRepository  # noqa: E402
from procurement.store import SqliteCaseStore  # noqa: E402
from procurement.ui import render  # noqa: E402

DATA = ROOT / "data"


@st.cache_resource
def get_agent() -> ProcurementAgent:
    repo = QuoteRepository(os.getenv("QUOTES_PATH", DATA / "quotes.json"))
    return ProcurementAgent(BedrockClient(), repo)


@st.cache_resource
def get_approval_service() -> ApprovalService:
    # Shared across browser sessions; cases are stored in SQLite and survive restarts.
    return ApprovalService(
        os.getenv("AUDIT_PATH", DATA / "audit.jsonl"),
        po_issuer=FilePurchaseOrderIssuer(os.getenv("PO_DIR", DATA / "purchase_orders")),
        store=SqliteCaseStore(os.getenv("CASES_DB", DATA / "cases.db")),
    )


@st.cache_resource
def get_users() -> UserStore:
    return UserStore(os.getenv("USERS_PATH", DATA / "users.json"))


render(get_agent(), get_approval_service(), get_users())
