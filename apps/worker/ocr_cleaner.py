"""
OCR Text Cleaner / Post-processor

Исправляет типичные ошибки OCR для русских текстов:
- Латиница вместо кириллицы (me → ше, ux → их)
- Неверные цифры в нумерации
- Артефакты формул и символов
- Переносы слов

Автор: TutorBot Team
"""

import re
from typing import Dict, List, Tuple


# ===========================================
# 1. Латиница → Кириллица
# ===========================================

# Похожие символы: латинская → кириллическая
LATIN_TO_CYRILLIC = {
    'a': 'а', 'A': 'А',
    'e': 'е', 'E': 'Е',
    'o': 'о', 'O': 'О',
    'p': 'р', 'P': 'Р',
    'c': 'с', 'C': 'С',
    'x': 'х', 'X': 'Х',
    'y': 'у', 'Y': 'У',
    'H': 'Н',
    'K': 'К', 'k': 'к',
    'M': 'М',
    'T': 'Т',
    'B': 'В',
    'm': 'т',  # часто путается в словах
}

# Частые OCR-ошибки: латинские последовательности → русские слова
LATIN_SEQUENCES = {
    # Окончания и части слов
    'me': 'ше',      # больше → боль-me
    'ux': 'их',      # их → ux
    'OHH': 'они',    # они → OHH
    'OHU': 'они',
    'pa3a': 'раза',  # раза → pa3a
    'pasa': 'раза',  # раза → pasa
    'pa3': 'раз',
    'caMbIX': 'самых',
    'yroJI': 'угол',
    'yrJIa': 'угла',
    'yroJIa': 'угла',
    'yrJIoB': 'углов',
    'CMeXHbIe': 'смежные',
    'CMeXHbIX': 'смежных',
    'cMeXHbIe': 'смежные',
    'paBHo': 'равно',
    'paBHa': 'равна',
    'paBHbI': 'равны',
    'MeHbme': 'меньше',
    'MeHee': 'менее',
    '6oJIbme': 'больше',
    '6oJIee': 'более',
    'HafiTH': 'найти',
    'HafiAHTe': 'найдите',
    'HaiTH': 'найти',
    '3HaK': 'знак',
    'qepTa': 'черта',
    'npHMofi': 'прямой',
    'OCTpbIfi': 'острый',
    'TynOfi': 'тупой',
    '3aAaqH': 'задачи',
    '3aAaqa': 'задача',
    'OTBeT': 'ответ',
    'OTBeTbI': 'ответы',
    'pemeHHe': 'решение',
    'ynpaxHeHHe': 'упражнение',
    'ynp': 'упр',
    'AoKa3aTb': 'доказать',
    'TeopeMa': 'теорема',
    'onpeAeJIeHHe': 'определение',
    'cBofiCTBo': 'свойство',
    'CJIeACTBHe': 'следствие',
    'aKCHoMa': 'аксиома',
    'naparpaa)': 'параграф',
    'naparpap': 'параграф',
    'rJIaBa': 'глава',
}

# Частые одиночные замены внутри слов
INLINE_FIXES = [
    (r'6o([лЛ])', r'бо\1'),           # 6ольше → больше
    (r'([а-яА-Я])6([а-яА-Я])', r'\1б\2'),  # 6 внутри слова → б
    (r'([а-яА-Я])3([а-яА-Я])', r'\1з\2'),  # 3 внутри слова → з  
    (r'([а-яА-Я])0([а-яА-Я])', r'\1о\2'),  # 0 внутри слова → о
    (r'([а-яА-Я])1([а-яА-Я])', r'\1і\2'),  # 1 внутри слова → i (редко)
]


