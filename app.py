import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- 1. 설정 및 제외 단어 ---
IGNORE_WORDS = {
    '있다', '있습니다', '있어요', '있는', '하는', '합니다', '하고', '됩니다', 
    '것입니다', '매우', '정말', '사실', '그래서', '그러나', '그런데', '그리고',
    '수', '것', '등', '더', '그', '이', '가', '을', '를', '은', '는', '의',
    '위한', '통해', '대해', '관한', '에서', '로', '으로', '해요', '해', '서'
}
JOSA_PATTERNS = r'(은|는|이|가|을|를|의|에|로|으로|에게|께|에서|와|과|한|하다|해요|된|지|도|만|서)$'

# --- 2. 구글 시트(DB) 연결 ---
def get_db_connection():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open("WordDB").sheet1 
        return sheet
    except Exception as e:
        return None

# --- 3. 정밀 분석 로직 ---
def normalize_word(word):
    word_clean = re.sub(r'[^\w\s]', '', word)
    if word_clean in IGNORE_WORDS: return None
    if len(word_clean) >= 2:
        clean_word = re.sub(JOSA_PATTERNS, '', word_clean)
        if len(clean_word) < 2 or clean_word in IGNORE_WORDS: return None
        return clean_word
    return None

def analyze_text_smart(text, db_keys):
    tokens = text.split()
    counts = {}
    
    for t in tokens:
        norm = normalize_word(t)
        if norm:
            counts[norm] = counts.get(norm, 0) + 1
            
    final_counts = {}
    for kw in counts.keys():
        cnt = text.count(kw)
        final_counts[kw] = cnt
        
    target_keywords = []
    for kw, cnt in final_counts.items():
        if cnt >= 2 or kw in db_keys:
            target_keywords.append(kw)
            
    return final_counts, target_keywords

# --- 4. 하이라이트 HTML 생성 (클릭 기능 제거 - 안전성 확보) ---
def create_highlighted_html(text, keywords):
    if not keywords:
        return text.replace("\n", "<br>")

    sorted_keywords = sorted(keywords, key=len, reverse=True)
    escaped_keywords = [re.escape(kw) for kw in sorted_keywords]
    pattern = re.compile('|'.join(escaped_keywords))

    def replace_func(match):
        word = match.group(0)
        # 링크(a 태그) 대신 단순 span 태그로 변경 -> 클릭해도 새로고침 안됨
        return f"<span class='highlight'>{word}</span>"

    highlighted_text = pattern.sub(replace_func, text)
    return highlighted_text.replace("\n", "<br>")

# --- 5. 데이터 동기화 함수 ---
def sync_input():
    st.session_state.main_text = st.session_state.editor_key

