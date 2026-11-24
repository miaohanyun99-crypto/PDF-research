import streamlit as st
import pymupdf
import pandas as pd
import hashlib
import hmac
import re
from supabase import create_client

st.set_page_config(page_title='PDF文献检索平台', layout='wide')
st.title('PDF 文献检索平台')

required = ['APP_PASSWORD', 'SUPABASE_URL', 'SUPABASE_KEY']
try:
    missing = [k for k in required if k not in st.secrets]
except Exception:
    missing = required
if missing:
    st.error('请在 Streamlit Secrets 中配置：' + ', '.join(missing))
    st.stop()

if not st.session_state.get('authorized'):
    with st.form('login'):
        password = st.text_input('请输入访问密码', type='password')
        submitted = st.form_submit_button('登录')
    if submitted:
        expected = st.secrets['APP_PASSWORD']
        if not isinstance(expected, str) or not expected:
            st.error('请将 Secrets 中的 APP_PASSWORD 设置为带英文双引号的非空字符串。')
        elif hmac.compare_digest(password.encode('utf-8'), expected.encode('utf-8')):
            st.session_state['authorized'] = True
            st.rerun()
        else:
            st.error('密码错误')
    st.stop()

try:
    db = create_client(str(st.secrets['SUPABASE_URL']), str(st.secrets['SUPABASE_KEY']))
except Exception:
    st.error('数据库连接配置有误，请检查 SUPABASE_URL 和 SUPABASE_KEY。')
    st.stop()

with st.sidebar:
    st.header('文献库管理')
    if st.button('退出登录'):
        st.session_state.clear()
        st.rerun()
    files = st.file_uploader('上传PDF文件', type=['pdf'], accept_multiple_files=True)
    if st.button('保存至文献库'):
        if not files:
            st.warning('请先上传PDF')
        for file in files:
            try:
                data = file.getvalue()
                digest = hashlib.sha256(data).hexdigest()
                with pymupdf.open(stream=data, filetype='pdf') as doc:
                    rows = [{'file_hash': digest, 'file_name': file.name, 'page_number': i+1, 'content': page.get_text()} for i, page in enumerate(doc)]
                if not any(r['content'].strip() for r in rows):
                    st.warning(f'{file.name} 无可提取文字，可能需要OCR。')
                    continue
                for i in range(0, len(rows), 50):
                    db.table('pdf_pages').upsert(rows[i:i+50], on_conflict='file_hash,page_number').execute()
                st.success(f'{file.name} 已保存')
            except Exception:
                st.error(f'{file.name} 保存失败，可能存在部分已入库页面，可重新上传重试。')
    try:
        count = db.table('pdf_pages').select('id', count='exact').limit(1).execute()
        st.metric('已存储文献页数', count.count)
    except Exception:
        st.error('无法读取数据库，请检查密钥及数据表权限。')

with st.form('search'):
    keyword = st.text_input('输入检索关键词')
    search = st.form_submit_button('开始检索', type='primary')
if search:
    st.session_state.pop('results', None)
    term = keyword.strip()
    if not term:
        st.warning('请输入关键词')
    else:
        results = []
        last_id = 0
        try:
            with st.spinner('正在检索文献库...'):
                while True:
                    rows = db.table('pdf_pages').select('id,file_name,page_number,content').gt('id', last_id).order('id').limit(200).execute().data
                    if not rows:
                        break
                    for row in rows:
                        text = row['content']
                        for match in re.finditer(re.escape(term), text, re.IGNORECASE):
                            results.append({'文件名': row['file_name'], '页码': row['page_number'], '原文': text[max(0,match.start()-150):match.end()+150]})
                    last_id = rows[-1]['id']
            st.session_state['results'] = results
        except Exception:
            st.error('检索失败，请检查数据库连接后重试。')
if 'results' in st.session_state:
    results = st.session_state['results']
    st.success(f'共找到 {len(results)} 处匹配')
    for item in results:
        with st.expander(f"{item['文件名']} | 第{item['页码']}页"):
            st.write(item['原文'])
    if results:
        st.download_button('导出检索结果', pd.DataFrame(results).to_csv(index=False).encode('utf-8-sig'), '检索结果.csv', 'text/csv')