def fix_latin_to_cyrillic(text: str) -> str:
    """Replace Latin characters that look like Cyrillic in Russian context."""
    
    # 1. Сначала фиксим известные последовательности
    for lat, cyr in LATIN_SEQUENCES.items():
        text = text.replace(lat, cyr)
    
    # 2. Затем смешанные слова (латинские буквы внутри кириллических слов)
    def fix_mixed_word(match):
        word = match.group(0)
        # Если слово содержит и кириллицу и латиницу - конвертим латиницу
        has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in word)
        has_latin = any('a' <= c.lower() <= 'z' for c in word)
        
        if has_cyrillic and has_latin:
            result = []
            for c in word:
                if c in LATIN_TO_CYRILLIC:
                    result.append(LATIN_TO_CYRILLIC[c])
                else:
                    result.append(c)
            return ''.join(result)
        return word
    
    # Ищем "слова" - последовательности букв
    text = re.sub(r'[a-zA-Zа-яА-ЯёЁ]+', fix_mixed_word, text)
    
    # 3. Inline fixes (цифры внутри слов)
    for pattern, replacement in INLINE_FIXES:
        text = re.sub(pattern, replacement, text)
    
    return text


# ===========================================
# 2. Исправление переносов
# ===========================================

def fix_hyphenation(text: str) -> str:
    """Fix word hyphenation from line breaks."""
    # "боль-\nше" → "больше"
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    # "боль- ше" → "больше"  
    text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
    return text


# ===========================================
# 3. Исправление нумерации
# ===========================================

def fix_numbering_in_context(text: str) -> str:
    """
    Fix numbering errors based on context.
    E.g., "1) ... 2) ... 8) ..." → "1) ... 2) ... 3) ..."
    """
    # Найти все нумерации вида "N)" где N - цифра
    pattern = r'\b(\d)\)'
    
    matches = list(re.finditer(pattern, text))
    
    if len(matches) < 2:
        return text
    
    # Проверяем последовательность
    result = text
    offset = 0
    expected_num = None
    
    for i, match in enumerate(matches):
        current_num = int(match.group(1))
        
        if expected_num is None:
            expected_num = current_num + 1
            continue
        
        # Если номер не совпадает с ожидаемым
        if current_num != expected_num and expected_num <= 9:
            # Скорее всего ошибка OCR
            # Проверяем что разница большая (8 вместо 3, не 4 вместо 3)
            if abs(current_num - expected_num) > 1:
                start = match.start() + offset
                end = match.end() + offset
                result = result[:start] + str(expected_num) + ')' + result[end:]
                offset += len(str(expected_num)) - len(match.group(0)) + 1
        
        expected_num = current_num + 1 if current_num == expected_num else expected_num + 1
    
    return result


# ===========================================
# 4. Формулы и математические символы
# ===========================================

MATH_FIXES = {
    # Градусы
    'градусов': '°',
    'градуса': '°',
    'градус ': '° ',
    '° °': '°',
    
    # Степени
    'm2': 'm²', 
    'м2': 'м²',
    'cm2': 'см²',
    'см2': 'см²',
    'm3': 'm³',
    'м3': 'м³',
    'cm3': 'см³',
    'см3': 'см³',
    
    # Дроби
    '1/2': '½',
    '1/3': '⅓',
    '1/4': '¼',
    '3/4': '¾',
    
    # Знаки
    '<=': '≤',
    '>=': '≥',
    '!=': '≠',
    '+-': '±',
    '~=': '≈',
    
    # Углы
    '<ABC': '∠ABC',
    '<АВС': '∠АВС',
    '/_': '∠',
    
    # Другое
    '||': '∥',  # параллельность
    '_|_': '⊥',  # перпендикулярность
}


def fix_math_symbols(text: str) -> str:
    """Fix common math symbol OCR errors."""
    for wrong, right in MATH_FIXES.items():
        text = text.replace(wrong, right)
    
    # Исправить "m?" где ? - артефакт от ³
    text = re.sub(r'm\?', 'm³', text)
    text = re.sub(r'м\?', 'м³', text)
    
    # Исправить "@" → "Q" в контексте (ЗА@)
    text = re.sub(r'([А-Я])@', r'\1Q', text)
    
    return text


