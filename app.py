import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
from st_click_detector import click_detector
import time

# --- 1. [핵심] 스크롤 고정 자바스크립트 ---
# 이 함수가 매번 실행되면서 스크롤 위치를 기억하고 강제로 되돌려 놓습니다.
def inject_scroll_keeper():
    js = """
    <script>
        // 1. 스크롤 할 때마다 위치를 세션 저장소에 저장 (키: scrollY)
        window.addEventListener('scroll', function() {
            sessionStorage.setItem('scrollY', window.scrollY);
        });

        // 2. 페이지가 로드되거나 Rerun될 때 저장된 위치로 강제 이동
        function restoreScroll() {
            var savedPos = sessionStorage.getItem('scrollY');
            if (savedPos) {
                window.scrollTo(0, parseInt(savedPos));
            }
        }

        // 3. [중요] Streamlit 렌더링 시간차를 극복하기 위해 
        //    0.1초, 0.2초, 0.5초 뒤에 반복해서 스크롤을 제자리로 돌려놓음
        restoreScroll();
        setTimeout(restoreScroll, 100);
        setTimeout(restoreScroll, 200);
        setTimeout(restoreScroll, 500);
    </script>
    """
    st.components.v1.html(js, height=0, width=0)

# --- 2. 설정 및 제외 단어 ---
IGNORE_WORDS = {
    '있다', '있습니다', '있어요', '있는', '하는', '합니다', '하고', '됩니다', 
    '것입니다', '매우', '정말', '사실', '그래서', '그러나', '그런데', '그리고',
    '수', '것', '등', '더', '그', '이', '가', '을', '를', '은', '는', '의',
    '위한', '통해', '대해', '관한', '에서', '로', '으로', '해요', '해', '서'
}
JOSA_PATTERNS = r'(은|는|이|가|을|를|의|에|로|으로|에게|께|에서|와|과|한|하다|해요|된|지|도|만|서)$'

# --- 3. 구글 시트(DB) 연결 ---
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

# --- 4. 정밀 분석 로직 ---
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

# --- [유지] N번째 단어만 교체하는 함수 ---
def replace_nth_occurrence(text, target_word, replace_word, n):
    indices = [m.start() for m in re.finditer(re.escape(target_word), text)]
    if n < len(indices):
        start_idx = indices[n]
        end_idx = start_idx + len(target_word)
        return text[:start_idx] + replace_word + text[end_idx:]
    return text

# --- 5. 하이라이트 HTML 생성 (ID에 순번 추가) ---
def create_interactive_html(text, keywords):
    css_style = """
    <style>
        .highlight {
            background-color: #fff5b1;
            padding: 2px 5px;
            border-radius: 4px;
            font-weight: bold;
            border: 1px solid #fdd835;
            color: #333;
            text-decoration: none;
            margin: 0 2px;
            cursor: pointer;
        }
        .highlight:hover {
            background-color: #ffeb3b;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
    </style>
    """
    
    if not keywords:
        return css_style + f"<div>{text.replace(chr(10), '<br>')}</div>"

    sorted_keywords = sorted(keywords, key=len, reverse=True)
    escaped_keywords = [re.escape(kw) for kw in sorted_keywords]
    pattern = re.compile('|'.join(escaped_keywords))

    word_counter = {} 

    def replace_func(match):
        word = match.group(0)
        current_count = word_counter.get(word, 0)
        word_counter[word] = current_count + 1
        
        # ID: 단어__순번
        unique_id = f"{word}__{current_count}"
        return f"<a href='javascript:void(0)' id='{unique_id}' class='highlight'>{word}</a>"

    highlighted_text = pattern.sub(replace_func, text)
    final_html = css_style + f"<div style='line-height:1.8; font-size:16px;'>{highlighted_text.replace(chr(10), '<br>')}</div>"
    return final_html

# --- 6. 데이터 동기화 ---
def sync_input():
    if "editor_key" in st.session_state:
        st.session_state.main_text = st.session_state.editor_key

