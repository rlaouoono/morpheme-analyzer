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
    '위한', '통해', '대해', '관한', '에서', '로', '으로'
}
JOSA_PATTERNS = r'(은|는|이|가|을|를|의|에|로|으로|에게|께|에서|와|과|한|하다|해요|된|지|도|만)$'

# --- 2. 구글 시트(DB) 연결 ---
def get_db_connection():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        # 클라우드 배포 환경 우선 확인
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        else:
            # 로컬 환경
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open("WordDB").sheet1 
        return sheet
    except Exception as e:
        # st.error(f"DB 연결 실패: {e}") # 필요시 주석 해제
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

def analyze_text_smart(text):
    tokens = text.split()
    counts = {}
    # 1. 정규화된 단어 카운트 (후보군 선정)
    for t in tokens:
        norm = normalize_word(t)
        if norm:
            counts[norm] = counts.get(norm, 0) + 1
            
    # 2. 본문 실제 등장 횟수 재확인 (중첩 포함)
    final_counts = {}
    for kw in counts.keys():
        cnt = text.count(kw)
        final_counts[kw] = cnt
    return final_counts

# --- 4. 하이라이트 HTML 생성 ---
def create_highlighted_html(text, keywords):
    """가장 긴 단어부터 순서대로 하이라이트 태그 적용"""
    if not keywords:
        return text.replace("\n", "<br>")

    sorted_keywords = sorted(keywords, key=len, reverse=True)
    # 특수문자 이스케이프 처리
    escaped_keywords = [re.escape(kw) for kw in sorted_keywords]
    pattern = re.compile('|'.join(escaped_keywords))

    def replace_func(match):
        word = match.group(0)
        # 단순 하이라이트용 span 태그 사용
        return f"<span class='highlight'>{word}</span>"

    highlighted_text = pattern.sub(replace_func, text)
    return highlighted_text.replace("\n", "<br>")