# ===========================================
# 5. Контекстуальная обработка
# ===========================================

# Словарь частых слов в учебниках (для контекстной проверки)
COMMON_MATH_WORDS = {
    # Геометрия
    'угол', 'углы', 'угла', 'углов', 'угле', 'углом',
    'смежные', 'смежных', 'смежный', 'смежного',
    'вертикальные', 'вертикальный', 'вертикальных',
    'прямой', 'прямая', 'прямую', 'прямые', 'прямых',
    'острый', 'острые', 'острого', 'острых',
    'тупой', 'тупые', 'тупого', 'тупых',
    'развернутый', 'развернутые',
    'треугольник', 'треугольника', 'треугольники', 'треугольников',
    'квадрат', 'квадрата', 'квадраты',
    'прямоугольник', 'прямоугольника',
    'окружность', 'окружности',
    'радиус', 'радиуса', 'радиусом',
    'диаметр', 'диаметра',
    'периметр', 'периметра',
    'площадь', 'площади',
    'сторона', 'стороны', 'сторон', 'стороной',
    'вершина', 'вершины', 'вершин',
    'основание', 'основания',
    'высота', 'высоты', 'высот',
    'медиана', 'медианы',
    'биссектриса', 'биссектрисы',
    'перпендикуляр', 'перпендикулярны', 'перпендикулярно',
    'параллельны', 'параллельно', 'параллельные',
    'точка', 'точки', 'точек', 'точку',
    'отрезок', 'отрезка', 'отрезки', 'отрезков',
    'луч', 'луча', 'лучи', 'лучей',
    'плоскость', 'плоскости',
    
    # Алгебра
    'уравнение', 'уравнения', 'уравнений',
    'неравенство', 'неравенства',
    'выражение', 'выражения',
    'формула', 'формулы', 'формул',
    'корень', 'корни', 'корней',
    'решение', 'решения', 'решений',
    'ответ', 'ответы', 'ответов',
    'значение', 'значения', 'значений',
    'переменная', 'переменные', 'переменной',
    'коэффициент', 'коэффициенты',
    'множитель', 'множители',
    'делитель', 'делители',
    'делимое', 'делимого',
    'частное', 'частного',
    'произведение', 'произведения',
    'сумма', 'суммы', 'сумм',
    'разность', 'разности',
    'дробь', 'дроби', 'дробей',
    'числитель', 'числителя',
    'знаменатель', 'знаменателя',
    'степень', 'степени', 'степеней',
    'показатель', 'показателя',
    'функция', 'функции', 'функций',
    'график', 'графика', 'графики',
    
    # Общие
    'найдите', 'найти', 'найден',
    'вычислите', 'вычислить',
    'докажите', 'доказать', 'доказательство',
    'определите', 'определить',
    'постройте', 'построить', 'построение',
    'решите', 'решить',
    'упростите', 'упростить',
    'сравните', 'сравнить',
    'равно', 'равны', 'равна', 'равен',
    'больше', 'меньше',
    'если', 'когда', 'тогда',
    'дано', 'данный', 'данные',
    'известно', 'известный',
    'следовательно', 'значит', 'поэтому',
    'теорема', 'теоремы', 'теорем',
    'определение', 'определения',
    'свойство', 'свойства', 'свойств',
    'признак', 'признаки', 'признаков',
    'аксиома', 'аксиомы',
    'следствие', 'следствия',
}

