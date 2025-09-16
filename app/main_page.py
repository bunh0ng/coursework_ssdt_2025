from app.estimate_model import estimate_price_basic
from datetime import datetime
import streamlit as st
from next_page import next_page


# Главная страница
def main_page():
    st.title("🚗 Система оценки стоимости автомобиля")
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.header("Данные автомобиля")
        st.session_state.car_data['mark'] = st.selectbox("Марка автомобиля", open('marks_and_models/marks.txt', 'r', encoding='UTF-8').read().split('\n'))
        
        st.session_state.car_data['model'] = st.selectbox("Модель", open(f'marks_and_models/{st.session_state.car_data['mark']}.txt', 'r', encoding='UTF-8').read().split('\n'))
        
        st.session_state.car_data['year'] = st.slider(
            "Год выпуска", 
            min_value=1990, 
            max_value=2024, 
            value=2018
        )
        
        st.session_state.car_data['probeg'] = st.number_input(
            "Пробег (км)", 
            min_value=0, 
            max_value=1000000, 
            value=50000
        )
    
    with col2:
        st.header("Дополнительные параметры")
        
        st.session_state.car_data['engine_volume'] = st.slider(
            "Объем двигателя (л)",
            min_value=0.5,
            max_value=6.0,
            value=2.0,
            step=0.1
        )
        
        st.session_state.car_data['condition'] = st.selectbox(
            "Состояние",
            ["Отличное", "Хорошее", "Удовлетворительное", "Плохое"]
        )
        
        st.session_state.car_data['transmission'] = st.radio(
            "Коробка передач",
            ["Автомат", "Механика", "Робот", "Вариатор"]
        )
        
        st.session_state.car_data['fuel_type'] = st.selectbox(
            "Тип топлива",
            ["Бензин", "Дизель", "Гибрид", "Электро"]
        )
    
    if st.button("🎯 Оценить стоимость", type="primary", use_container_width=True):
        price = estimate_price_basic(
            st.session_state.car_data['mark'],
            st.session_state.car_data['model'],
            st.session_state.car_data['year'],
            st.session_state.car_data['probeg'],
            st.session_state.car_data['engine_volume'],
            st.session_state.car_data['condition']
        )
        
        st.success(f"### Оценочная стоимость: {price:,.0f} ₽")
        
        # Сохраняем в историю
        appraisal_data = {
            **st.session_state.car_data,
            'price': price,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        st.session_state.history_data = st.session_state.get('history_data', [])
        st.session_state.history_data.append(appraisal_data)