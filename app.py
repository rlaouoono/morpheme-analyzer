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
    
    # 1. 단어 카운팅
    for t in tokens:
        norm = normalize_word(t)
        if norm:
            counts[norm] = counts.get(norm, 0) + 1
            
    # 2. 본문 실제 등장 횟수 재확인 (중첩 포함)
    final_counts = {}
    for kw in counts.keys():
        cnt = text.count(kw)
        final_counts[kw] = cnt
        
    # [핵심 변경 사항] main.py 로직 적용
    # 조건 1: 빈도수가 2회 이상인 단어
    # 조건 2: DB에 이미 등록된 단어 (빈도수 1회라도 포함)
    target_keywords = []
    for kw, cnt in final_counts.items():
        if cnt >= 2 or kw in db_keys:
            target_keywords.append(kw)
            
    return final_counts, target_keywords

# --- 4. 하이라이트 HTML 생성 (클릭 링크 포함) ---
def create_highlighted_html(text, keywords):
    if not keywords:
        return text.replace("\n", "<br>")

    # 긴 단어부터 처리해야 태그 꼬임 방지
    sorted_keywords = sorted(keywords, key=len, reverse=True)
    escaped_keywords = [re.escape(kw) for kw in sorted_keywords]
    pattern = re.compile('|'.join(escaped_keywords))

    def replace_func(match):
        word = match.group(0)
        # 클릭 시 ?selected_word=단어 형태로 리로드 (우측 패널 연동용)
        return f"<a href='?selected_word={word}' target='_self' class='highlight'>{word}</a>"

    highlighted_text = pattern.sub(replace_func, text)
    return highlighted_text.replace("\n", "<br>")

# --- 5. 메인 앱 ---
def main():
    st.set_page_config(layout="wide", page_title="영웅 분석기")

    # CSS 스타일
    st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px; line-height: 1.6; }
    
    /* 클릭 가능한 하이라이트 스타일 */
    a.highlight { 
        background-color: #fff5b1; 
        color: #333 !important;
        padding: 2px 5px; 
        border-radius: 4px; 
        font-weight: bold; 
        border: 1px solid #fdd835;
        text-decoration: none !important;
        cursor: pointer;
        transition: all 0.2s;
    }
    a.highlight:hover {
        background-color: #ffeb3b;
        transform: scale(1.05);
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* 미리보기 박스 */
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

    # [핵심 기능] URL 쿼리 파라미터 감지 (클릭 시 실행됨)
    if "selected_word" in st.query_params:
        clicked_word = st.query_params["selected_word"]
        st.session_state.selected_keyword = clicked_word
        # 파라미터 초기화 (새로고침 시 유지되지 않도록)
        st.query_params.clear()

    # --- 레이아웃 구성 (3단) ---
    col_left, col_mid, col_right = st.columns([4, 2, 3])

    # [왼쪽] 원고 입력 및 미리보기
    with col_left:
        st.subheader("📝 원고 입력")
        input_text = st.text_area(
            "글을 입력하세요", 
            value=st.session_state.main_text, 
            height=150, 
            key="input_area"
        )
        st.session_state.main_text = input_text
        
        if st.button("🔍 분석 시작", type="primary", use_container_width=True):
            st.session_state.analyzed = True
            st.session_state.selected_keyword = None 
            st.rerun()

        st.divider()
        st.subheader("📄 교정 미리보기")
        st.caption("노란색 단어를 클릭하면 오른쪽에서 수정할 수 있습니다.")
        
        if st.session_state.main_text and st.session_state.analyzed:
            # DB에 있는 키워드 목록 전달
            counts, targets = analyze_text_smart(st.session_state.main_text, db_dict.keys())
            
            # HTML 생성 (클릭 링크 포함)
            final_html = create_highlighted_html(st.session_state.main_text, targets)
            st.markdown(f"<div class='preview-box'>{final_html}</div>", unsafe_allow_html=True)
        else:
            st.info("분석을 시작하면 미리보기가 표시됩니다.")

    # [중간 & 오른쪽] 분석 결과가 있을 때만 표시
    if st.session_state.main_text and st.session_state.analyzed:
        # 타겟 키워드 다시 계산 (화면 렌더링용)
        counts, targets = analyze_text_smart(st.session_state.main_text, db_dict.keys())
        # 빈도순 정렬
        sorted_targets = sorted(targets, key=lambda x: counts.get(x, 0), reverse=True)
        
        # [중간] 반복 횟수 통계
        with col_mid:
            st.subheader("📊 반복 횟수")
            if sorted_targets:
                df = pd.DataFrame([(k, counts[k]) for k in sorted_targets], columns=['키워드', '횟수'])
                st.dataframe(df, hide_index=True, use_container_width=True, height=500)
            else:
                st.caption("감지된 키워드가 없습니다.")

        # [오른쪽] 수정 컨트롤 (선택된 단어가 있을 때만 활성화)
        with col_right:
            st.subheader("편집기")
            
            target = st.session_state.selected_keyword
            
            if not target:
                st.info("👈 왼쪽 미리보기에서 노란색 단어를 클릭하세요.")
            else:
                st.markdown(f"### 선택됨: **'{target}'**")
                
                # 빈도수 표시
                current_count = counts.get(target, 0)
                st.write(f"현재 본문 등장 횟수: **{current_count}회**")

                st.divider()

                # 탭으로 기능 분리
                tab_fix, tab_add, tab_manual = st.tabs(["🔄 대체어 적용", "➕ DB 추가", "✍️ 직접 수정"])
                
                # 1. DB 대체어 적용 탭
                with tab_fix:
                    # 정규화된 키워드로 DB 검색
                    norm_target = normalize_word(target)
                    search_key = norm_target if norm_target and norm_target in db_dict else target
                    
                    if search_key in db_dict:
                        replacements = [w.strip() for w in db_dict[search_key].split(',')]
                        st.success("등록된 대체어가 있습니다!")
                        for rep in replacements:
                            if st.button(f"👉 '{rep}'(으)로 변경", key=f"btn_{target}_{rep}", use_container_width=True):
                                st.session_state.main_text = st.session_state.main_text.replace(target, rep)
                                st.toast(f"변경 완료: {target} -> {rep}")
                                st.rerun()
                    else:
                        st.warning("등록된 대체어가 없습니다. 'DB 추가' 탭을 이용하세요.")

                # 2. DB 추가 탭
                with tab_add:
                    st.write(f"**'{search_key}'** 저장")
                    new_sub = st.text_input("대체어 입력 (콤마 구분)", key=f"new_db_{target}")
                    if st.button("💾 DB 저장", key=f"save_{target}", use_container_width=True):
                        if new_sub and sheet:
                            try:
                                sheet.append_row([search_key, new_sub])
                                st.success(f"저장 완료! (새로고침 후 적용됨)")
                                # 캐시 갱신을 위해 리로드
                                st.rerun()
                            except: st.error("저장 실패")

                # 3. 직접 수정 탭
                with tab_manual:
                    manual_val = st.text_input("바꿀 단어 입력", key=f"manual_{target}")
                    if st.button("적용하기", key=f"apply_{target}", use_container_width=True, type="primary"):
                        if manual_val:
                            st.session_state.main_text = st.session_state.main_text.replace(target, manual_val)
                            st.toast("수정되었습니다.")
                            st.rerun()

    # 하단: 최종 결과 복사
    st.divider()
    with st.expander("✅ 최종 교정 원고 복사하기"):
        st.code(st.session_state.main_text, language=None)

if __name__ == "__main__":
    main()
