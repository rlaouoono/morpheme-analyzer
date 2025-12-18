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
    '위한', '통해', '대해', '관한'
}
# 조사 패턴 (끝에 붙은 조사만 제거)
JOSA_PATTERNS = r'(은|는|이|가|을|를|의|에|로|으로|에게|께|에서|와|과|한|하다|해요|된|지)$'

# --- 2. 구글 시트(DB) 연결 (클라우드 호환 수정) ---
def get_db_connection():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # 1. 클라우드(Secrets)에 키가 있는지 먼저 확인
        if "gcp_service_account" in st.secrets:
            creds_dict = st.secrets["gcp_service_account"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        # 2. 없으면 로컬 파일(service_account.json) 확인
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
            
        client = gspread.authorize(creds)
        sheet = client.open("WordDB").sheet1 
        return sheet
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return None

# --- 3. 정밀 분석 로직 ---
def normalize_word(word):
    # 특수문자 제거
    word_clean = re.sub(r'[^\w\s]', '', word)
    if word_clean in IGNORE_WORDS: return None
    if len(word_clean) >= 2:
        # 조사 제거
        clean_word = re.sub(JOSA_PATTERNS, '', word_clean)
        if len(clean_word) < 2: return None
        if clean_word in IGNORE_WORDS: return None
        return clean_word
    return None

def analyze_text_smart(text):
    tokens = text.split()
    counts = {}
    
    # 1. 정규화된 단어 카운트
    for t in tokens:
        norm = normalize_word(t)
        if norm:
            counts[norm] = counts.get(norm, 0) + 1
            
    # 2. 본문 실제 등장 횟수 재확인 (중첩 카운트)
    final_counts = {}
    for kw in counts.keys():
        cnt = text.count(kw)
        final_counts[kw] = cnt
        
    return final_counts

# --- 4. [핵심] 텍스트 하이라이트 생성기 (깨짐 방지 로직) ---
def create_highlighted_html(text, keywords):
    """
    단어가 겹칠 때(예: '김해adhd'와 'adhd') HTML 태그가 깨지는 것을 방지하기 위해
    단 한번의 패스로 정규식 치환을 수행합니다.
    """
    if not keywords:
        return text.replace("\n", "<br>")

    # 길리가 긴 순서대로 정렬 (긴 단어를 먼저 잡아야 함)
    sorted_keywords = sorted(keywords, key=len, reverse=True)
    
    # 정규식 패턴 생성: (김해adhd|adhd|치료)
    # re.escape로 특수문자 충돌 방지
    pattern = re.compile('|'.join(re.escape(kw) for kw in sorted_keywords))

    def replace_func(match):
        word = match.group(0)
        # 클릭 가능한 링크 생성
        return f"<a href='?selected_word={word}' target='_self' class='highlight'>{word}</a>"

    # 전체 텍스트에서 패턴을 찾아 한 번에 교체
    highlighted_text = pattern.sub(replace_func, text)
    
    return highlighted_text.replace("\n", "<br>")

# --- 5. 팝업(Dialog) 기능 ---
@st.dialog("키워드 수정")
def show_correction_dialog(target_word, db_dict, sheet):
    st.write(f"선택한 키워드: **'{target_word}'**")
    
    tab1, tab2 = st.tabs(["✍️ 수정하기", "💾 DB에 추가"])
    
    # [탭 1] 수정하기
    with tab1:
        # DB 매칭 시도 (정규화된 단어로 검색)
        norm_target = normalize_word(target_word)
        search_key = norm_target if norm_target else target_word
        
        # 정확히 일치하거나, 정규화된 키워드가 DB에 있을 때
        found_key = None
        if target_word in db_dict: found_key = target_word
        elif search_key in db_dict: found_key = search_key
        
        if found_key:
            st.success(f"추천 대체어 발견! (키워드: {found_key})")
            replacements = [w.strip() for w in db_dict[found_key].split(',')]
            
            for rep in replacements:
                if st.button(f"👉 '{rep}'(으)로 전체 변경", key=f"btn_fix_{rep}", use_container_width=True):
                    st.session_state.main_text = st.session_state.main_text.replace(target_word, rep)
                    st.toast(f"모든 '{target_word}' -> '{rep}' 변경 완료!")
                    st.rerun()
        else:
            st.info("등록된 대체어가 없습니다.")

        st.divider()
        
        # 직접 수정
        col_input, col_btn = st.columns([3, 1])
        with col_input:
            manual_val = st.text_input("직접 입력", key="manual_fix_input")
        with col_btn:
            st.write("") 
            st.write("")
            if st.button("적용", key="btn_manual_apply", type="primary"):
                if manual_val:
                    st.session_state.main_text = st.session_state.main_text.replace(target_word, manual_val)
                    st.toast("수정되었습니다.")
                    st.rerun()

    # [탭 2] DB 추가
    with tab2:
        st.write(f"**'{search_key}'**의 대체어를 저장합니다.")
        new_sub = st.text_input("대체어 입력 (콤마로 구분)", key="new_db_input")
        if st.button("DB 저장하기", key="btn_db_save"):
            if new_sub and sheet:
                try:
                    sheet.append_row([search_key, new_sub])
                    st.success(f"저장 완료! '{search_key}'에 대한 데이터가 추가되었습니다.")
                except:
                    st.error("저장 실패")

# --- 6. 메인 앱 ---
def main():
    st.set_page_config(layout="wide", page_title="Pro 원고 교정기")

    # CSS 스타일
    st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px; line-height: 1.6; }
    /* 클릭 링크 스타일 */
    a.highlight { 
        background-color: #fff5b1; 
        color: #333 !important;
        padding: 2px 6px; 
        border-radius: 6px; 
        font-weight: 600; 
        border: 1px solid #fdd835;
        text-decoration: none !important;
        cursor: pointer;
    }
    a.highlight:hover {
        background-color: #ffeb3b;
        transform: scale(1.05);
    }
    .result-box {
        background-color: white; 
        padding: 30px; 
        border-radius: 12px; 
        border: 1px solid #eee; 
        line-height: 2.0; 
        height: 600px;
        overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("🩺 Pro 원고 교정기")

    # [중요] 세션 초기화 (원고 보존용)
    if 'main_text' not in st.session_state:
        st.session_state.main_text = ""

    # DB 로드
    sheet = get_db_connection()
    db_dict = {}
    if sheet:
        try:
            db_data = sheet.get_all_records()
            db_dict = {str(row['target_word']): str(row['replace_word']) for row in db_data}
        except:
            pass

    # [클릭 이벤트 처리]
    if "selected_word" in st.query_params:
        target = st.query_params["selected_word"]
        st.query_params.clear()
        show_correction_dialog(target, db_dict, sheet)

    # [입력 영역] - 콜백 함수를 사용하여 입력 즉시 세션에 저장
    def update_text():
        st.session_state.main_text = st.session_state.input_area

    with st.expander("📝 원고 입력", expanded=True):
        # value를 session_state.main_text로 고정하고, on_change로 동기화
        st.text_area(
            "여기에 글을 붙여넣으세요", 
            value=st.session_state.main_text,
            height=150, 
            key="input_area",
            on_change=update_text # 입력할 때마다 저장
        )
        
        # 검사 버튼 (사실 실시간 반영되지만 명시적 트리거 역할)
        if st.button("🔄 분석 결과 새로고침", type="secondary"):
            st.rerun()

    # [결과 영역]
    if st.session_state.main_text.strip():
        text = st.session_state.main_text
        counts = analyze_text_smart(text)
        
        # 5회 이상 반복 단어 필터링
        high_freq = [k for k, v in counts.items() if v >= 5]
        
        st.divider()
        col1, col2 = st.columns([3, 1])

        with col1:
            st.subheader("📄 교정 미리보기")
            st.caption("노란색 단어를 클릭하면 수정할 수 있습니다.")
            
            # [수정된 로직] HTML 깨짐 없이 하이라이트 생성
            final_html = create_highlighted_html(text, high_freq)
            
            st.markdown(f"<div class='result-box'>{final_html}</div>", unsafe_allow_html=True)

        with col2:
            st.subheader("📊 빈도 Top 리스트")
            if high_freq:
                # [수정된 로직] 내림차순 정렬 (높은 숫자 먼저)
                df = pd.DataFrame([(k, counts[k]) for k in high_freq], columns=['키워드', '빈도'])
                df = df.sort_values(by='빈도', ascending=False) # 내림차순 확실히 적용
                
                st.dataframe(
                    df, 
                    hide_index=True, 
                    use_container_width=True, 
                    height=600
                )
            else:
                st.success("5회 이상 반복된 단어가 없습니다.")

        # 최종 복사
        st.write("")
        with st.expander("✅ 최종 원고 복사하기"):
            st.code(st.session_state.main_text, language=None)

if __name__ == "__main__":
    main()