# --- 5. 메인 앱 ---
def main():
    st.set_page_config(layout="wide", page_title="영웅 분석기")

    # CSS 스타일
    st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px; line-height: 1.6; }
    /* 하이라이트 스타일 */
    .highlight { 
        background-color: #fff5b1; 
        padding: 2px 4px; 
        border-radius: 4px; 
        font-weight: bold; 
        border: 1px solid #fdd835;
    }
    /* 미리보기 박스 */
    .preview-box {
        background-color: white; 
        padding: 20px; 
        border-radius: 10px; 
        border: 1px solid #eee; 
        line-height: 1.8; 
        height: 400px;
        overflow-y: auto;
    }
    /* 통계 표 높이 */
    div[data-testid="stDataFrame"] { height: 400px; overflow-y: auto; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🩺 Pro 원고 교정기")

    # 세션 상태 초기화
    if 'main_text' not in st.session_state: st.session_state.main_text = ""
    if 'analyzed' not in st.session_state: st.session_state.analyzed = False
    if 'selected_keyword' not in st.session_state: st.session_state.selected_keyword = None

    # DB 로드
    sheet = get_db_connection()
    db_dict = {}
    if sheet:
        try:
            db_data = sheet.get_all_records()
            db_dict = {str(row['target_word']): str(row['replace_word']) for row in db_data}
        except: pass

    # --- 레이아웃 구성 (3단) ---
    # 왼쪽(입력/미리보기) : 중간(통계) : 오른쪽(컨트롤)
    col_left, col_mid, col_right = st.columns([4, 2, 3])

    # [왼쪽] 원고 입력 및 미리보기
    with col_left:
        st.subheader("📝 원고 입력")
        # 입력 즉시 동기화
        input_text = st.text_area(
            "글을 입력하세요", 
            value=st.session_state.main_text, 
            height=200, 
            key="input_area"
        )
        st.session_state.main_text = input_text
        
        if st.button("🔍 분석 시작", type="primary", use_container_width=True):
            st.session_state.analyzed = True
            st.session_state.selected_keyword = None # 새 분석 시 선택 초기화
            st.rerun()

        st.divider()
        st.subheader("📄 교정 미리보기")
        
        if st.session_state.main_text and st.session_state.analyzed:
            counts = analyze_text_smart(st.session_state.main_text)
            # 5회 이상 하이라이트
            high_freq = [k for k, v in counts.items() if v >= 5]
            final_html = create_highlighted_html(st.session_state.main_text, high_freq)
            st.markdown(f"<div class='preview-box'>{final_html}</div>", unsafe_allow_html=True)
        else:
            st.info("분석을 시작하면 미리보기가 표시됩니다.")

    # [중간 & 오른쪽] 분석 결과가 있을 때만 표시
    if st.session_state.main_text and st.session_state.analyzed:
        counts = analyze_text_smart(st.session_state.main_text)
        high_freq_all = sorted([k for k, v in counts.items() if v >= 4], key=lambda x: counts[x], reverse=True)
        
        # [중간] 반복 횟수 통계
        with col_mid:
            st.subheader("📊 반복 횟수")
            if high_freq_all:
                df = pd.DataFrame([(k, counts[k]) for k in high_freq_all], columns=['키워드', '횟수'])
                st.dataframe(df, hide_index=True, use_container_width=True)
            else:
                st.caption("4회 이상 반복된 단어가 없습니다.")

        # [오른쪽] 대체어 선택 및 추가 컨트롤
        with col_right:
            st.subheader("🛠️ 수정 컨트롤")
            if not high_freq_all:
                st.info("수정할 대상이 없습니다.")
            else:
                # 키워드 선택 라디오 버튼
                selected_kw = st.radio(
                    "수정할 키워드 선택:", 
                    high_freq_all, 
                    format_func=lambda x: f"{x} ({counts[x]}회)",
                    key="keyword_radio"
                )
                st.session_state.selected_keyword = selected_kw

                st.divider()
                
                target = st.session_state.selected_keyword
                if target:
                    st.markdown(f"**선택됨: '{target}'**")

                    # 탭으로 기능 분리
                    tab_fix, tab_add, tab_manual = st.tabs(["🔄 대체어 적용", "➕ DB 추가", "✍️ 직접 수정"])
                    
                    # 1. DB 대체어 적용 탭
                    with tab_fix:
                        # 정규화된 키워드로 DB 검색 시도
                        norm_target = normalize_word(target)
                        search_key = norm_target if norm_target and norm_target in db_dict else target
                        
                        if search_key in db_dict:
                            replacements = [w.strip() for w in db_dict[search_key].split(',')]
                            st.caption("등록된 대체어 (버튼 클릭 시 즉시 변경):")
                            for rep in replacements:
                                if st.button(f"👉 '{rep}'(으)로 모두 변경", key=f"btn_{target}_{rep}", use_container_width=True):
                                    st.session_state.main_text = st.session_state.main_text.replace(target, rep)
                                    st.toast(f"'{target}' -> '{rep}' 변경 완료!")
                                    st.rerun()
                        else:
                            st.warning("DB에 등록된 대체어가 없습니다. 'DB 추가' 탭을 이용하세요.")

                    # 2. DB 추가 탭
                    with tab_add:
                        st.caption(f"'{search_key}'의 대체어를 DB에 저장합니다.")
                        new_sub = st.text_input("대체어 입력 (콤마 구분)", key=f"new_db_{target}")
                        if st.button("💾 DB 저장", key=f"save_{target}", use_container_width=True):
                            if new_sub and sheet:
                                try:
                                    sheet.append_row([search_key, new_sub])
                                    st.success(f"저장 완료! (새로고침 후 적용됨)")
                                except: st.error("저장 실패")

                    # 3. 직접 수정 탭
                    with tab_manual:
                        st.caption("해당 단어를 원하는 단어로 직접 바꿉니다.")
                        manual_val = st.text_input("바꿀 단어 입력", key=f"manual_{target}")
                        if st.button("적용하기", key=f"apply_{target}", use_container_width=True, type="primary"):
                            if manual_val:
                                st.session_state.main_text = st.session_state.main_text.replace(target, manual_val)
                                st.toast("수정되었습니다.")
                                st.rerun()

    # 하단: 최종 결과 복사
    st.divider()
    with st.expander("✅ 최종 교정 원고 복사하기 (클릭)"):
        st.code(st.session_state.main_text, language=None)

if __name__ == "__main__":
    main()

