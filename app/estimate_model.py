# Функции для оценки стоимости
def estimate_price_basic(marka, model, year, probeg, engine_volume, condition):
    """Базовая модель оценки"""
    base_prices = {
        'Toyota': 1, 'BMW': 1, 'Mercedes': 1,
        'Audi': 1, 'Volkswagen': 1, 'Lada': 1,
        'Kia': 1, 'Hyundai': 1, 'default': 1
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