# Общие OCR-ошибки по контексту (паттерн → исправление)
CONTEXTUAL_FIXES = [
    # "сме.ные углы" → "смежные углы" (точка вместо ж)
    (r'сме[.]ные', 'смежные'),
    (r'CME[.]HbIe', 'смежные'),
    
    # Числа + градусы
    (r'(\d+)\s*rpanycoв', r'\1 градусов'),
    (r'(\d+)\s*rpaдycoв', r'\1 градусов'),
    (r'(\d+)\s*rpaдyc', r'\1 градус'),
    
    # "один из них" паттерны
    (r'oдuн\s+uз\s+нux', 'один из них'),
    (r'oдин\s+из\s+ниx', 'один из них'),
    (r'oдин\s+из\s+нux', 'один из них'),
    
    # "в N раз(а)" паттерны  
    (r'в\s+(\d+)\s*pa[3з]a?', r'в \1 раза'),
    (r'в\s+(\d+)\s*pa[3з]', r'в \1 раз'),
    
    # Теоремы и определения
    (r'[tт]еорема', 'теорема'),
    (r'oпределение', 'определение'),
    (r'cвойство', 'свойство'),
    (r'дoказательство', 'доказательство'),
    (r'дока[3з]ательство', 'доказательство'),
    
    # Распространённые окончания
    (r'(\w+)ckuu\b', r'\1ский'),
    (r'(\w+)ckuй\b', r'\1ский'),
    (r'(\w+)ецкий\b', r'\1ецкий'),
]


def apply_contextual_fixes(text: str) -> str:
    """
    Apply context-aware fixes based on common patterns in textbooks.
    """
    for pattern, replacement in CONTEXTUAL_FIXES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    return text


def fix_words_by_dictionary(text: str, max_words: int = 200) -> str:
    """
    Fix words that are close to known dictionary words.
    Uses simple edit distance for common words.
    
    Args:
        text: Input text
        max_words: Maximum number of words to process (for performance)
    """
    words = text.split()
    
    # Performance optimization: skip if too many words
    if len(words) > max_words:
        return text
    
    fixed_words = []
    
    # Pre-filter dictionary by length buckets for faster lookup
    dict_by_len = {}
    for w in COMMON_MATH_WORDS:
        wlen = len(w)
        if wlen not in dict_by_len:
            dict_by_len[wlen] = []
        dict_by_len[wlen].append(w)
    
    for word in words:
        # Убираем пунктуацию для сравнения
        clean_word = re.sub(r'[^\w]', '', word.lower())
        
        if len(clean_word) < 4 or len(clean_word) > 15:
            fixed_words.append(word)
            continue
        
        # Quick check - if already in dictionary, skip
        if clean_word in COMMON_MATH_WORDS:
            fixed_words.append(word)
            continue
        
        # Only check words with similar length
        best_match = None
        best_distance = 3  # Only accept up to 2 errors
        
        for delta in [0, 1, -1, 2, -2]:
            target_len = len(clean_word) + delta
            if target_len not in dict_by_len:
                continue
            
            for known_word in dict_by_len[target_len]:
                # Quick filter: first char should match or differ by 1
                if clean_word[0] != known_word[0]:
                    continue
                
                distance = levenshtein_simple(clean_word, known_word)
                
                if distance < best_distance:
                    best_distance = distance
                    best_match = known_word
                    if distance == 1:  # Good enough
                        break
            
            if best_distance == 1:
                break
        
        if best_match and best_distance > 0 and best_distance < 3:
            # Сохраняем регистр и пунктуацию оригинала
            fixed = preserve_case(word, best_match)
            fixed_words.append(fixed)
        else:
            fixed_words.append(word)
    
    return ' '.join(fixed_words)


def levenshtein_simple(s1: str, s2: str) -> int:
    """
    Simple Levenshtein distance calculation.
    For performance, only calculates for short strings.
    """
    if len(s1) > 15 or len(s2) > 15:
        return abs(len(s1) - len(s2))
    
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def preserve_case(original: str, replacement: str) -> str:
    """
    Apply the case pattern of original to replacement.
    """
    # Извлекаем пунктуацию
    prefix = ''
    suffix = ''
    
    while original and not original[0].isalpha():
        prefix += original[0]
        original = original[1:]
    
    while original and not original[-1].isalpha():
        suffix = original[-1] + suffix
        original = original[:-1]
    
    if not original:
        return prefix + replacement + suffix
    
    # Применяем регистр
    result = []
    for i, char in enumerate(replacement):
        if i < len(original):
            if original[i].isupper():
                result.append(char.upper())
            else:
                result.append(char.lower())
        else:
            result.append(char)
    
    return prefix + ''.join(result) + suffix


