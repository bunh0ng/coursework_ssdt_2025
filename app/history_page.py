import streamlit as st
import pandas as pd
import plotly.express as px



# Страница истории
def history_page():
    st.title("📋 История оценок")
    st.markdown("---")
    
    if 'history_data' not in st.session_state or not st.session_state.history_data:
        st.info("История оценок пуста")
        return
    
    history_df = pd.DataFrame(st.session_state.history_data)
    
    # Показываем последние оценки
    st.subheader("Последние оценки")
    for i, row in enumerate(reversed(history_df.to_dict('records')[:5])):
        with st.expander(f"{row['mark']} {row['model']} - {row['price']:,.0f} ₽"):
            st.write(f"**Год:** {row['year']}")
            st.write(f"**Пробег:** {row['probeg']:,.0f} км")
            st.write(f"**Состояние:** {row['condition']}")
            st.write(f"**Время оценки:** {row['timestamp']}")
    
    # График истории
    if len(history_df) > 1:
        st.markdown("---")
        st.subheader("Статистика оценок")
        
        history_df['timestamp_dt'] = pd.to_datetime(history_df['timestamp'])
        fig = px.line(history_df, x='timestamp_dt', y='price', 
                     title='Динамика оценок во времени')
        st.plotly_chart(fig, use_container_width=True)