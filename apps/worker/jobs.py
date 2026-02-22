"""
Job handlers for query processing.
"""
import time
from datetime import datetime

from database import SessionLocal
from models import Query, Response
from notifications import send_telegram_notification_sync, build_query_ready_message
from retrieval import search_problems, SearchResult
from llm import get_section_theory, generate_solution_explanation


# Minimum FTS score to consider a match valid (avoid weak/wrong references)
CONFIDENCE_THRESHOLD = 0.15

# Enable LLM explanations (can be disabled for faster testing)
ENABLE_LLM_EXPLANATIONS = True


def format_response(
    query_text: str,
    result: SearchResult,
    processing_time_ms: int,
    llm_explanation: str = None
) -> str:
    """Format search result as markdown response."""
    
    # Answer: for multi-part use part_answer when available
    if result.has_parts and result.part_answer:
        part_label = f" (вариант {result.requested_part})" if result.requested_part else ""
        answer_section = f"**{result.part_answer}**{part_label}"
    elif result.answer_text:
        answer_section = f"**{result.answer_text}**"
    else:
        answer_section = "_Ответ не найден_"
    
    # Solution/explanation section
    if llm_explanation:
        solution_section = f"""### 💡 Объяснение решения

{llm_explanation}"""
    elif result.solution_text:
        solution_section = f"""### ✏️ Решение из базы

{result.solution_text}"""
    else:
        solution_section = "_Решение не найдено в базе_"
    
    content = f"""## Ответ на запрос

**Ваш запрос:** {query_text[:200]}

---

### 📚 Источник

**Книга:** {result.book_title}  
**Задача:** {result.number or 'N/A'}  
**Страница:** {result.page_ref or 'N/A'}

---

### ✅ Ответ

{answer_section}

---

{solution_section}

---

*Источник: {result.book_title}, {result.page_ref}*  
*Обработано за {processing_time_ms} мс*
"""
    return content


def format_no_results_response(query_text: str, processing_time_ms: int) -> str:
    """Format response when no matching problem found."""
    return f"""## Ответ на запрос

**Ваш запрос:** {query_text[:200]}

---

### ❌ Решение не найдено

К сожалению, мы не нашли похожую задачу в нашей базе данных.

**Возможные причины:**
- Задача сформулирована иначе в учебнике
- Такой задачи нет в загруженных решебниках
- Попробуйте переформулировать запрос

**Совет:** Укажите больше деталей из условия задачи или номер упражнения из учебника.

---

*Обработано за {processing_time_ms} мс*
"""


