import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# Настройка страницы
st.set_page_config(
    page_title="Car Appraisal System",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Функции для оценки стоимости
def estimate_price_basic(marka, model, year, probeg, engine_volume, condition):
    """Базовая модель оценки"""
    base_prices = {
        'Toyota': 600000, 'BMW': 800000, 'Mercedes': 850000,
        'Audi': 750000, 'Volkswagen': 500000, 'Lada': 300000,
        'Kia': 450000, 'Hyundai': 420000, 'default': 500000
    }
    
    base_price = base_prices.get(marka, base_prices['default'])
    
    # Модификаторы
    year_mod = (year - 2000) * 15000
    probeg_mod = -probeg * 0.5
    engine_mod = engine_volume * 50000
    
    condition_mod = {
        'Отличное': 1.2,
        'Хорошее': 1.0,
        'Удовлетворительное': 0.8,
        'Плохое': 0.6
    }.get(condition, 1.0)
    
    price = (base_price + year_mod + probeg_mod + engine_mod) * condition_mod
    return max(price, 100000)

def generate_sample_data():
    """Генерация примерных данных для визуализации"""
    np.random.seed(42)
    data = []
    
    for _ in range(100):
        year = np.random.randint(2000, 2024)
        probeg = np.random.randint(0, 300000)
        price = estimate_price_basic(
            np.random.choice(['Toyota', 'BMW', 'Lada', 'Kia', 'Hyundai']),
            'Model',
            year,
            probeg,
            np.random.uniform(1.5, 3.0),
            np.random.choice(['Отличное', 'Хорошее', 'Удовлетворительное'])
        ) * np.random.uniform(0.8, 1.2)
        
        data.append({
            'Марка': np.random.choice(['Toyota', 'BMW', 'Lada', 'Kia', 'Hyundai']),
            'Год': year,
            'Пробег': probeg,
            'Цена': price,
            'Объем_двигателя': np.random.uniform(1.5, 3.0)
        })
    
    return pd.DataFrame(data)

# Инициализация состояния сессии
if 'page' not in st.session_state:
    st.session_state.page = 'main'
if 'car_data' not in st.session_state:
    st.session_state.car_data = {}
if 'history' not in st.session_state:
    st.session_state.history = []

# Функции навигации
def go_to_page(page_name):
    st.session_state.page = page_name
    if page_name != 'history':
        st.session_state.history.append(page_name)

def go_back():
    if len(st.session_state.history) > 1:
        st.session_state.history.pop()
        st.session_state.page = st.session_state.history[-1]
    else:
        st.session_state.page = 'main'

def go_home():
    st.session_state.page = 'main'
    st.session_state.history = ['main']

# Панель навигации
def render_navigation():
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 2])
    
    with col1:
        if st.button("🏠 Главная", use_container_width=True):
            go_home()
    
    with col2:
        if st.button("📊 Аналитика", use_container_width=True):
            go_to_page('analytics')
    
    with col3:
        if st.button("📈 Сравнение", use_container_width=True):
            go_to_page('comparison')
    
    with col4:
        if st.button("📋 История", use_container_width=True):
            go_to_page('history')
    
    with col5:
        if st.session_state.page != 'main':
            if st.button("⬅️ Назад", use_container_width=True):
                go_back()

# Главная страница
def main_page():
    st.title("🚗 Система оценки стоимости автомобиля")
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.header("Данные автомобиля")
        
        st.session_state.car_data['marka'] = st.selectbox(
            "Марка автомобиля",
            ['Toyota', 'BMW', 'Mercedes', 'Audi', 'Volkswagen', 'Lada', 'Kia', 'Hyundai']
        )
        
        st.session_state.car_data['model'] = st.text_input("Модель", "Camry")
        
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
            st.session_state.car_data['marka'],
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

# Страница аналитики
def analytics_page():
    st.title("📊 Аналитика рынка")
    st.markdown("---")
    
    # Генерация примерных данных
    df = generate_sample_data()
    
    tab1, tab2, tab3 = st.tabs(["Распределение цен", "Зависимость от параметров", "Тренды"])
    
    with tab1:
        fig1 = px.histogram(df, x='Цена', nbins=20, title='Распределение цен на автомобили')
        st.plotly_chart(fig1, use_container_width=True)
    
    with tab2:
        col1, col2 = st.columns(2)
        
        with col1:
            fig2 = px.scatter(df, x='Год', y='Цена', color='Марка', 
                            title='Цена vs Год выпуска')
            st.plotly_chart(fig2, use_container_width=True)
        
        with col2:
            fig3 = px.scatter(df, x='Пробег', y='Цена', color='Марка',
                            title='Цена vs Пробег')
            st.plotly_chart(fig3, use_container_width=True)
    
    with tab3:
        trend_df = df.groupby('Год').agg({'Цена': 'mean'}).reset_index()
        fig4 = px.line(trend_df, x='Год', y='Цена', title='Средняя цена по годам выпуска')
        st.plotly_chart(fig4, use_container_width=True)

# Страница сравнения
def comparison_page():
    st.title("📈 Сравнение автомобилей")
    st.markdown("---")
    
    st.info("Добавьте несколько автомобилей для сравнения")
    
    if 'comparison_list' not in st.session_state:
        st.session_state.comparison_list = []
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Добавить автомобиль")
        new_car = {
            'marka': st.selectbox("Марка", ['Toyota', 'BMW', 'Mercedes', 'Lada']),
            'model': st.text_input("Модель", "Model"),
            'year': st.slider("Год", 2000, 2024, 2020),
            'price': st.number_input("Цена (руб)", min_value=0, value=1000000)
        }
        
        if st.button("➕ Добавить к сравнению"):
            st.session_state.comparison_list.append(new_car)
            st.success("Автомобиль добавлен!")
    
    with col2:
        st.subheader("Список для сравнения")
        if not st.session_state.comparison_list:
            st.warning("Добавьте автомобили для сравнения")
        else:
            for i, car in enumerate(st.session_state.comparison_list):
                st.write(f"{i+1}. {car['marka']} {car['model']} ({car['year']}) - {car['price']:,.0f} ₽")
            
            if st.button("🧹 Очистить список"):
                st.session_state.comparison_list = []
    
    if st.session_state.comparison_list:
        st.markdown("---")
        st.subheader("Визуальное сравнение")
        
        comparison_df = pd.DataFrame(st.session_state.comparison_list)
        fig = px.bar(comparison_df, x='marka', y='price', color='model',
                    title='Сравнение цен автомобилей')
        st.plotly_chart(fig, use_container_width=True)

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
        with st.expander(f"{row['marka']} {row['model']} - {row['price']:,.0f} ₽"):
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

# Основной рендеринг
def main():
    render_navigation()
    st.markdown("---")
    
    if st.session_state.page == 'main':
        main_page()
    elif st.session_state.page == 'analytics':
        analytics_page()
    elif st.session_state.page == 'comparison':
        comparison_page()
    elif st.session_state.page == 'history':
        history_page()

if __name__ == "__main__":
    main()