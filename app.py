import streamlit as st
import pymupdf
import pandas as pd
import hashlib
import hmac
import re
from supabase import create_client

st.set_page_config(
    page_title="PDF文献检索平台",
    layout="wide"
)

st.title("PDF 文献检索平台")

# 网站访问验证
if not st.session_state.get("authorized"):
    password = st.text_input("请输入访问密码", type="password")
    if st.button("登录"):
        if hmac.compare_digest(
            password, st.secrets["APP_PASSWORD"]
        ):
            st.session_state["authorized"] = True
            st.rerun()
        else:
            st.error("密码错误")
    st.stop()

# 连接数据库
db = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

# 上传文献
with st.sidebar:
    st.header("文献库管理")

    files = st.file_uploader(
        "上传PDF文件",
        type=["pdf"],
        accept_multiple_files=True
    )

    if st.button("保存至文献库"):
        if not files:
            st.warning("请先上传文件")

        for file in files:
            try:
                data = file.getvalue()
                file_hash = hashlib.sha256(data).hexdigest()
                rows = []

                with pymupdf.open(
                    stream=data, filetype="pdf"
                ) as doc:
                    for i, page in enumerate(doc):
                        rows.append({
                            "file_hash": file_hash,
                            "file_name": file.name,
                            "page_number": i + 1,
                            "content": page.get_text()
                        })

                for i in range(0, len(rows), 50):
                    db.table("pdf_pages").upsert(
                        rows[i:i+50],
                        on_conflict="file_hash,page_number"
                    ).execute()

                st.success(f"{file.name} 已保存")

            except Exception as e:
                st.error(f"{file.name} 保存失败")

    count = db.table("pdf_pages").select(
        "id", count="exact"
    ).limit(1).execute()

    st.metric("已存储文献页数", count.count)

# 关键词检索
keyword = st.text_input("输入检索关键词")

if st.button("开始检索", type="primary"):
    if keyword.strip():
        results = []
        offset = 0
        term = keyword.strip()

        with st.spinner("正在检索数据库..."):
            while True:
                response = db.table("pdf_pages").select(
                    "id,file_name,page_number,content"
                ).order("id").range(
                    offset, offset + 199
                ).execute()

                for row in response.data:
                    text = row["content"]

                    for match in re.finditer(
                        re.escape(term),
                        text,
                        re.IGNORECASE
                    ):
                        results.append({
                            "文件名": row["file_name"],
                            "页码": row["page_number"],
                            "原文": text[
                                max(0, match.start()-150):
                                match.end()+150
                            ]
                        })

                if len(response.data) < 200:
                    break

                offset += 200

        st.session_state["results"] = results

if "results" in st.session_state:
    results = st.session_state["results"]

    st.success(f"共找到 {len(results)} 处匹配")

    for item in results:
        with st.expander(
            f"{item['文件名']} | 第{item['页码']}页"
        ):
            st.write(item["原文"])

    if results:
        df = pd.DataFrame(results)

        st.download_button(
            "导出检索结果",
            df.to_csv(index=False).encode("utf-8-sig"),
            "检索结果.csv",
            "text/csv"
        )
