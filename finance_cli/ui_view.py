"""查看与删除页面"""

import streamlit as st
import pandas as pd

from config import CATEGORIES
from database import get_transactions, get_months, delete_transaction


def show_view_page() -> None:
    st.subheader("查看账目")

    months = get_months()
    month_options = ["全部"] + months

    col1, col2 = st.columns(2)
    with col1:
        selected_month = st.selectbox("月份", month_options, key="view_month")
    with col2:
        selected_categories = st.multiselect(
            "分类", CATEGORIES, default=CATEGORIES, key="view_categories"
        )

    # 删除区（放在表格前面，确保删除后查询的是最新数据）
    st.divider()
    st.subheader("删除账目")
    del_col1, del_col2 = st.columns([1, 3])
    with del_col1:
        delete_id = st.number_input(
            "输入要删除的 ID", min_value=1, step=1, key="delete_id"
        )
    with del_col2:
        st.write("")
        if st.button("确认删除", key="delete_btn"):
            if delete_transaction(delete_id):
                st.success(f"已删除 ID={delete_id}")
                st.rerun()
            else:
                st.warning(f"ID={delete_id} 不存在")

    st.divider()
    st.subheader("账目列表")

    # 查询
    month_filter = None if selected_month == "全部" else selected_month
    cat_filter = selected_categories if selected_categories else None
    transactions = get_transactions(month=month_filter, categories=cat_filter)

    if not transactions:
        st.info("暂无账目记录")
        return

    df = pd.DataFrame(transactions)
    df = df.rename(
        columns={
            "id": "ID",
            "amount": "金额",
            "category": "分类",
            "date": "日期",
            "note": "备注",
        }
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
