from streamlit import session_state

# Функции навигации
def go_to_page(page_name):
    session_state.page = page_name
    if page_name != 'history':
        session_state.history.append(page_name)

def go_back():
    if len(session_state.history) > 1:
        session_state.history.pop()
        session_state.page = session_state.history[-1]
    else:
        session_state.page = 'main'

def go_home():
    session_state.page = 'main'
    session_state.history = ['main']