def fix_mathematical_context(text: str) -> str:
    """
    Fix OCR errors in mathematical expressions context.
    """
    # Исправляем переменные в уравнениях: "2x" но не "2 икс"
    # "2х" (кириллический х) → "2x" (латинский x) в мат. контексте
    text = re.sub(r'(\d)х\b', r'\1x', text)  # 2х → 2x
    text = re.sub(r'\bх(\d)', r'x\1', text)  # х2 → x2
    
    # Исправляем y/у в мат. контексте
    text = re.sub(r'(\d)у\b', r'\1y', text)  # 2у → 2y
    text = re.sub(r'\bу\s*=', r'y =', text)  # у = → y =
    
    # Знак умножения
    text = re.sub(r'(\d)\s*[хx]\s*(\d)', r'\1 × \2', text)  # 2 x 3 → 2 × 3
    
    # Скобки в формулах
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    
    # Знак равенства
    text = re.sub(r'\s+=\s+', ' = ', text)
    
    return text


def fix_sentence_boundaries(text: str) -> str:
    """
    Fix sentence boundary issues from OCR.
    """
    # Пробел после точки перед заглавной
    text = re.sub(r'\.([А-ЯA-Z])', r'. \1', text)
    
    # Пробел после запятой
    text = re.sub(r',([а-яА-Яa-zA-Z])', r', \1', text)
    
    # Убрать пробел перед точкой/запятой
    text = re.sub(r'\s+([.,;:!?])', r'\1', text)
    
    return text


# ===========================================
# 6. Общая очистка
# ===========================================

def clean_whitespace(text: str) -> str:
    """Normalize whitespace."""
    # Множественные пробелы → один
    text = re.sub(r'[ \t]+', ' ', text)
    # Множественные переносы → два
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Пробелы в начале/конце строк
    text = '\n'.join(line.strip() for line in text.split('\n'))
    return text.strip()


def remove_page_artifacts(text: str) -> str:
    """Remove page numbers and headers/footers."""
    # Номера страниц внизу
    text = re.sub(r'\n\s*\d{1,3}\s*\n', '\n', text)
    # Заголовки типа "Глава 1. Начальные геометрические сведения"
    # (оставляем - это полезная информация)
    return text


# ===========================================
# Главная функция
# ===========================================

def clean_ocr_text(text: str, aggressive: bool = True, use_dictionary: bool = True) -> str:
    """
    Apply all OCR cleaning steps.
    
    Args:
        text: Raw OCR text
        aggressive: If True, apply more aggressive fixes
        use_dictionary: If True, use dictionary-based word correction
        
    Returns:
        Cleaned text
    """
    if not text:
        return text
    
    # 1. Переносы (до других исправлений)
    text = fix_hyphenation(text)
    
    # 2. Латиница → Кириллица
    text = fix_latin_to_cyrillic(text)
    
    # 3. Математические символы
    text = fix_math_symbols(text)
    
    # 4. Контекстуальные исправления (паттерны)
    text = apply_contextual_fixes(text)
    
    # 5. Математический контекст (переменные, формулы)
    text = fix_mathematical_context(text)
    
    # 6. Границы предложений
    text = fix_sentence_boundaries(text)
    
    # 7. Нумерация (опционально - может быть агрессивно)
    if aggressive:
        text = fix_numbering_in_context(text)
    
    # 8. Словарная коррекция (опционально - медленнее)
    if use_dictionary and aggressive:
        text = fix_words_by_dictionary(text)
    
    # 9. Пробелы и артефакты
    text = clean_whitespace(text)
    text = remove_page_artifacts(text)
    
    return text


# ===========================================
# Валидация качества OCR
# ===========================================

