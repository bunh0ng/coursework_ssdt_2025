from render_navigation import render_navigation
from streamlit import session_state, markdown
from main_page import main_page
from history_page import history_page
import streamlit as st



# Настройка страницы
st.set_page_config(
    page_title="Car Appraisal System",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)


# Основной рендеринг
def main():
    render_navigation()
    markdown("---")
    
    if session_state.page == 'main':
        main_page()
    elif session_state.page == 'history':
        history_page()

if __name__ == "__main__":
    main()