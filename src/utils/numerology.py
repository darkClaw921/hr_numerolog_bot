"""
Модуль для нумерологических расчетов по дате рождения.
Реализует алгоритм расчета матрицы и дополнительных чисел.

Это источник истины алгоритма. Модуль не зависит от aiogram/БД и пригоден для
переиспользования будущим ботом совместимости (через общий пакет или копию).
"""
from typing import Dict, List, Tuple
from datetime import datetime, date

# Версия алгоритма расчёта. Хранится вместе со снапшотом результата в БД, чтобы
# бот совместимости мог определить устаревший кэш и пересчитать из даты рождения.
CALC_VERSION = 1

# Ключи коэффициентов секторов, которые обязаны присутствовать в результате.
REQUIRED_COEF_KEYS = (
    "sector_temperament",
    "sector_life",
    "sector_purpose",
    "sector_family",
)


def parse_date(date_str: str) -> Tuple[int, int, int]:
    """
    Парсит строку даты в формате DD.MM.YYYY.
    
    Args:
        date_str: Строка с датой в формате DD.MM.YYYY
        
    Returns:
        Кортеж (день, месяц, год)
        
    Raises:
        ValueError: Если дата неверного формата
    """
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        return date_obj.day, date_obj.month, date_obj.year
    except ValueError:
        raise ValueError("Неверный формат даты. Используйте DD.MM.YYYY (например, 18.08.1984)")


def sum_digits(number: int) -> int:
    """
    Суммирует все цифры числа до получения однозначного числа.
    
    Args:
        number: Число для суммирования
        
    Returns:
        Однозначное число (1-9) или 0
    """
    while number >= 10:
        number = sum(int(digit) for digit in str(number))
    return number


def calculate_first_additional(date_str: str) -> int:
    """
    Вычисляет первое дополнительное число: сумма всех цифр даты рождения.
    
    Args:
        date_str: Дата в формате DD.MM.YYYY
        
    Returns:
        Первое дополнительное число
    """
    # Убираем точки и суммируем все цифры
    digits = [int(d) for d in date_str if d.isdigit()]
    return sum(digits)


def calculate_second_additional(first_additional: int) -> int:
    """
    Вычисляет второе дополнительное число: сумма цифр первого дополнительного.
    
    Args:
        first_additional: Первое дополнительное число
        
    Returns:
        Второе дополнительное число
    """
    return sum(int(d) for d in str(first_additional))


def calculate_third_additional(first_additional: int, first_digit_of_date: int) -> int:
    """
    Вычисляет третье дополнительное число.
    
    Формула: первое_дополнительное - (2 * первая_цифра_даты)
    Если первая цифра даты 0, берется первая ненулевая цифра.
    
    Args:
        first_additional: Первое дополнительное число
        first_digit_of_date: Первая цифра даты рождения
        
    Returns:
        Третье дополнительное число
    """
    return first_additional - (2 * first_digit_of_date)


def calculate_fourth_additional(third_additional: int) -> int:
    """
    Вычисляет четвертое дополнительное число: сумма цифр третьего дополнительного.
    
    Args:
        third_additional: Третье дополнительное число
        
    Returns:
        Четвертое дополнительное число
    """
    return sum(int(d) for d in str(third_additional))


def fill_matrix(date_str: str, first_add: int, second_add: int, 
                third_add: int, fourth_add: int) -> Dict[int, List[int]]:
    """
    Заполняет матрицу (секторы 1-9) числами из даты и дополнительных чисел.
    
    Args:
        date_str: Дата в формате DD.MM.YYYY
        first_add: Первое дополнительное число
        second_add: Второе дополнительное число
        third_add: Третье дополнительное число
        fourth_add: Четвертое дополнительное число
        
    Returns:
        Словарь {сектор: [список чисел]}
    """
    matrix = {i: [] for i in range(1, 10)}
    
    # Собираем все числа для анализа
    all_numbers = []
    
    # Добавляем цифры из даты
    for char in date_str:
        if char.isdigit():
            digit = int(char)
            if digit != 0:
                all_numbers.append(digit)
    
    # Добавляем цифры из дополнительных чисел
    for num in [first_add, second_add, third_add, fourth_add]:
        for digit in str(num):
            digit_int = int(digit)
            if digit_int != 0:
                all_numbers.append(digit_int)
    
    # Распределяем числа по секторам
    for digit in all_numbers:
        if 1 <= digit <= 9:
            matrix[digit].append(digit)
    
    return matrix


def calculate_sector_coefficient(matrix: Dict[int, List[int]], sectors: List[int]) -> int:
    """
    Вычисляет коэффициент сектора как сумму количества цифр в указанных секторах.
    
    Args:
        matrix: Заполненная матрица
        sectors: Список номеров секторов для расчета
        
    Returns:
        Коэффициент сектора
    """
    return sum(len(matrix[sector]) for sector in sectors)