def calculate_quality_score(text: str) -> dict:
    """
    Calculate OCR quality metrics.
    
    Returns:
        dict with quality metrics and issues found
    """
    issues = []
    
    # 1. Проверка на латиницу в русском контексте
    latin_in_cyrillic = re.findall(r'[а-яА-ЯёЁ]+[a-zA-Z]+[а-яА-ЯёЁ]*|[a-zA-Z]+[а-яА-ЯёЁ]+', text)
    if latin_in_cyrillic:
        issues.append({
            'type': 'mixed_script',
            'count': len(latin_in_cyrillic),
            'examples': latin_in_cyrillic[:5]
        })
    
    # 2. Проверка на нетипичные символы
    unusual = re.findall(r'[@#$%&*{}|<>]', text)
    if unusual:
        issues.append({
            'type': 'unusual_chars',
            'count': len(unusual),
            'chars': list(set(unusual))
        })
    
    # 3. Проверка нумерации
    numbers_in_lists = re.findall(r'\b(\d)\)', text)
    if numbers_in_lists:
        nums = [int(n) for n in numbers_in_lists]
        expected = list(range(nums[0], nums[0] + len(nums)))
        if nums != expected:
            issues.append({
                'type': 'numbering_error',
                'found': nums,
                'expected': expected
            })
    
    # 4. Слишком много цифр внутри слов
    digits_in_words = re.findall(r'[а-яА-Я]+\d+[а-яА-Я]+', text)
    if digits_in_words:
        issues.append({
            'type': 'digits_in_words',
            'count': len(digits_in_words),
            'examples': digits_in_words[:5]
        })
    
    # Общий скор (0-100)
    # Начинаем с 100, вычитаем за каждую проблему
    score = 100
    for issue in issues:
        if issue['type'] == 'mixed_script':
            score -= min(issue['count'] * 5, 30)
        elif issue['type'] == 'unusual_chars':
            score -= min(issue['count'] * 2, 10)
        elif issue['type'] == 'numbering_error':
            score -= 10
        elif issue['type'] == 'digits_in_words':
            score -= min(issue['count'] * 5, 20)
    
    return {
        'score': max(0, score),
        'issues': issues,
        'text_length': len(text),
        'word_count': len(text.split()),
    }


# ===========================================
# CLI
# ===========================================

if __name__ == "__main__":
    import sys
    
    # Примеры проблемных текстов
    test_cases = [
        # Оригинальный проблемный текст
        """4. Найдите смежные углы, если: 1) один из них на 80° боль-
me другого; 2) ux разность равна 40°; 8) один из них в
3 pasa меньше другого; 4) OHH равны.""",

        # Математический контекст
        """Решите уравнение: 2х + 5 = 13. Найдите значение у при х = 4.""",
        
        # Теоремы и определения
        """Tеорема 1.2. Cмежные yглы в cyмме равны 180°.
Дока3ательство. Пусть угoл ABC и угoл CBD - cмежные.""",
        
        # Числа и единицы
        """Угол равен 45 rpanycoв. Найдите смe.ный угол.""",
    ]
    
    for i, test_text in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"ТЕСТ {i}")
        print('='*60)
        
        print("\n📝 Исходный текст:")
        print(test_text)
        
        quality_before = calculate_quality_score(test_text)
        print(f"\n📊 Качество ДО: {quality_before['score']}/100")
        if quality_before['issues']:
            for issue in quality_before['issues']:
                print(f"   ⚠️ {issue['type']}: {issue.get('count', '')} {issue.get('examples', issue.get('chars', ''))[:3]}")
        
        print("\n✨ После очистки:")
        cleaned = clean_ocr_text(test_text)
        print(cleaned)
        
        quality_after = calculate_quality_score(cleaned)
        print(f"\n📊 Качество ПОСЛЕ: {quality_after['score']}/100")
        print(f"📈 Улучшение: +{quality_after['score'] - quality_before['score']}")
    
    print(f"\n{'='*60}")
    print("✅ Тестирование завершено")
