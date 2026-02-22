#!/usr/bin/env python3
"""
Formula Processor for OCR Text

Улучшает распознавание формул через:
1. Пост-обработку известных артефактов OCR
2. (Опционально) GPT-4 Vision для сложных формул
"""

import re
import os
from typing import Optional, Tuple
import base64

# Try to import OpenAI
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


# ===========================================
# 1. Пост-обработка OCR артефактов
# ===========================================

# Замены символов (OCR артефакт → правильный символ)
SYMBOL_REPLACEMENTS = [
    # Физика/математика - Q (теплота, заряд)
    (r'@(\d)', r'Q\1'),          # @1 → Q1, @2 → Q2
    (r'@_', r'Q_'),              # @_ → Q_
    (r'@,', r'Q,'),              # @, → Q,
    (r'@\.', r'Q.'),             # @. → Q.
    (r'@\)', r'Q)'),             # @) → Q)
    (r'\(@', r'(Q'),             # (@ → (Q
    (r'@\s*=', r'Q ='),          # @ = → Q =
    (r'=\s*@', r'= Q'),          # = @ → = Q
    (r'\b@\b', 'Q'),             # @ → Q (отдельно стоящий)
    (r'@', 'Q'),                 # Любой оставшийся @ → Q
    
    # Кубические метры/сантиметры
    (r'м\?', 'м³'),              # м? → м³
    (r'м\s*\?', 'м³'),           # м ? → м³
    (r'm\?', 'm³'),              # m? → m³
    (r'm°', 'm³'),               # m° → m³
    (r'см\?', 'см³'),            # см? → см³
    (r'см°', 'см³'),             # см° → см³
    (r'м°', 'м³'),               # м° → м³
    (r'дм\?', 'дм³'),            # дм? → дм³
    (r'кг/м\?', 'кг/м³'),        # кг/м? → кг/м³
    
    # Квадратные метры
    (r's°', 's²'),               # s° → s²
    (r'с°', 'с²'),               # с° → с²
    (r'м/с\?', 'м/с²'),          # м/с? → м/с²
    
    # Дельта
    (r'\bAt\b', 'Δt'),           # At → Δt
    (r'\bAT\b', 'ΔT'),           # AT → ΔT
    (r'A[Tt]emperature', 'Δtemperature'),
    
    # Греческие буквы
    (r'\bр\b(?=\s*=)', 'ρ'),     # р = → ρ = (плотность)
    (r'\bl\b(?=\s*=)', 'λ'),     # l = → λ = (длина волны)
    (r'\bw\b(?=\s*=)', 'ω'),     # w = → ω = (угловая скорость)
    
    # Кириллица ↔ Латиница (частые ошибки)
    (r'\bkak\b', 'как'),
    (r'\bHe\b', 'не'),           # He → не (осторожно: гелий He)
    (r'\beco\b', 'его'),
    (r'\beTo\b', 'это'),
    (r'\bHO\b', 'но'),
    (r'\bOH\b', 'он'),
    
    # Единицы измерения
    (r'Дж/\(кг\s*[·\*]\s*°C\)', 'Дж/(кг·°C)'),
    (r'кг/м\?', 'кг/м³'),
    (r'м/с\?', 'м/с²'),
    
    # Степени и индексы
    (r't,\s*—\s*t,', 't₂ − t₁'),
    (r'(\d)\s*°\s*C', r'\1°C'),  # Убрать пробелы в градусах
]

# Паттерны формул для детекции
FORMULA_PATTERNS = [
    r'[QFEmvat]\s*=',              # Q = , F = , E = ...
    r'\d+\s*[·\*×]\s*\d+',         # умножение
    r'\d+\s*/\s*\d+',              # деление
    r'[α-ωΑ-Ω]',                   # греческие буквы
    r'\b(sin|cos|tan|log|ln)\b',  # функции
    r'[²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]',     # верхние/нижние индексы
]


def has_formulas(text: str) -> bool:
    """Проверяет, содержит ли текст формулы."""
    for pattern in FORMULA_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def post_process_ocr(text: str) -> str:
    """
    Применяет пост-обработку к OCR тексту.
    Исправляет известные артефакты Tesseract.
    """
    if not text:
        return text
    
    result = text
    
    for pattern, replacement in SYMBOL_REPLACEMENTS:
        result = re.sub(pattern, replacement, result)
    
    return result


