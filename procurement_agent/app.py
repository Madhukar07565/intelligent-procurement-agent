"""Run with: streamlit run app.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from procurement.agent import ProcurementAgent  # noqa: E402
from procurement.approval import ApprovalService  # noqa: E402
from procurement.llm import BedrockClient  # noqa: E402
from procurement.po import FilePurchaseOrderIssuer  # noqa: E402
from procurement.quotes import QuoteRepository  # noqa: E402
from procurement.ui import render  # noqa: E402


@st.cache_resource
def get_agent() -> ProcurementAgent:
    repo = QuoteRepository(os.getenv("QUOTES_PATH", ROOT / "data" / "quotes.json"))
    return ProcurementAgent(BedrockClient(), repo)


@st.cache_resource
def get_approval_service() -> ApprovalService:
    # Shared across browser sessions so a requester and an approver can use two tabs.
    return ApprovalService(
        os.getenv("AUDIT_PATH", ROOT / "data" / "audit.jsonl"),
        po_issuer=FilePurchaseOrderIssuer(os.getenv("PO_DIR", ROOT / "data" / "purchase_orders")),
    )


render(get_agent(), get_approval_service())
