"""
Redis Queue (RQ) setup and job enqueuing.
"""
from redis import Redis
from rq import Queue

from config import get_settings

settings = get_settings()

# Redis connection
redis_conn = Redis.from_url(settings.redis_url)

# Queues
query_queue = Queue("queries", connection=redis_conn)
ingestion_queue = Queue("ingestion", connection=redis_conn)


def enqueue_query_job(query_id: int) -> str:
    """
    Enqueue a query processing job.
    
    Args:
        query_id: The ID of the query to process
        
    Returns:
        The job ID
    """
    job = query_queue.enqueue(
        "jobs.process_query",  # Worker will import this
        query_id,
        job_timeout="5m",
        result_ttl=3600,  # Keep result for 1 hour
    )
    return job.id


def enqueue_ingestion(pdf_source_id: int) -> str:
    """
    Enqueue PDF ingestion job (OCR → normalization → DB).
    Worker runs ingestion.process_pdf_source(pdf_source_id).
    """
    job = ingestion_queue.enqueue(
        "ingestion.process_pdf_source",
        pdf_source_id,
        job_timeout="30m",
        result_ttl=3600,
    )
    return job.id


def enqueue_llm_normalize(pdf_source_id: int) -> str:
    """
    Enqueue only LLM normalization: read normalized file → OpenAI correct → write → re-import.
    Worker runs ingestion.run_llm_normalize_only(pdf_source_id).
    """
    job = ingestion_queue.enqueue(
        "ingestion.run_llm_normalize_only",
        pdf_source_id,
        job_timeout="15m",
        result_ttl=3600,
    )
    redis_conn.setex(f"llm_norm_job_id:{pdf_source_id}", 3600, job.id)
    return job.id


def enqueue_import_from_normalized(pdf_source_id: int) -> str:
    """
    Enqueue distribution from normalized .md into DB via LLM (see docs/LLM_DISTRIBUTION_DESIGN.md).
    Worker runs ingestion.import_from_normalized_file_llm(pdf_source_id). БД перезаписывается.
    """
    job = ingestion_queue.enqueue(
        "ingestion.import_from_normalized_file_llm",
        pdf_source_id,
        job_timeout="30m",
        result_ttl=3600,
    )
    return job.id
