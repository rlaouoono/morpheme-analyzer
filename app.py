import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
from st_click_detector import click_detector
import time

# --- 1. [강력한 스크롤 고정] iframe 탈출 코드 ---
def inject_scroll_keeper():
    js = """
    <script>
        // 부모 창(실제 브라우저)의 스크롤 위치를 저장하고 복원합니다.
        try {
            var parentWindow = window.parent;
            
            // 스크롤 할 때마다 위치 저장
            parentWindow.addEventListener('scroll', function() {
                parentWindow.sessionStorage.setItem('scrollY', parentWindow.scrollY);
            });

            // 로드 시 복원 함수
            function restoreScroll() {
                var savedPos = parentWindow.sessionStorage.getItem('scrollY');
                if (savedPos) {
                    parentWindow.scrollTo(0, parseInt(savedPos));
                }
            }

            // 렌더링 타이밍 이슈 극복을 위해 반복 실행
            restoreScroll();
            setTimeout(restoreScroll, 100);
            setTimeout(restoreScroll, 300);
        } catch(e) {
            console.log("Cross-origin access blocked or other error");
        }
    </script>
    """
    st.components.v1.html(js, height=0, width=0)

# --- 2. 설정 및 기본 함수 ---
IGNORE_WORDS = {
    '있다', '있습니다', '있어요', '있는', '하는', '합니다', '하고', '됩니다', 
    '것입니다', '매우', '정말', '사실', '그래서', '그러나', '그런데', '그리고',
    '수', '것', '등', '더', '그', '이', '가', '을', '를', '은', '는', '의',
    '위한', '통해', '대해', '관한', '에서', '로', '으로', '해요', '해', '서'
}
JOSA_PATTERNS = r'(은|는|이|가|을|를|의|에|로|으로|에게|께|에서|와|과|한|하다|해요|된|지|도|만|서)$'

def get_db_connection():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)
        return client.open("WordDB").sheet1 
    except: return None

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
        if norm: counts[norm] = counts.get(norm, 0) + 1
            
    final_counts = {}
    for kw in counts.keys():
        cnt = text.count(kw)
        final_counts[kw] = cnt
        
    target_keywords = []
    for kw, cnt in final_counts.items():
        if cnt >= 2 or kw in db_keys:
            target_keywords.append(kw)
    return final_counts, target_keywords

def replace_nth_occurrence(text, target_word, replace_word, n):
    indices = [m.start() for m in re.finditer(re.escape(target_word), text)]
    if n < len(indices):
        start_idx = indices[n]
        end_idx = start_idx + len(target_word)
        return text[:start_idx] + replace_word + text[end_idx:]
    return text

# --- 3. HTML 생성 (필터링 로직 추가) ---
def create_interactive_html(text, keywords, filter_word=None):
    # 기본 CSS
    css_style = """
    <style>
        .highlight {
            background-color: #fff5b1; /* 기본 노란색 */
            padding: 2px 5px; border-radius: 4px; font-weight: bold;
            border: 1px solid #fdd835; color: #333; text-decoration: none;
            margin: 0 2px; cursor: pointer;
        }
        .highlight:hover { background-color: #ffeb3b; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        
        /* 필터링 되었을 때 비활성화된 스타일 */
        .dimmed {
            background-color: transparent;
            padding: 0; border: none; font-weight: normal;
            color: inherit; pointer-events: none;
        }
    </style>
    """
    
    if not keywords:
        return css_style + f"<div>{text.replace(chr(10), '<br>')}</div>"

    # [핵심] 필터링 단어가 있으면 그것만 남기고 나머지는 제거
    if filter_word:
        # filter_word와 정확히 일치하는 키워드만 남김
        active_keywords = [k for k in keywords if k == filter_word]
    else:
        active_keywords = keywords

    sorted_keywords = sorted(keywords, key=len, reverse=True) # 매칭을 위해 전체 키워드 패턴 사용
    escaped_keywords = [re.escape(kw) for kw in sorted_keywords]
    pattern = re.compile('|'.join(escaped_keywords))

    word_counter = {} 

    def replace_func(match):
        word = match.group(0)
        
        # 필터링 모드일 때: active 목록에 없으면 하이라이트 안 함
        if filter_word and word != filter_word:
            return word 

        current_count = word_counter.get(word, 0)
        word_counter[word] = current_count + 1
        
        unique_id = f"{word}__{current_count}"
        return f"<a href='javascript:void(0)' id='{unique_id}' class='highlight'>{word}</a>"

    highlighted_text = pattern.sub(replace_func, text)
    final_html = css_style + f"<div style='line-height:1.8; font-size:16px;'>{highlighted_text.replace(chr(10), '<br>')}</div>"
    return final_html

