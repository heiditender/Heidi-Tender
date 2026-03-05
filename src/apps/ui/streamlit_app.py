from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Suisse Bid Match", layout="wide")
st.title("Suisse Bid Match")

page = st.sidebar.radio("Page", ["Search & Chat", "Tender Detail"])


def _safe_json_response(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


if page == "Search & Chat":
    st.subheader("Search / Chat")
    question = st.text_area(
        "Question",
        value="Zurich IT services tenders deadline next 30 days, what are key requirements?",
        height=120,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        source = st.selectbox("Source", ["", "simap"], index=1)
        buyer = st.text_input("Buyer contains", value="")
    with col2:
        cpv_raw = st.text_input("CPV codes (comma-separated)", value="")
        canton = st.text_input("Canton/Region", value="")
    with col3:
        language = st.selectbox("Language", ["", "en", "de", "fr", "it"], index=0)
        top_k = st.slider("Top K", min_value=3, max_value=12, value=8)

    date_col1, date_col2 = st.columns(2)
    with date_col1:
        start = st.date_input("Deadline start", value=datetime.utcnow().date() - timedelta(days=7))
    with date_col2:
        end = st.date_input("Deadline end", value=datetime.utcnow().date() + timedelta(days=30))

    if st.button("Ask", type="primary"):
        filters = {
            "source": source or None,
            "cpv": [x.strip() for x in cpv_raw.split(",") if x.strip()] or None,
            "buyer": buyer or None,
            "canton": canton or None,
            "language": language or None,
            "date_range": {
                "start": datetime.combine(start, datetime.min.time()).isoformat(),
                "end": datetime.combine(end, datetime.max.time()).isoformat(),
            },
        }
        payload = {
            "question": question,
            "filters": {k: v for k, v in filters.items() if v is not None},
            "top_k": top_k,
            "debug": True,
        }

        with st.spinner("Running retrieval and answer generation..."):
            resp = requests.post(f"{API_BASE}/chat", json=payload, timeout=60)
        data = _safe_json_response(resp)

        if resp.status_code >= 400:
            st.error(f"API error: {resp.status_code}")
            st.json(data)
        else:
            st.markdown("### Answer")
            st.write(data.get("answer", ""))
            if data.get("citation_count_insufficient"):
                st.warning("Less than 3 citations available for this query.")

            st.markdown("### Citations")
            for i, c in enumerate(data.get("citations", []), start=1):
                st.markdown(f"**{i}. {c.get('title') or 'Untitled'}**")
                if c.get("url"):
                    st.markdown(f"Notice: {c['url']}")
                if c.get("doc_url"):
                    st.markdown(f"Doc: {c['doc_url']}")
                st.write(c.get("snippet", ""))
                st.caption(f"score={c.get('score')} notice_id={c.get('notice_id')}")

            with st.expander("Debug"):
                st.json(data.get("debug", {}))

else:
    st.subheader("Tender Detail")
    notice_id = st.text_input("Notice ID")

    if st.button("Load Notice") and notice_id:
        notice_resp = requests.get(f"{API_BASE}/notices/{notice_id}", timeout=30)
        if notice_resp.status_code >= 400:
            st.error(f"Notice fetch failed: {notice_resp.status_code}")
            st.json(_safe_json_response(notice_resp))
        else:
            notice = notice_resp.json()
            st.markdown(f"### {notice.get('title') or notice.get('source_id')}")
            st.json(notice)

            checklist_resp = requests.get(f"{API_BASE}/notices/{notice_id}/checklist", timeout=60)
            st.markdown("### Checklist")
            st.json(_safe_json_response(checklist_resp))

            changes_resp = requests.get(f"{API_BASE}/notices/{notice_id}/changes", timeout=30)
            st.markdown("### Changes")
            st.json(_safe_json_response(changes_resp))
