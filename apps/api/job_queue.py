"""
Redis Queue (RQ) setup and job enqueuing.
"""
from redis import Redis
from rq import Queue

from config import get_settings

settings = get_settings()

# Redis connection
redis_conn = Redis.from_url(settings.redis_url)

# Default queue for query processing
query_queue = Queue("queries", connection=redis_conn)


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