# --- 4. 메인 앱 ---
def main():
    st.set_page_config(layout="wide", page_title="영웅 분석기")
    inject_scroll_keeper() # 스크롤 고정 실행

    # CSS (패널 고정 및 스타일)
    st.markdown("""
    <style>
    div[data-testid="stColumn"]:nth-of-type(2) > div,
    div[data-testid="stColumn"]:nth-of-type(3) > div {
        position: sticky; top: 4rem; z-index: 999;
        background-color: white; padding: 15px; border-radius: 10px;
        border: 1px solid #f0f0f0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        max-height: 85vh; overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("영웅 분석기")

    # 세션 상태 초기화
    if 'main_text' not in st.session_state: st.session_state['main_text'] = ""
    if 'analyzed' not in st.session_state: st.session_state.analyzed = False
    if 'selected_keyword_id' not in st.session_state: st.session_state.selected_keyword_id = None
    if 'filter_keyword' not in st.session_state: st.session_state.filter_keyword = None

    # DB 로드
    sheet = get_db_connection()
    db_dict = {}
    if sheet:
        try:
            db_data = sheet.get_all_records()
            for row in db_data:
                t_word, r_word = str(row['target_word']), str(row['replace_word'])
                db_dict[t_word] = db_dict.get(t_word, "") + f", {r_word}" if t_word in db_dict else r_word
        except: pass

    col_left, col_mid, col_right = st.columns([5, 2, 2])

    # --- 1. 왼쪽: 원고 입력 & 미리보기 (통합) ---
    with col_left:
        with st.expander("📝 원고 입력 / 수정 (펼치기)", expanded=not st.session_state.analyzed):
            st.text_area("글을 입력하세요", key="editor_key", height=150,
                         value=st.session_state['main_text'])
            if st.button("🔍 분석 시작", type="primary", use_container_width=True):
                st.session_state.main_text = st.session_state.editor_key
                st.session_state.analyzed = True
                st.session_state.selected_keyword_id = None
                st.session_state.filter_keyword = None
                st.rerun()

        st.divider()
        
        # [복사 버튼 위치]
        c1, c2 = st.columns([3, 1])
        with c1: st.subheader("📄 교정 미리보기")
        with c2:
            # st.code는 내장 복사 버튼을 제공함. 깔끔하게 텍스트만 보여줌.
            if st.session_state.analyzed:
                with st.popover("📋 원고 복사"):
                    st.code(st.session_state.main_text, language=None)
                    st.caption("위 박스 우측 상단 아이콘을 눌러 복사하세요.")

        current_text = st.session_state.main_text

        if st.session_state.analyzed and current_text:
            # 1. 분석 수행
            counts, targets = analyze_text_smart(current_text, db_dict.keys())
            
            # 2. 필터링 여부 확인 (가운데 표에서 선택한 단어)
            filter_kw = st.session_state.filter_keyword
            if filter_kw:
                st.info(f"💡 '{filter_kw}' 단어만 확인 중입니다. (해제하려면 가운데 표의 다른 곳을 클릭하거나 새로고침)")
            else:
                st.caption("단어를 클릭하여 수정하세요.")

            # 3. HTML 생성 (필터 적용)
            html_content = create_interactive_html(current_text, targets, filter_word=filter_kw)
            
            # 4. 클릭 감지
            clicked_id = click_detector(html_content)
            if clicked_id:
                st.session_state.selected_keyword_id = clicked_id
        else:
            st.info("원고를 입력하고 분석을 시작하세요.")

    # --- 2. 가운데: 반복 횟수 (필터 기능 추가) ---
    with col_mid:
        st.subheader("📊 반복 횟수")
        if st.session_state.analyzed and sorted_targets := sorted(targets, key=lambda x: counts.get(x, 0), reverse=True):
            df = pd.DataFrame([(k, counts[k]) for k in sorted_targets], columns=['키워드', '횟수'])
            
            # [핵심] DataFrame 선택 기능 활성화 (행 클릭 시 필터링)
            event = st.dataframe(
                df, 
                hide_index=True, 
                use_container_width=True, 
                height=500,
                on_select="rerun", # 클릭 시 리런
                selection_mode="single-row"
            )
            
            # 선택된 행이 있으면 필터 키워드 업데이트
            if event.selection.rows:
                selected_idx = event.selection.rows[0]
                selected_word = df.iloc[selected_idx]['키워드']
                if st.session_state.filter_keyword != selected_word:
                    st.session_state.filter_keyword = selected_word
                    st.rerun()
            else:
                # 선택 해제 시 필터 초기화
                if st.session_state.filter_keyword is not None:
                    st.session_state.filter_keyword = None
                    st.rerun()
        else:
            st.caption("결과 없음")

    # --- 3. 오른쪽: 편집기 (N번째 수정 기능 유지) ---
    with col_right:
        st.subheader("편집기")
        sel_id = st.session_state.selected_keyword_id
        
        if not sel_id:
            st.info("👈 단어를 클릭하세요.")
        else:
            try:
                target_word, target_idx = sel_id.split("__")[0], int(sel_id.split("__")[1])
            except: target_word, target_idx = sel_id, 0

            st.markdown(f"**'{target_word}'** ({target_idx + 1}번째 등장)")
            
            tab_fix, tab_add, tab_manual = st.tabs(["🔄대체", "➕DB", "✍️수정"])
            
            with tab_fix: # 대체어
                norm = normalize_word(target_word)
                key = norm if norm and norm in db_dict else target_word
                if key in db_dict:
                    reps = [w.strip() for w in db_dict[key].split(',') if w.strip()]
                    for rep in reps:
                        if st.button(f"👉 {rep}", key=f"btn_{sel_id}_{rep}", use_container_width=True):
                            new_text = replace_nth_occurrence(current_text, target_word, rep, target_idx)
                            st.session_state.main_text = new_text
                            st.session_state.selected_keyword_id = None
                            st.toast(f"변경 완료: {rep}")
                            st.rerun()
                else: st.warning("대체어 없음")

            with tab_add: # DB추가
                new_sub = st.text_input("추가할 단어", key=f"new_db_{sel_id}")
                msg_box = st.empty()
                if st.button("💾 저장", key=f"save_{sel_id}", use_container_width=True):
                    if new_sub and sheet:
                        try:
                            sheet.append_row([key, new_sub])
                            msg_box.success("완료!")
                            time.sleep(1)
                            st.rerun()
                        except: msg_box.error("실패")

            with tab_manual: # 직접 수정
                val = st.text_input("입력", key=f"man_{sel_id}")
                if st.button("적용", key=f"app_{sel_id}", use_container_width=True, type="primary"):
                    if val:
                        new_text = replace_nth_occurrence(current_text, target_word, val, target_idx)
                        st.session_state.main_text = new_text
                        st.session_state.selected_keyword_id = None
                        st.rerun()

if __name__ == "__main__":
    main()