def calculate_formula_confidence(original: str, processed: str) -> int:
    """
    Оценивает уверенность в распознавании формул (0-100).
    Низкий скор = нужна ревизия GPT-4V.
    """
    if not original:
        return 100
    
    # Считаем количество подозрительных паттернов
    suspicious_patterns = [
        r'@',           # @ вместо Q
        r'm\?',         # m? вместо m³
        r't,\s*—\s*t,', # индексы не распознаны
        r'[A-Za-z]{10,}',  # очень длинные "слова" (мусор)
        r'[\?\*\#]{2,}',   # множественные спецсимволы
    ]
    
    suspicion_count = 0
    for pattern in suspicious_patterns:
        matches = re.findall(pattern, original)
        suspicion_count += len(matches)
    
    # Базовая уверенность 100, уменьшаем за каждую проблему
    confidence = max(0, 100 - suspicion_count * 10)
    
    return confidence


# ===========================================
# 2. GPT-4 Vision для сложных формул
# ===========================================

FORMULA_EXTRACTION_PROMPT = """Ты — эксперт по распознаванию математических и физических формул.

Проанализируй изображение страницы учебника и извлеки ВСЕ формулы в формате:

1. Для каждой формулы укажи:
   - Исходная формула (как написано)
   - LaTeX версия
   - Текстовое описание (что означает)

2. Обрати особое внимание на:
   - Греческие буквы (ρ, λ, Δ, α, β, ω и т.д.)
   - Верхние и нижние индексы
   - Дроби и степени
   - Единицы измерения

Формат ответа — JSON:
{
  "formulas": [
    {
      "original": "Q = cm(t₂ - t₁)",
      "latex": "Q = cm(t_2 - t_1)",
      "description": "Количество теплоты"
    }
  ],
  "page_has_formulas": true,
  "confidence": 95
}

Если на странице нет формул, верни:
{"formulas": [], "page_has_formulas": false, "confidence": 100}
"""


def extract_formulas_with_vision(
    image_path: str,
    api_key: Optional[str] = None
) -> dict:
    """
    Извлекает формулы из изображения с помощью GPT-4 Vision.
    
    Args:
        image_path: Путь к изображению страницы
        api_key: OpenAI API ключ (или из env OPENAI_API_KEY)
    
    Returns:
        dict с формулами и метаданными
    """
    if not HAS_OPENAI:
        return {"error": "OpenAI not installed", "formulas": []}
    
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "No API key", "formulas": []}
    
    try:
        # Читаем и кодируем изображение
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o",  # или gpt-4-vision-preview
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": FORMULA_EXTRACTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        import json
        result = json.loads(response.choices[0].message.content)
        return result
        
    except Exception as e:
        return {"error": str(e), "formulas": []}


def enhance_ocr_with_formulas(
    ocr_text: str,
    image_path: Optional[str] = None,
    use_vision: bool = False,
    api_key: Optional[str] = None
) -> Tuple[str, dict]:
    """
    Полный пайплайн улучшения OCR текста.
    
    1. Пост-обработка известных артефактов
    2. (Опционально) GPT-4V для формул
    
    Returns:
        (улучшенный_текст, метаданные)
    """
    # Шаг 1: Пост-обработка
    processed = post_process_ocr(ocr_text)
    confidence = calculate_formula_confidence(ocr_text, processed)
    
    metadata = {
        "original_length": len(ocr_text or ""),
        "processed_length": len(processed),
        "post_processing_applied": True,
        "formula_confidence": confidence,
        "vision_used": False,
        "formulas_extracted": []
    }
    
    # Шаг 2: GPT-4V для сложных страниц (если запрошено и confidence низкий)
    if use_vision and image_path and confidence < 70:
        vision_result = extract_formulas_with_vision(image_path, api_key)
        
        if "error" not in vision_result:
            metadata["vision_used"] = True
            metadata["formulas_extracted"] = vision_result.get("formulas", [])
            
            # Можно заменить формулы в тексте на LaTeX версии
            # (опционально, для будущего рендеринга)
    
    return processed, metadata


# ===========================================
# CLI для тестирования
# ===========================================

if __name__ == "__main__":
    # Тестовые примеры
    test_texts = [
        "© ЗАДАЧА 1. Найдите @1 если @2 = 100 Дж",
        "Дано: m = 400 г, V = 2 л, t = 20°C",
        "Формула: @ = cm(t, — t,)",
        "Плотность р = 1000 кг/м?",
        "Это He задача, а просто текст kak пример",
    ]
    
    print("🔧 Тестирование пост-обработки OCR формул\n")
    print("=" * 60)
    
    for text in test_texts:
        processed = post_process_ocr(text)
        confidence = calculate_formula_confidence(text, processed)
        
        print(f"\n📝 Оригинал:    {text}")
        print(f"✅ Обработано:  {processed}")
        print(f"🎯 Confidence:  {confidence}%")
        
        if text != processed:
            print("   → Изменения применены!")
