import streamlit as st
from app.history_page import history_page
from app.main_page import main_page

# Настройка страницы
st.set_page_config(
    page_title="Анализатор",
    layout="wide",
    page_icon="🤡",
    initial_sidebar_state="expanded"
)


# Инициализация состояния сессии
if 'page' not in st.session_state:
    st.session_state.page = 'main'
if 'car_data' not in st.session_state:
    st.session_state.car_data = {}

# Функции навигации
def go_to_page(page_name):
    st.session_state.page = page_name

def go_home():
    st.session_state.page = 'main'
    st.session_state.history = ['main']

# Панель навигации
def render_navigation():
    col1, col2= st.columns([1, 1])
    
    with col1:
        if st.button("🏠 Главная", use_container_width=True):
            go_home()
    
    with col2:
        if st.button("📋 История", use_container_width=True):
            go_to_page('history')

# Основной рендеринг
def main():
    render_navigation()
    st.markdown("---")
    
    if st.session_state.page == 'main':
        main_page()
    elif st.session_state.page == 'history':
        history_page()

if __name__ == "__main__":
    main()





