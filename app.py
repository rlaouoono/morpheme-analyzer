import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
from st_click_detector import click_detector
import time

# --- 1. [스크롤 고정 끝판왕] JS + CSS 강제 ---
def inject_scroll_keeper():
    js = """
    <script>
        // 1. 스크롤 동작을 '즉시(instant)'로 변경하여 부드러운 애니메이션 제거 (튀는 원인 차단)
        document.documentElement.style.scrollBehavior = 'auto';
        
        // 2. 부모 윈도우(실제 브라우저) 스크롤 위치 제어
        try {
            var parentWindow = window.parent;
            
            // 스크롤 이벤트 발생 시 로컬 스토리지에 저장 (세션보다 강력)
            parentWindow.addEventListener('scroll', function() {
                parentWindow.localStorage.setItem('savedScroll', parentWindow.scrollY);
            });

            // 위치 복원 함수
            function restoreScroll() {
                var savedPos = parentWindow.localStorage.getItem('savedScroll');
                if (savedPos) {
                    parentWindow.scrollTo({
                        top: parseInt(savedPos),
                        behavior: 'instant' // 애니메이션 없이 즉시 이동
                    });
                }
            }

            // 렌더링 직후 반복 실행하여 위치 강제 고정
            restoreScroll();
            setTimeout(restoreScroll, 50);
            setTimeout(restoreScroll, 100);
            setTimeout(restoreScroll, 300);
            
        } catch(e) { console.log(e); }
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

# [NEW] 문장 단위 추출 및 교체 함수
def get_sentence_context(text, target_word, n):
    indices = [m.start() for m in re.finditer(re.escape(target_word), text)]
    if n >= len(indices): return None, None, None
    
    start_idx = indices[n]
    
    # 문장 시작 찾기 (. ? ! 줄바꿈)
    sent_start = max(text.rfind('.', 0, start_idx), text.rfind('?', 0, start_idx), text.rfind('!', 0, start_idx), text.rfind('\n', 0, start_idx))
    if sent_start == -1: sent_start = 0
    else: sent_start += 1 # 구두점 다음부터
    
    # 문장 끝 찾기
    sent_end = min([i for i in [text.find('.', start_idx), text.find('?', start_idx), text.find('!', start_idx), text.find('\n', start_idx), len(text)] if i != -1])
    if sent_end != len(text): sent_end += 1 # 구두점 포함
    
    original_sentence = text[sent_start:sent_end].strip()
    return original_sentence, sent_start, sent_end

def replace_sentence_range(text, start, end, new_sentence):
    return text[:start] + new_sentence + text[end:]

# --- 3. HTML 생성 ---
def create_interactive_html(text, keywords, filter_word=None):
    css_style = """
    <style>
        .highlight {
            background-color: #fff5b1; 
            padding: 2px 5px;  /* 노란 박스 크기 조절 */
            border-radius: 4px;
            font-weight: bold;
            border: 1px solid #fdd835; 
            color: #333; 
            text-decoration: none;
            margin: 0 2px;
            cursor: pointer;
        }
        .highlight:hover { background-color: #ffeb3b; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    </style>
    """
    
    if not keywords:
        return css_style + f"<div>{text.replace(chr(10), '<br>')}</div>"

    if filter_word:
        active_keywords = [k for k in keywords if k == filter_word]
    else:
        active_keywords = keywords

    sorted_keywords = sorted(keywords, key=len, reverse=True)
    escaped_keywords = [re.escape(kw) for kw in sorted_keywords]
    pattern = re.compile('|'.join(escaped_keywords))

    word_counter = {} 

    def replace_func(match):
        word = match.group(0)
        
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

    if 'main_text' not in st.session_state: st.session_state['main_text'] = ""
    if 'analyzed' not in st.session_state: st.session_state.analyzed = False
    if 'selected_keyword_id' not in st.session_state: st.session_state.selected_keyword_id = None
    if 'filter_keyword' not in st.session_state: st.session_state.filter_keyword = None

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

    # --- 왼쪽: 원고 입력 & 미리보기 ---
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
        
        c1, c2 = st.columns([3, 1])
        with c1: st.subheader("📄 교정 미리보기")
        with c2:
            if st.session_state.analyzed:
                with st.popover("📋 원고 복사"):
                    st.code(st.session_state.main_text, language=None)
                    st.caption("우측 상단 아이콘 클릭하여 복사")

        current_text = st.session_state.main_text

        if st.session_state.analyzed and current_text:
            counts, targets = analyze_text_smart(current_text, db_dict.keys())
            
            filter_kw = st.session_state.filter_keyword
            if filter_kw:
                st.info(f"💡 '{filter_kw}' 단어만 확인 중입니다. (해제: 표 빈 곳 클릭)")
            else:
                st.caption("단어를 클릭하여 수정하세요.")

            html_content = create_interactive_html(current_text, targets, filter_word=filter_kw)
            
            clicked_id = click_detector(html_content)
            if clicked_id:
                st.session_state.selected_keyword_id = clicked_id
        else:
            st.info("원고를 입력하고 분석을 시작하세요.")

    # --- 가운데: 반복 횟수 ---
    with col_mid:
        st.subheader("📊 반복 횟수")
        if st.session_state.analyzed and (sorted_targets := sorted(targets, key=lambda x: counts.get(x, 0), reverse=True)):
            df = pd.DataFrame([(k, counts[k]) for k in sorted_targets], columns=['키워드', '횟수'])
            
            event = st.dataframe(
                df, hide_index=True, use_container_width=True, height=500,
                on_select="rerun", selection_mode="single-row"
            )
            
            if event.selection.rows:
                selected_idx = event.selection.rows[0]
                selected_word = df.iloc[selected_idx]['키워드']
                if st.session_state.filter_keyword != selected_word:
                    st.session_state.filter_keyword = selected_word
                    st.rerun()
            else:
                if st.session_state.filter_keyword is not None:
                    st.session_state.filter_keyword = None
                    st.rerun()
        else:
            st.caption("결과 없음")

    # --- 오른쪽: 편집기 (문맥 교정 기능 추가) ---
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
            
            # [NEW] 탭 순서 변경 및 '문맥' 탭 추가
            tab_fix, tab_context, tab_add = st.tabs(["🔄대체", "📝문맥", "➕DB"])
            
            # 1. 단순 대체
            with tab_fix: 
                norm = normalize_word(target_word)
                key = norm if norm and norm in db_dict else target_word
                if key in db_dict:
                    reps = [w.strip() for w in db_dict[key].split(',') if w.strip()]
                    st.caption("클릭 시 해당 단어만 변경됩니다.")
                    for rep in reps:
                        if st.button(f"👉 {rep}", key=f"btn_{sel_id}_{rep}", use_container_width=True):
                            new_text = replace_nth_occurrence(current_text, target_word, rep, target_idx)
                            st.session_state.main_text = new_text
                            st.session_state.selected_keyword_id = None
                            st.toast(f"변경 완료: {rep}")
                            st.rerun()
                else: st.warning("대체어 없음")

            # 2. [NEW] 문맥(문장) 교정 - 조사 수정용
            with tab_context:
                st.caption("단어가 포함된 문장 전체를 수정합니다. 조사가 어색할 때 사용하세요.")
                
                # 문장 추출
                orig_sent, s_start, s_end = get_sentence_context(current_text, target_word, target_idx)
                
                if orig_sent:
                    # 문장 수정용 텍스트 에어리어
                    edited_sent = st.text_area("문장 수정", value=orig_sent, height=100, key=f"ctx_{sel_id}")
                    
                    if st.button("문장 적용", key=f"apply_ctx_{sel_id}", type="primary", use_container_width=True):
                        # 전체 텍스트에서 해당 문장 구간 교체
                        new_text = replace_sentence_range(current_text, s_start, s_end, edited_sent)
                        st.session_state.main_text = new_text
                        st.session_state.selected_keyword_id = None
                        st.toast("문맥이 수정되었습니다.")
                        st.rerun()
                else:
                    st.error("문장을 찾을 수 없습니다.")

            # 3. DB 추가
            with tab_add:
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

if __name__ == "__main__":
    main()
