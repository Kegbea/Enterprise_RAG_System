"""添加账目页面"""

import streamlit as st
from datetime import date

from config import CATEGORIES
from database import add_transaction


def show_add_page() -> None:
    st.subheader("添加新账目")

    with st.form("add_form", clear_on_submit=True):
        amount = st.number_input("金额", min_value=0.01, step=0.01, format="%.2f")
        category = st.selectbox("分类", CATEGORIES)
        trans_date = st.date_input("日期", value=date.today())
        note = st.text_input("备注", placeholder="可选")

        submitted = st.form_submit_button("添加")
        if submitted:
            if amount <= 0:
                st.error("金额必须大于 0")
            else:
                add_transaction(amount, category, trans_date.strftime("%Y-%m-%d"), note)
                st.success(f"已添加：{category} ¥{amount:.2f}")
