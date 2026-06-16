"""分类统计页面"""

import streamlit as st
import pandas as pd
from datetime import date

from database import get_months, get_stats


def show_stats_page() -> None:
    st.subheader("分类统计")

    months = get_months()
    if not months:
        st.info("暂无数据，请先添加账目")
        return

    current_month = date.today().strftime("%Y-%m")
    default_month = current_month if current_month in months else months[0]
    default_index = months.index(default_month)

    selected_month = st.selectbox(
        "选择月份", months, index=default_index, key="stats_month"
    )

    stats = get_stats(selected_month)
    if not stats:
        st.info(f"{selected_month} 暂无账目记录")
        return

    # 柱状图
    chart_data = pd.DataFrame(
        [{"分类": row["category"], "金额": row["total"]} for row in stats]
    ).set_index("分类")

    st.bar_chart(chart_data, use_container_width=True)

    # 统计表
    grand_total = sum(row["total"] for row in stats)
    grand_count = sum(row["count"] for row in stats)

    table_rows = []
    for row in stats:
        pct = row["total"] / grand_total * 100
        table_rows.append(
            {
                "分类": row["category"],
                "笔数": row["count"],
                "合计金额": f"¥{row['total']:.2f}",
                "占比": f"{pct:.1f}%",
            }
        )
    table_rows.append(
        {
            "分类": "**合计**",
            "笔数": grand_count,
            "合计金额": f"¥{grand_total:.2f}",
            "占比": "100%",
        }
    )

    st.dataframe(
        pd.DataFrame(table_rows), use_container_width=True, hide_index=True
    )
