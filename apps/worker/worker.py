"""
RQ Worker entry point.
"""
import sys
from redis import Redis
from rq import Worker, Queue

from config import get_settings

settings = get_settings()


def main():
    """Start the RQ worker."""
    print("🚀 TutorBot Worker starting...")
    print(f"📮 Redis: {settings.redis_url}")
    print(f"📦 Database: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    
    # Connect to Redis
    redis_conn = Redis.from_url(settings.redis_url)
    
    # Listen on 'queries' (ответы) and 'ingestion' (обработка PDF)
    queues = [
        Queue("ingestion", connection=redis_conn),
        Queue("queries", connection=redis_conn),
    ]
    
    print(f"👂 Listening on queues: {[q.name for q in queues]}")
    
    # Start worker
    worker = Worker(queues, connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