def process_query(query_id: int) -> dict:
    """
    Process a homework query.
    
    Pipeline:
    1. Mark query as processing
    2. Search for matching problems (FTS)
    3. If found with good confidence - format response
    4. If multiple candidates - mark as needs_choice
    5. If not found - return "not found" response
    6. Send push notification
    
    Args:
        query_id: The ID of the query to process
        
    Returns:
        dict with processing result
    """
    start_time = time.time()
    query = None
    
    db = SessionLocal()
    try:
        # Get query
        query = db.query(Query).filter(Query.id == query_id).first()
        
        if not query:
            print(f"❌ Query {query_id} not found")
            return {"status": "error", "message": "Query not found"}
        
        input_text = query.input_text or ""
        input_preview = input_text[:50] if input_text else "фото"
        print(f"🔄 Processing query {query_id}: {input_preview}...")
        
        # Mark as processing
        query.status = "processing"
        query.extracted_text = input_text  # TODO: OCR for photos
        db.commit()
        
        # ===========================================
        # Search for matching problems
        # ===========================================
        search_results = search_problems(input_text, limit=5)
        llm_explanation = None  # Will be set if LLM generates explanation
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        best = search_results[0] if search_results else None
        if search_results and search_results[0].score >= CONFIDENCE_THRESHOLD:
            # Found a good match — always show source (book, task, page); correctness depends on search/OCR
            best = search_results[0]
            print(f"   ✅ Found match: {best.book_title} #{best.number} (score={best.score:.3f})")
            
            # Generate LLM explanation using section theory
            llm_explanation = None
            effective_answer = (best.part_answer if (best.has_parts and best.part_answer) else best.answer_text)
            if ENABLE_LLM_EXPLANATIONS:
                try:
                    print(f"   📖 Fetching section theory for {best.section}...")
                    section_theory = get_section_theory(db, best.book_id, best.section)
                    theory_len = len(section_theory) if section_theory else 0
                    print(f"   📖 Got {theory_len} chars of theory")
                    
                    if section_theory or effective_answer:
                        llm_explanation = generate_solution_explanation(
                            problem_text=best.problem_text,
                            answer_text=effective_answer,
                            section_theory=section_theory,
                            book_title=best.book_title,
                            section=best.section or "",
                        )
                except Exception as e:
                    print(f"   ⚠️ LLM explanation failed: {e}")
            
            content = format_response(input_text, best, processing_time_ms, llm_explanation)
            citations = [{
                "book_id": best.book_id,
                "problem_id": best.problem_id,
                "page_ref": best.page_ref,
                "score": best.score,
            }]
            confidence_score = int(best.score * 100)
            model_used = "fts+llm" if llm_explanation else "fts"
            query.status = "done"
            
        elif search_results:
            # Low confidence — still show best match and source (reference may be wrong; fix via search/OCR)
            best = search_results[0]
            print(f"   ⚠️ Low confidence match: {best.book_title} #{best.number} (score={best.score:.3f})")
            
            # Still try LLM for low confidence results
            llm_explanation = None
            effective_answer_low = (best.part_answer if (best.has_parts and best.part_answer) else best.answer_text)
            if ENABLE_LLM_EXPLANATIONS:
                try:
                    section_theory = get_section_theory(db, best.book_id, best.section)
                    if section_theory or effective_answer_low:
                        llm_explanation = generate_solution_explanation(
                            problem_text=best.problem_text,
                            answer_text=effective_answer_low,
                            section_theory=section_theory,
                            book_title=best.book_title,
                            section=best.section or "",
                        )
                except Exception as e:
                    print(f"   ⚠️ LLM explanation failed: {e}")
            
            content = format_response(input_text, best, processing_time_ms, llm_explanation)
            citations = [{
                "book_id": best.book_id,
                "problem_id": best.problem_id,
                "page_ref": best.page_ref,
                "score": best.score,
            }]
            confidence_score = int(best.score * 100)
            model_used = "fts+llm" if llm_explanation else "fts"
            query.status = "done"
            
        else:
            # No results found
            print(f"   ❌ No matching problems found")
            
            content = format_no_results_response(input_text, processing_time_ms)
            citations = []
            confidence_score = 0
            model_used = "none"
            query.status = "done"  # Still done, just no answer
        
        # Create response
        response = Response(
            query_id=query.id,
            content_markdown=content,
            citations=citations,
            model_used=model_used,
            confidence_score=confidence_score,
        )
        db.add(response)
        
        # Finalize
        query.processing_time_ms = processing_time_ms
        query.ocr_confidence = 100  # TODO: real OCR confidence
        
        db.commit()
        
        print(f"✅ Query {query_id} processed in {processing_time_ms}ms")
        
        # ===========================================
        # Send push notification with answer
        # ===========================================
        try:
            # Get user's Telegram ID
            from sqlalchemy import text
            result = db.execute(
                text("SELECT tg_uid FROM users WHERE id = :user_id"),
                {"user_id": query.user_id}
            ).fetchone()
            
            if result and result[0]:
                tg_uid = result[0]
                
                # Build answer content for notification
                if search_results:
                    best = search_results[0]
                    from notifications import build_short_answer
                    answer_content = build_short_answer(
                        problem_text=best.problem_text,
                        solution_text=best.solution_text,
                        answer_text=best.answer_text,
                        problem_type=best.problem_type,
                        llm_explanation=llm_explanation,
                        part_answer=best.part_answer,
                        requested_part=best.requested_part,
                        has_parts=best.has_parts,
                    )
                    message = build_query_ready_message(
                        query_id=query.id,
                        preview=input_preview,
                        answer_content=answer_content,
                        book_title=best.book_title,
                        problem_number=best.number,
                        confidence=confidence_score
                    )
                else:
                    message = build_query_ready_message(
                        query_id=query.id,
                        preview=input_preview,
                        answer_content="К сожалению, похожая задача не найдена в базе.",
                        confidence=0
                    )
                
                send_telegram_notification_sync(tg_uid, message)
        except Exception as e:
            print(f"⚠️ Failed to send notification for query {query_id}: {e}")
        
        return {
            "status": "success",
            "query_id": query_id,
            "processing_time_ms": processing_time_ms
        }
        
    except Exception as e:
        print(f"❌ Error processing query {query_id}: {e}")
        
        # Mark as failed if query was loaded
        if query is not None:
            query.status = "failed"
            query.error_message = str(e)
            db.commit()
        
        return {"status": "error", "message": str(e)}
        
    finally:
        db.close()
