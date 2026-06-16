# 个人记账本

基于 **Python + Streamlit + SQLite3** 的个人记账 Web 工具。

## 功能

- **添加账目**：金额、分类、日期、备注
- **查看列表**：按月/分类筛选，表格展示
- **删除账目**：按 ID 删除
- **分类统计**：柱状图 + 统计表

## 技术栈

- Python 3
- Streamlit（Web 界面）
- SQLite3（数据存储，Python 内置）

## 项目结构

```
finance_cli/
├── app.py            # 入口：页面配置 + Tab 路由
├── config.py         # 常量：6 个预设分类
├── database.py       # 数据层：建表、增删查、统计查询
├── ui_add.py         # 页面：添加账目表单
├── ui_view.py        # 页面：查看列表 + 删除
├── ui_stats.py       # 页面：分类统计柱状图 + 统计表
├── requirements.txt  # 依赖声明
└── data.db           # SQLite 数据库（首次运行自动创建）
```

**依赖方向**：`app.py` → `ui_*.py` → `database.py` → `config.py`（单向，无循环引用）

## 运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

浏览器自动打开 `http://localhost:8501`。

## 数据库表结构

```sql
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    date TEXT NOT NULL,       -- "YYYY-MM-DD"
    note TEXT DEFAULT ''
);
```

6 个预设分类：`餐饮` `交通` `购物` `娱乐` `居住` `其他`