def calculate_destiny_number(date_str: str) -> int:
    """
    Вычисляет Число Судьбы: сумма всех цифр даты.
    Если получается 11, останавливается и возвращает 11 (мастер-число).
    Иначе приводит к однозначному числу.
    
    Args:
        date_str: Дата в формате DD.MM.YYYY
        
    Returns:
        Число Судьбы (1-9 или 11)
    """
    first_add = calculate_first_additional(date_str)
    # Если первое дополнительное число уже однозначное, возвращаем его
    if first_add < 10:
        return first_add
    
    # Суммируем цифры первого дополнительного числа
    result = sum(int(d) for d in str(first_add))
    
    # Если получилось 11, останавливаемся (мастер-число)
    if result == 11:
        return 11
    
    # Иначе приводим к однозначному
    return sum_digits(result)


def calculate_all(date_str: str) -> Dict:
    """
    Выполняет все расчеты для даты рождения.
    
    Args:
        date_str: Дата в формате DD.MM.YYYY
        
    Returns:
        Словарь со всеми результатами расчетов
    """
    # Парсим дату
    day, month, year = parse_date(date_str)
    
    # Определяем первую цифру дня для расчета третьего дополнительного числа
    # Если день начинается с 0 (например, 05), берем следующую цифру (5)
    day_str = str(day).zfill(2)  # Дополняем до 2 цифр с нулем слева
    if day_str[0] == '0':
        first_digit = int(day_str[1])  # Берем вторую цифру, если первая 0
    else:
        first_digit = int(day_str[0])  # Берем первую цифру дня
    
    # Шаг 1: Первое дополнительное число
    first_additional = calculate_first_additional(date_str)
    
    # Шаг 2: Второе дополнительное число
    second_additional = calculate_second_additional(first_additional)
    
    # Шаг 3: Третье дополнительное число
    third_additional = calculate_third_additional(first_additional, first_digit)
    
    # Шаг 4: Четвертое дополнительное число
    fourth_additional = calculate_fourth_additional(third_additional)
    
    # Шаг 5: Заполняем матрицу
    matrix = fill_matrix(date_str, first_additional, second_additional, 
                        third_additional, fourth_additional)
    
    # Шаг 6: Сектор темперамент (3/5/7 по диагонали)
    # В матрице 3x3: сектор 3 (верхний правый), 5 (центр), 7 (нижний левый)
    # Но по описанию это диагональ, значит: 3, 5, 7
    sector_temperament = calculate_sector_coefficient(matrix, [3, 5, 7])
    
    # Шаг 7: Сектор быт (4/5/6)
    sector_life = calculate_sector_coefficient(matrix, [4, 5, 6])
    
    # Шаг 8: Сектор цель (1/4/7)
    sector_purpose = calculate_sector_coefficient(matrix, [1, 4, 7])
    
    # Шаг 9: Сектор семья (2/5/8)
    sector_family = calculate_sector_coefficient(matrix, [2, 5, 8])
    
    # Шаг 10: Число Судьбы
    destiny_number = calculate_destiny_number(date_str)
    
    return {
        "date": date_str,
        "first_additional": first_additional,
        "second_additional": second_additional,
        "third_additional": third_additional,
        "fourth_additional": fourth_additional,
        "matrix": matrix,
        "sector_temperament": sector_temperament,
        "sector_life": sector_life,
        "sector_purpose": sector_purpose,
        "sector_family": sector_family,
        "destiny_number": destiny_number
    }


def format_date_for_calc(value: date) -> str:
    """
    Превращает объект date в строку DD.MM.YYYY с ведущими нулями.

    Алгоритм расчёта чувствителен к строковому представлению (нули в дне/месяце
    влияют на сумму цифр), поэтому дату из БД нужно форматировать детерминированно
    именно так, как её вводит пользователь (regex ^\\d{2}\\.\\d{2}\\.\\d{4}$).

    Args:
        value: дата рождения как datetime.date

    Returns:
        Строка в формате DD.MM.YYYY
    """
    return value.strftime("%d.%m.%Y")


def validate_results(results: Dict) -> None:
    """
    Проверяет полноту результатов расчёта перед показом/сохранением.

    Закрывает пункт ТЗ «коэффициенты секторов проверяем на полноту»: гарантирует,
    что все коэффициенты посчитаны, матрица содержит все 9 секторов, а Число Судьбы
    присутствует. Защищает от KeyError/None в форматировании, отчёте и кабинете.

    Args:
        results: словарь из calculate_all()

    Raises:
        ValueError: если результаты неполны или некорректны
    """
    missing = [k for k in REQUIRED_COEF_KEYS if results.get(k) is None]
    if missing:
        raise ValueError(f"Не посчитаны коэффициенты секторов: {', '.join(missing)}")

    matrix = results.get("matrix")
    if not isinstance(matrix, dict) or set(matrix.keys()) != set(range(1, 10)):
        raise ValueError("Матрица неполна: ожидаются секторы 1-9")

    if results.get("destiny_number") is None:
        raise ValueError("Не посчитано Число Судьбы")
