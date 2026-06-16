"""个人记账本 — 入口"""

import streamlit as st

from database import init_db
from ui_add import show_add_page
from ui_view import show_view_page
from ui_stats import show_stats_page

st.set_page_config(page_title="个人记账本", page_icon="💰", layout="wide")

# 首次运行自动建表
init_db()

st.title("💰 个人记账本")

tab1, tab2, tab3 = st.tabs(["添加账目", "查看列表", "分类统计"])

with tab1:
    show_add_page()

with tab2:
    show_view_page()

with tab3:
    show_stats_page()