# --- 7. 메인 앱 ---
def main():
    st.set_page_config(layout="wide", page_title="영웅 분석기")
    
    # CSS: 패널 Sticky 설정
    st.markdown("""
    <style>
    .stTextArea textarea { font-size: 16px; line-height: 1.6; }
    
    /* 패널 고정 */
    div[data-testid="stColumn"]:nth-of-type(2) > div,
    div[data-testid="stColumn"]:nth-of-type(3) > div {
        position: sticky;
        top: 4rem; 
        z-index: 999;
        background-color: white; 
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #f0f0f0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        max-height: 85vh; 
        overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("영웅 분석기")

    # 세션 초기화
    if 'main_text' not in st.session_state: st.session_state['main_text'] = ""
    if 'analyzed' not in st.session_state: st.session_state.analyzed = False
    if 'selected_keyword_id' not in st.session_state: st.session_state.selected_keyword_id = None

    # DB 로드
    sheet = get_db_connection()
    db_dict = {}
    if sheet:
        try:
            db_data = sheet.get_all_records()
            for row in db_data:
                t_word = str(row['target_word'])
                r_word = str(row['replace_word'])
                if t_word in db_dict:
                    db_dict[t_word] += f", {r_word}"
                else:
                    db_dict[t_word] = r_word
        except: pass

    # --- 레이아웃 ---
    col_left, col_mid, col_right = st.columns([5, 2, 2])

    with col_left:
        st.subheader("📝 원고 입력")
        st.text_area(
            "글을 입력하세요", 
            height=200, 
            key="editor_key",
            value=st.session_state['main_text'], 
            on_change=sync_input
        )
        
        if st.button("🔍 분석 시작", type="primary", use_container_width=True):
            st.session_state.main_text = st.session_state.editor_key
            st.session_state.analyzed = True
            st.session_state.selected_keyword_id = None
            st.rerun()

        st.divider()
        st.subheader("📄 교정 미리보기")
        st.caption("클릭한 위치의 단어만 수정됩니다.")
        
        current_text = st.session_state.main_text

        if st.session_state.analyzed and current_text:
            counts, targets = analyze_text_smart(current_text, db_dict.keys())
            html_content = create_interactive_html(current_text, targets)
            
            # 클릭 시 스크롤 위치 보존을 위해 클릭 처리 후 rerun 될 때 JS 실행됨
            clicked_id = click_detector(html_content)
            
            if clicked_id:
                st.session_state.selected_keyword_id = clicked_id
        else:
            st.info("분석을 시작하면 미리보기가 표시됩니다.")

    # 중간 & 오른쪽 패널
    if st.session_state.analyzed and current_text:
        counts, targets = analyze_text_smart(current_text, db_dict.keys())
        sorted_targets = sorted(targets, key=lambda x: counts.get(x, 0), reverse=True)
        
        with col_mid:
            st.subheader("📊 반복 횟수")
            if sorted_targets:
                df = pd.DataFrame([(k, counts[k]) for k in sorted_targets], columns=['키워드', '횟수'])
                st.dataframe(df, hide_index=True, use_container_width=True, height=500)
            else:
                st.caption("감지된 키워드가 없습니다.")

        with col_right:
            st.subheader("편집기")
            sel_id = st.session_state.selected_keyword_id
            
            target_word = None
            target_idx = 0

            if sel_id:
                try:
                    parts = sel_id.split("__")
                    target_word = parts[0]
                    target_idx = int(parts[1])
                except:
                    target_word = sel_id

            if not target_word:
                st.info("👈 왼쪽 미리보기에서 단어를 클릭하세요.")
            else:
                st.markdown(f"### 선택: **'{target_word}'** ({target_idx + 1}번째)")
                st.write(f"전체 등장: **{counts.get(target_word, 0)}회**")

                st.divider()
                tab_fix, tab_add, tab_manual = st.tabs(["🔄 대체어", "➕ DB추가", "✍️ 수정"])
                
                # 1. DB 대체어
                with tab_fix:
                    norm_target = normalize_word(target_word)
                    search_key = norm_target if norm_target and norm_target in db_dict else target_word
                    
                    if search_key in db_dict:
                        replacements = [w.strip() for w in db_dict[search_key].split(',') if w.strip()]
                        st.success(f"추천 대체어:")
                        for rep in replacements:
                            if st.button(f"👉 '{rep}'로 변경", key=f"btn_{sel_id}_{rep}", use_container_width=True):
                                # N번째 단어만 교체
                                new_text = replace_nth_occurrence(current_text, target_word, rep, target_idx)
                                st.session_state.main_text = new_text
                                st.session_state.selected_keyword_id = None 
                                st.toast(f"변경 완료: '{target_word}' -> '{rep}'")
                                st.rerun()
                    else:
                        st.warning("등록된 대체어가 없습니다.")

                # 2. DB 추가
                with tab_add:
                    st.markdown(f"**'{search_key}'** DB 추가")
                    new_sub = st.text_input("대체어 입력", key=f"new_db_{sel_id}")
                    msg_box = st.empty()

                    if st.button("💾 DB 저장", key=f"save_{sel_id}", use_container_width=True):
                        if new_sub and sheet:
                            try:
                                sheet.append_row([search_key, new_sub])
                                msg_box.success("저장 완료!")
                                time.sleep(1)
                                st.rerun()
                            except: 
                                msg_box.error("저장 실패")

                # 3. 직접 수정
                with tab_manual:
                    manual_val = st.text_input("직접 입력", key=f"manual_{sel_id}")
                    if st.button("적용", key=f"apply_{sel_id}", use_container_width=True, type="primary"):
                        if manual_val:
                            new_text = replace_nth_occurrence(current_text, target_word, manual_val, target_idx)
                            st.session_state.main_text = new_text
                            st.session_state.selected_keyword_id = None
                            st.toast("수정되었습니다.")
                            st.rerun()

    # [하단] 최종 원고
    st.divider()
    st.subheader("✅ 최종 결과")
    st.code(st.session_state.main_text, language=None)
    
    # [핵심] 모든 렌더링이 끝난 마지막 시점에 스크롤 복구 스크립트 실행
    inject_scroll_keeper()

if __name__ == "__main__":
    main()
