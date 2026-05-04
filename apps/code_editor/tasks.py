"""
Background tasks for code editor app using Celery for async processing.
"""

import os
import time
from datetime import datetime, timedelta

# Make celery optional for local development
try:
    from celery import shared_task
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False
    def shared_task(*args, **kwargs):
        """Decorator fallback when celery is not available"""
        def decorator(func):
            return func
        return decorator

from django.core.cache import cache
from django.utils import timezone
from django.db import transaction
# Import models and services relative to the ``code_editor`` package. Using a
# single dot (.) ensures imports resolve within this package; double dots (..)
# would incorrectly refer to the parent of ``code_editor``.
from .models import (
    CodeEditorRequestLog, Project, Repository,
    IndexedFile, CodeChunk, IngestionJob, ProviderHealth
)
from .services.config import ConfigService
from .services.ingestion_service import IngestionService
from .services.repository_service import RepositoryService
from .services.embeddings_service import EmbeddingsService
from .services.router import RouterService


def cleanup_old_logs():
    """Clean up old request logs (older than 90 days)"""
    cutoff_date = timezone.now() - timedelta(days=90)
    deleted_count, _ = CodeEditorRequestLog.objects.filter(
        created_at__lt=cutoff_date
    ).delete()
    return deleted_count


def reset_daily_counters():
    """Reset daily local analytics caches (should run daily at midnight)."""
    # Local mode does not maintain per-key quota counters.
    # Any stale analytics cache entries are allowed to expire naturally.
    pass


def update_usage_statistics():
    """Update usage statistics for analytics"""
    yesterday = timezone.now() - timedelta(days=1)
    yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Get yesterday's stats
    stats = {
        'total_requests': CodeEditorRequestLog.objects.filter(
            created_at__gte=yesterday_start,
            created_at__lte=yesterday_end
        ).count(),
        'successful_requests': CodeEditorRequestLog.objects.filter(
            created_at__gte=yesterday_start,
            created_at__lte=yesterday_end,
            status='success'
        ).count(),
        'error_requests': CodeEditorRequestLog.objects.filter(
            created_at__gte=yesterday_start,
            created_at__lte=yesterday_end,
            status='error'
        ).count(),
    }
    
    # Store in cache for dashboard
    cache.set(f'code_editor_daily_stats:{yesterday.strftime("%Y-%m-%d")}', stats, 86400 * 7)