# --- 6. 메인 앱 ---
def main():
    st.set_page_config(layout="wide", page_title="영웅 분석기")

    # CSS 스타일
    st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px; line-height: 1.6; }
    
    .highlight { 
        background-color: #fff5b1; 
        padding: 2px 4px; 
        border-radius: 4px; 
        font-weight: bold; 
        border: 1px solid #fdd835;
        color: #333;
    }
    .preview-box {
        background-color: white; 
        padding: 20px; 
        border-radius: 10px; 
        border: 1px solid #eee; 
        line-height: 1.8; 
        height: 500px;
        overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("영웅 분석기")

    # 세션 초기화
    if 'main_text' not in st.session_state: st.session_state.main_text = ""
    if 'analyzed' not in st.session_state: st.session_state.analyzed = False

    # DB 연결
    sheet = get_db_connection()
    db_dict = {}
    if sheet:
        try:
            db_data = sheet.get_all_records()
            db_dict = {str(row['target_word']): str(row['replace_word']) for row in db_data}
        except: pass

    # --- 레이아웃 ---
    col_left, col_mid, col_right = st.columns([4, 2, 3])

    # [왼쪽] 원고 입력 & 미리보기
    with col_left:
        st.subheader("📝 원고 입력")
        
        # 입력창: 값이 바뀔 때마다 session_state.main_text에 저장 (on_change)
        st.text_area(
            "글을 입력하세요", 
            value=st.session_state.main_text,
            height=200, 
            key="editor_key",
            on_change=sync_input
        )
        
        if st.button("🔍 분석 시작", type="primary", use_container_width=True):
            st.session_state.main_text = st.session_state.editor_key # 강제 저장
            st.session_state.analyzed = True
            st.rerun()

        st.divider()
        st.subheader("📄 교정 미리보기")
        
        # 현재 저장된 텍스트 사용
        current_text = st.session_state.main_text

        if st.session_state.analyzed and current_text:
            counts, targets = analyze_text_smart(current_text, db_dict.keys())
            final_html = create_highlighted_html(current_text, targets)
            st.markdown(f"<div class='preview-box'>{final_html}</div>", unsafe_allow_html=True)
        else:
            st.info("분석을 시작하면 미리보기가 표시됩니다.")

    # [중간 & 오른쪽] 로직
    selected_word_from_table = None

    if st.session_state.analyzed and current_text:
        counts, targets = analyze_text_smart(current_text, db_dict.keys())
        sorted_targets = sorted(targets, key=lambda x: counts.get(x, 0), reverse=True)
        
        # [중간] 클릭 가능한 데이터프레임 (여기가 핵심!)
        with col_mid:
            st.subheader("📊 반복 횟수 (클릭)")
            st.caption("아래 표에서 단어를 선택하세요.")
            
            if sorted_targets:
                df = pd.DataFrame([(k, counts[k]) for k in sorted_targets], columns=['키워드', '횟수'])
                
                # Streamlit의 선택 기능 사용 (새로고침 없이 안전하게 선택 가능)
                event = st.dataframe(
                    df,
                    hide_index=True,
                    use_container_width=True,
                    height=500,
                    selection_mode="single-row", # 한 줄만 선택 가능
                    on_select="rerun" # 선택 시 리런 (이건 데이터가 저장된 후라 안전함)
                )
                
                # 선택된 행이 있는지 확인
                if len(event.selection.rows) > 0:
                    idx = event.selection.rows[0]
                    selected_word_from_table = df.iloc[idx]['키워드']
            else:
                st.caption("감지된 키워드가 없습니다.")

        # [오른쪽] 편집기
        with col_right:
            st.subheader("편집기")
            
            target = selected_word_from_table
            
            if not target:
                st.info("👈 중간의 '반복 횟수' 표에서 단어를 클릭하세요.")
            else:
                st.markdown(f"### 선택됨: **'{target}'**")
                st.write(f"등장 횟수: **{counts.get(target, 0)}회**")

                st.divider()
                tab_fix, tab_add, tab_manual = st.tabs(["🔄 대체어 적용", "➕ DB 추가", "✍️ 직접 수정"])
                
                # 1. DB 대체어 적용
                with tab_fix:
                    norm_target = normalize_word(target)
                    search_key = norm_target if norm_target and norm_target in db_dict else target
                    
                    if search_key in db_dict:
                        replacements = [w.strip() for w in db_dict[search_key].split(',')]
                        st.success("등록된 대체어:")
                        for rep in replacements:
                            if st.button(f"👉 '{rep}'(으)로 변경", key=f"btn_{target}_{rep}", use_container_width=True):
                                st.session_state.main_text = st.session_state.main_text.replace(target, rep)
                                st.toast(f"변경 완료: {target} -> {rep}")
                                st.rerun()
                    else:
                        st.warning("등록된 대체어가 없습니다.")

                # 2. DB 추가
                with tab_add:
                    st.write(f"**'{search_key}'** 저장")
                    new_sub = st.text_input("대체어 입력", key=f"new_db_{target}")
                    if st.button("💾 DB 저장", key=f"save_{target}", use_container_width=True):
                        if new_sub and sheet:
                            try:
                                sheet.append_row([search_key, new_sub])
                                st.success("저장 완료!")
                                st.rerun()
                            except: st.error("저장 실패")

                # 3. 직접 수정
                with tab_manual:
                    manual_val = st.text_input("바꿀 단어 입력", key=f"manual_{target}")
                    if st.button("적용하기", key=f"apply_{target}", use_container_width=True, type="primary"):
                        if manual_val:
                            st.session_state.main_text = st.session_state.main_text.replace(target, manual_val)
                            st.toast("수정되었습니다.")
                            st.rerun()

    st.divider()
    with st.expander("✅ 최종 교정 원고 복사하기"):
        st.code(st.session_state.main_text, language=None)

if __name__ == "__main__":
    main()
