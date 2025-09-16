from streamlit import columns, button
from go import *


# Панель навигации
def render_navigation():
    col1, col4 = columns([1, 1])
    
    with col1:
        if button("🏠 Главная", use_container_width=True):
            go_home()
    
    with col4:
        if button("📋 История", use_container_width=True):
            go_to_page('history')