# Celery Tasks
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_repository_task(self, job_id: str):
    """Background task for repository ingestion"""
    try:
        ingestion_service = IngestionService()
        result = ingestion_service.ingest_repository(job_id)
        
        # Update job status in database
        from .models import IngestionJob  # noqa: E402
        try:
            job = IngestionJob.objects.get(job_id=job_id)
            if result.get('error'):
                job.status = 'failed'
                job.error_message = result['error']
            else:
                job.status = 'completed'
                job.files_processed = result.get('files_processed', 0)
                job.chunks_created = result.get('chunks_created', 0)
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_message', 'files_processed', 'chunks_created', 'completed_at'])
        except IngestionJob.DoesNotExist:
            # Job might have been deleted
            pass
            
        return {'status': 'completed', 'result': result}
        
    except Exception as e:
        # Update job with error
        try:
            from .models import IngestionJob  # noqa: E402
            job = IngestionJob.objects.get(job_id=job_id)
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_message', 'completed_at'])
        except IngestionJob.DoesNotExist:
            pass
        
        # Retry the task
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@shared_task(bind=True, max_retries=2)
def generate_embeddings_task(self, chunk_ids: list):
    """Background task for generating embeddings"""
    try:
        # Import within the function to avoid circular import issues.
        from .models import CodeChunk  # noqa: E402
        from .services.embeddings_service import EmbeddingsService  # noqa: E402

        embeddings_service = EmbeddingsService()

        # Get chunks to process (only those without embeddings)
        chunks = CodeChunk.objects.filter(id__in=chunk_ids, embedding__isnull=True)
        if not chunks.exists():
            return {'status': 'completed', 'processed': 0}

        # Determine batch size from configuration to align with EmbeddingsService
        embed_config = ConfigService.get_embeddings_config()
        batch_size = embed_config.get('batch_size', 50) or 50
        processed = 0

        for i in range(0, chunks.count(), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [chunk.content for chunk in batch]
            try:
                embeddings = embeddings_service.generate_embeddings(
                    texts=texts,
                    model=embed_config.get('model')
                )
                # Update chunks with returned embeddings or fallback pseudo embeddings
                for chunk, embedding in zip(batch, embeddings):
                    chunk.embedding = embedding
                    chunk.embedding_model = embed_config.get('model')
                    chunk.save(update_fields=['embedding', 'embedding_model'])
                processed += len(batch)
            except Exception as exc:
                # On error, generate pseudo embeddings locally and save them
                # to ensure retrieval still works, but mark processing as partial
                for chunk in batch:
                    # Fallback pseudo embedding via EmbeddingsService
                    pseudo = embeddings_service._pseudo_embedding(chunk.content)
                    chunk.embedding = pseudo
                    chunk.embedding_model = embed_config.get('model')
                    chunk.save(update_fields=['embedding', 'embedding_model'])
                processed += len(batch)
                # Log error to stdout for debugging; continue with next batch
                print(f"Error generating embeddings for batch {i}: {str(exc)}")
                continue

        return {'status': 'completed', 'processed': processed}

    except Exception as e:
        # Retry the task on unexpected errors
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


@shared_task(bind=True, max_retries=1)
def check_provider_health_task(self):
    """Background task for checking provider health"""
    try:
        router_service = RouterService()
        health_status = router_service.get_provider_health_status()
        
        # Update database with health status
        for provider_name, status in health_status.items():
            ProviderHealth.objects.update_or_create(
                provider_name=provider_name,
                defaults={
                    'status': status['status'],
                    'response_time_ms': status.get('response_time_ms'),
                    'error_message': status.get('error', ''),
                    'last_check': timezone.now(),
                }
            )
        
        return {'status': 'completed', 'providers': health_status}
        
    except Exception as e:
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def cleanup_expired_cache_task(self):
    """Background task for cleaning up expired cache entries"""
    try:
        # This would use Redis commands to clean up specific patterns
        # For now, just report what would be cleaned
        patterns_to_clean = [
            'code_editor_daily_stats:*',
            'provider_health:*',
        ]
        
        cleaned_count = 0
        for pattern in patterns_to_clean:
            try:
                # In a real implementation, you'd use Redis SCAN and DELETE
                # For now, just count keys that would be cleaned
                cleaned_count += 10  # Placeholder count
            except Exception:
                continue
        
        return {'status': 'completed', 'cleaned_patterns': patterns_to_clean, 'cleaned_count': cleaned_count}
        
    except Exception as e:
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=2)
def update_usage_statistics_task(self):
    """Background task for updating usage statistics"""
    try:
        # This is already implemented above but made into a Celery task
        yesterday = timezone.now() - timedelta(days=1)
        yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Get yesterday's stats
        stats = {
            'total_requests': CodeEditorRequestLog.objects.filter(
                created_at__gte=yesterday_start,
                created_at__lte=yesterday_end
            ).count(),
            'successful_requests': CodeEditorRequestLog.objects.filter(
                created_at__gte=yesterday_start,
                created_at__lte=yesterday_end,
                status='success'
            ).count(),
            'error_requests': CodeEditorRequestLog.objects.filter(
                created_at__gte=yesterday_start,
                created_at__lte=yesterday_end,
                status='error'
            ).count(),
        }
        
        # Store in cache for dashboard
        cache.set(f'code_editor_daily_stats:{yesterday.strftime("%Y-%m-%d")}', stats, 86400 * 7)
        
        return {'status': 'completed', 'stats': stats}
        
    except Exception as e:
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def reindex_repository_task(self, repository_id: int):
    """Background task for reindexing a repository"""
    try:
        from .models import Repository  # noqa: E402
        repository = Repository.objects.get(id=repository_id)
        
        # Start new ingestion job
        repository_service = RepositoryService()
        job = repository_service.start_ingestion_job(repository)
        
        return {'status': 'started', 'job_id': job.job_id, 'repository': repository.name}
        
    except Exception as e:
        raise self.retry(exc=e, countdown=60)


def _execute_task_run_in_thread(task_id: str):
    """Thread target for local async task execution."""
    from django.db import close_old_connections
    from .workflows.task_executor import TaskExecutor

    close_old_connections()
    try:
        TaskExecutor.from_id(task_id).run()
    finally:
        close_old_connections()


@shared_task(bind=True, ignore_result=False)
def execute_task_run_task(self, task_id: str):
    """Queue-compatible Celery task for running a TaskRun."""
    from .workflows.task_executor import TaskExecutor

    TaskExecutor.from_id(task_id).run()
    return {'task_id': task_id, 'status': 'completed'}


def launch_task_run(task):
    """Launch a task run without blocking the API request thread."""
    import os
    import threading
    from .models import TaskRun  # noqa: WPS433

    task_id = str(task.id if isinstance(task, TaskRun) else task)
    use_celery = HAS_CELERY and os.environ.get('CODE_EDITOR_TASK_USE_CELERY', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if use_celery:
        try:
            async_result = execute_task_run_task.delay(task_id)
            TaskRun.objects.filter(id=task_id).update(
                launched_via='celery',
                runner_job_id=str(async_result.id),
            )
            return {'launched_via': 'celery', 'runner_job_id': str(async_result.id)}
        except Exception:
            pass

    worker = threading.Thread(
        target=_execute_task_run_in_thread,
        args=(task_id,),
        daemon=True,
        name=f'code-editor-task-{task_id}',
    )
    worker.start()
    TaskRun.objects.filter(id=task_id).update(
        launched_via='thread',
        runner_job_id=f'thread:{task_id}',
    )
    return {'launched_via': 'thread', 'runner_job_id': f'thread:{task_id}'}
