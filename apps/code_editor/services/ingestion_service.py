import os
import hashlib
import re
from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from ..models import Repository, IndexedFile, CodeChunk, IngestionJob
from ..services.embeddings_service import EmbeddingsService
from ..services.config import ConfigService
from ..utils import extract_code_language

# Expose RepositoryService at module level for easier patching in tests.
# Importing here avoids circular import issues because repository_service does not
# import IngestionService. This allows tests to use
# `patch('code_editor.services.ingestion_service.RepositoryService.get_repository_files')`.
from ..services.repository_service import RepositoryService  # noqa: E402,F401


class IngestionService:
    """Service for ingesting and processing code repositories"""
    
    def __init__(self):
        self.embeddings_service = EmbeddingsService()
        self.chunk_size = 1000  # Maximum chunk size in characters
        self.chunk_overlap = 200  # Overlap between chunks
    
    def ingest_repository(self, job_id: str) -> Dict[str, Any]:
        """Main ingestion method"""
        try:
            job = IngestionJob.objects.get(job_id=job_id)
            
            if job.status != 'pending':
                return {'error': 'Job is not in pending state'}
            
            # Update job status
            job.status = 'running'
            job.started_at = timezone.now()
            job.save(update_fields=['status', 'started_at'])
            
            # Get repository
            repository = job.repository
            
            # Update repository status
            repository.indexing_status = 'indexing'
            repository.save(update_fields=['indexing_status'])
            
            # Get files from repository (will perform remote sync if necessary)
            from ..services.repository_service import RepositoryService
            files = RepositoryService.get_repository_files(repository)

            # Determine paths of files that will be indexed; used for incremental deletion
            scanned_paths = {f.get('path') for f in files if f.get('path')}

            if not files:
                # No files discovered: mark indexing as failed
                job.status = 'failed'
                job.error_message = 'No files found in repository'
                job.completed_at = timezone.now()
                job.save(update_fields=['status', 'error_message', 'completed_at'])
                repository.indexing_status = 'failed'
                repository.indexing_error = 'No files found'
                repository.save(update_fields=['indexing_status', 'indexing_error'])
                return {'error': 'No files found in repository'}

            # Delete stale indexed files (files removed from repo) before processing
            try:
                existing_qs = IndexedFile.objects.filter(repository=repository)
                for indexed in existing_qs:
                    if indexed.file_path not in scanned_paths:
                        # Delete associated chunks
                        CodeChunk.objects.filter(indexed_file=indexed).delete()
                        indexed.delete()
            except Exception:
                pass
            
            # Process files
            total_files = len(files)
            processed_files = 0
            total_chunks = 0
            
            for i, file_data in enumerate(files):
                try:
                    # Update job progress
                    progress = int((i / total_files) * 100)
                    job.progress = progress
                    job.files_processed = i + 1
                    job.save(update_fields=['progress', 'files_processed'])
                    
                    # Process file
                    chunks_created = self._process_file(repository, file_data)
                    total_chunks += chunks_created
                    processed_files += 1
                    
                except Exception as e:
                    # Log error but continue with other files
                    print(f"Error processing file {file_data['path']}: {str(e)}")
                    continue
            
            # Update repository with final stats
            repository.file_count = processed_files
            repository.indexed_chunk_count = total_chunks
            repository.last_indexed_at = timezone.now()
            repository.indexing_status = 'completed'
            repository.indexing_error = ''
            repository.save(update_fields=['file_count', 'indexed_chunk_count', 'last_indexed_at', 'indexing_status', 'indexing_error'])
            
            # Complete job
            job.status = 'completed'
            job.progress = 100
            job.files_processed = processed_files
            job.chunks_created = total_chunks
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'progress', 'files_processed', 'chunks_created', 'completed_at'])
            
            # Invalidate caches related to repository statistics now that ingestion
            # has completed.  Errors during invalidation are ignored.
            try:
                from ..services.cache_helper import CacheHelper  # type: ignore
                CacheHelper.invalidate_repository_stats_cache()
            except Exception:
                pass
            return {
                'status': 'completed',
                'files_processed': processed_files,
                'chunks_created': total_chunks
            }
            # Invalidate caches related to repository stats
            try:
                from ..services.cache_helper import CacheHelper  # type: ignore
                CacheHelper.invalidate_repository_stats_cache()
            except Exception:
                pass
            
        except IngestionJob.DoesNotExist:
            return {'error': 'Job not found'}
        except Exception as e:
            # Update job with error
            try:
                job = IngestionJob.objects.get(job_id=job_id)
                job.status = 'failed'
                job.error_message = str(e)
                job.completed_at = timezone.now()
                job.save(update_fields=['status', 'error_message', 'completed_at'])
                
                # Update repository status
                repository = job.repository
                repository.indexing_status = 'failed'
                repository.indexing_error = str(e)
                repository.save(update_fields=['indexing_status', 'indexing_error'])
                
            except Exception:
                pass  # Job might not exist
            
            return {'error': str(e)}
    
    def _process_file(self, repository: Repository, file_data: Dict[str, Any]) -> int:
        """Process a single file and create chunks"""
        file_path = file_data['path']
        content = file_data['content']
        
        # Skip very large files for now
        if len(content) > 100000:  # 100KB limit
            print(f"Skipping large file: {file_path} ({len(content)} chars)")
            return 0
        
        # Calculate file hash
        file_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        # Check if an IndexedFile entry already exists
        indexed_file, created = IndexedFile.objects.get_or_create(
            repository=repository,
            file_path=file_path,
            defaults={
                'file_hash': file_hash,
                'file_size': file_data['size'],
                'language': extract_code_language(file_path, content),
                'last_modified': file_data['last_modified']
            }
        )

        # If an existing record was found (not created), determine if the file has changed
        if not created:
            # If the content hash matches, skip re-chunking
            if indexed_file.file_hash == file_hash:
                return CodeChunk.objects.filter(indexed_file=indexed_file).count()
            # Otherwise update the metadata to reflect the new state
            indexed_file.file_hash = file_hash
            indexed_file.file_size = file_data['size']
            indexed_file.language = extract_code_language(file_path, content)
            indexed_file.last_modified = file_data['last_modified']
            indexed_file.save(update_fields=['file_hash', 'file_size', 'language', 'last_modified'])

            # Delete existing chunks for this file before re-chunking
            CodeChunk.objects.filter(indexed_file=indexed_file).delete()
        
        # Chunk the content
        chunks = self._chunk_content(content, file_path)
        # Apply a limit on the number of chunks per file if configured.  A value
        # of 0 or unset means unlimited.  This prevents runaway chunk
        # generation on extremely large files.  Environment variables are
        # strings so default to 0 when parsing fails.
        try:
            max_chunks = int(os.getenv('CODE_EDITOR_MAX_CHUNKS_PER_FILE', '0') or '0')
        except Exception:
            max_chunks = 0
        if max_chunks > 0 and len(chunks) > max_chunks:
            chunks = chunks[:max_chunks]
        
        # Create chunk records and collect their IDs for deferred embedding generation
        chunk_ids: List[int] = []
        for chunk_data in chunks:
            chunk = CodeChunk.objects.create(
                indexed_file=indexed_file,
                chunk_index=chunk_data['index'],
                content=chunk_data['content'],
                start_line=chunk_data['start_line'],
                end_line=chunk_data['end_line'],
                chunk_type=chunk_data['type'],
                token_count=self._estimate_tokens(chunk_data['content']),
                symbol_name=chunk_data.get('symbol_name'),
            )
            chunk_ids.append(chunk.id)

        # Defer embedding generation to background task if enabled
        try:
            from ..tasks import generate_embeddings_task
            # Kick off asynchronous embedding generation. If the Celery worker is not
            # configured, this call will be a no-op when using eager mode for tests.
            if chunk_ids:
                generate_embeddings_task.delay(chunk_ids)
        except Exception:
            # In environments without Celery, embedding generation must be handled
            # synchronously by calling EmbeddingsService directly or deferred elsewhere.
            pass

        return len(chunk_ids)
    
    def _chunk_content(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Split content into meaningful chunks.

        This method uses simple language-aware heuristics to break large files into
        smaller, semantically meaningful chunks. For Python files, we split on
        function and class definitions as well as docstrings and comments. For
        brace-based languages (e.g., JavaScript, TypeScript, Java, Go, C/C++, Rust),
        we attempt to split on lines that open or close blocks. When heuristics do
        not find a natural breakpoint, we fall back to line count and chunk size
        limits. Each returned chunk includes metadata such as start/end line,
        chunk type, and an optional symbol name (function or class name) if
        identifiable.
        """
        if not content.strip():
            return []

        # Determine file extension for language-aware processing
        _, ext = os.path.splitext(file_path.lower())
        brace_languages = {'.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.hpp', '.swift', '.kt'}

        lines = content.split('\n')
        chunks: List[Dict[str, Any]] = []
        current_chunk: List[str] = []
        current_start_line: int = 1
        current_chunk_type: str = 'code'
        current_symbol_name: Optional[str] = None

        for i, line in enumerate(lines):
            line_num = i + 1
            stripped_line = line.strip()

            # Detect standalone docstrings or comment-based docstrings for Python
            is_docstring = False
            if stripped_line.startswith(('"""', "'''")):
                is_docstring = True
            elif stripped_line.startswith('#') and len(stripped_line) > 1 and stripped_line[1] == ' ':
                is_docstring = True

            if is_docstring:
                # Finalize any existing current chunk before starting a docstring chunk
                if current_chunk:
                    chunk_content = '\n'.join(current_chunk)
                    if chunk_content.strip():
                        chunks.append({
                            'index': len(chunks),
                            'content': chunk_content,
                            'start_line': current_start_line,
                            'end_line': line_num - 1,
                            'type': current_chunk_type,
                            'symbol_name': current_symbol_name,
                        })
                    current_chunk = []
                    current_symbol_name = None
                # Add the docstring line as its own chunk
                chunks.append({
                    'index': len(chunks),
                    'content': line,
                    'start_line': line_num,
                    'end_line': line_num,
                    'type': 'docstring',
                    'symbol_name': None,
                })
                # Reset current chunk start line to the next line
                current_start_line = line_num + 1
                # Continue to next line
                continue

            # Detect function/class/import definitions to set chunk type and symbol name
            if any(stripped_line.startswith(keyword) for keyword in ['def ', 'class ', 'import ', 'from ']):
                if 'def ' in stripped_line:
                    current_chunk_type = 'function'
                    # Extract Python function name
                    match = re.match(r'^\s*def\s+([a-zA-Z0-9_]+)', line)
                    current_symbol_name = match.group(1) if match else None
                elif 'class ' in stripped_line:
                    current_chunk_type = 'class'
                    match = re.match(r'^\s*class\s+([a-zA-Z0-9_]+)', line)
                    current_symbol_name = match.group(1) if match else None
                else:
                    current_chunk_type = 'import'
                    current_symbol_name = None
            # Brace-based language heuristics
            elif ext in brace_languages:
                # Identify function or class declarations containing '{'
                brace_open = '{' in stripped_line
                # Heuristic: treat lines containing 'function', 'class', 'enum', 'struct', 'interface' as declarations
                if any(keyword in stripped_line for keyword in ['function', 'class', 'enum', 'struct', 'interface']) and brace_open:
                    # Finalize any existing current chunk before starting a new declaration chunk
                    if current_chunk:
                        chunk_content = '\n'.join(current_chunk)
                        if chunk_content.strip():
                            chunks.append({
                                'index': len(chunks),
                                'content': chunk_content,
                                'start_line': current_start_line,
                                'end_line': line_num - 1,
                                'type': current_chunk_type,
                                'symbol_name': current_symbol_name,
                            })
                        current_chunk = []
                        current_symbol_name = None
                    # Determine declaration type and symbol name
                    if 'function' in stripped_line:
                        current_chunk_type = 'function'
                        match = re.search(r'function\s+([a-zA-Z0-9_]+)', stripped_line)
                        current_symbol_name = match.group(1) if match else None
                    elif 'class' in stripped_line:
                        current_chunk_type = 'class'
                        match = re.search(r'class\s+([a-zA-Z0-9_]+)', stripped_line)
                        current_symbol_name = match.group(1) if match else None
                    else:
                        current_chunk_type = 'code'
                        current_symbol_name = None
                    current_start_line = line_num
                # Break at closing braces for brace languages
                elif stripped_line.startswith('}') or stripped_line == '};':
                    current_chunk_type = 'code'
                    current_symbol_name = None

            # Comments update type for Python
            elif stripped_line == '' or stripped_line in ['{', '}', 'break', 'continue', 'pass', 'return']:
                current_chunk_type = 'code'
            elif stripped_line.startswith('#'):
                current_chunk_type = 'comment'

            current_chunk.append(line)

            # Check if we should create a new chunk
            chunk_content = '\n'.join(current_chunk)
            at_end = i == len(lines) - 1
            should_break = False
            # Always break if chunk exceeds max size
            if len(chunk_content) >= self.chunk_size:
                should_break = True
            # At end of file, flush
            elif at_end:
                should_break = True
            else:
                # Natural breakpoint heuristics
                if self._is_natural_breakpoint(line, current_chunk_type, ext):
                    should_break = True

            if should_break and chunk_content.strip():
                chunks.append({
                    'index': len(chunks),
                    'content': chunk_content,
                    'start_line': current_start_line,
                    'end_line': line_num,
                    'type': current_chunk_type,
                    'symbol_name': current_symbol_name,
                })
                current_chunk = []
                current_start_line = line_num + 1
                current_symbol_name = None

        # Any remaining content after the loop
        if current_chunk:
            chunk_content = '\n'.join(current_chunk)
            if chunk_content.strip():
                chunks.append({
                    'index': len(chunks),
                    'content': chunk_content,
                    'start_line': current_start_line,
                    'end_line': len(lines),
                    'type': current_chunk_type,
                    'symbol_name': current_symbol_name,
                })

        return chunks
    
    def _is_natural_breakpoint(self, line: str, chunk_type: str, ext: Optional[str] = None) -> bool:
        """Determine if a line is a natural breakpoint for chunking.

        This helper checks for common breakpoints such as new declarations,
        decorators, blank lines, and section comments. For brace-based languages,
        we also treat closing braces as natural breakpoints. The ext argument
        allows language-specific logic.
        """
        stripped = line.strip()
        
        # Always break at certain constructs
        if any(stripped.startswith(keyword) for keyword in [
            'def ', 'class ', '@', 'interface ', 'enum ', 'struct '
        ]):
            return True
        
        # For brace languages, break at closing braces on their own line
        brace_langs = {'.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.hpp', '.swift', '.kt'}
        if ext in brace_langs:
            if stripped.startswith('}'):
                return True
        
        # Break at blank lines for code
        if chunk_type == 'code' and not stripped:
            return True
        
        # Break at section comments (e.g. '#------')
        if stripped.startswith('#') and len(stripped) > 1 and stripped[1] in ['-', '=', '~']:
            return True
        
        return False
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation"""
        if not text:
            return 0
        # Simple heuristic: ~4 characters per token for code
        return max(1, len(text) // 4)
    
    def get_ingestion_stats(self, repository_id: int) -> Dict[str, Any]:
        """Get ingestion statistics for a repository"""
        try:
            repository = Repository.objects.get(id=repository_id)
            
            files = IndexedFile.objects.filter(repository=repository)
            chunks = CodeChunk.objects.filter(indexed_file__repository=repository)
            
            # Language breakdown
            languages = {}
            for file in files:
                lang = file.language or 'unknown'
                languages[lang] = languages.get(lang, 0) + 1
            
            # Chunk type breakdown
            chunk_types = {}
            for chunk in chunks:
                chunk_type = chunk.chunk_type
                chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
            
            # Aggregate totals using the imported Sum aggregator rather than referencing ``models``
            total_file_size = files.aggregate(total_size=Sum('file_size'))['total_size'] or 0
            total_tokens = chunks.aggregate(total_tokens=Sum('token_count'))['total_tokens'] or 0
            return {
                'repository': {
                    'id': repository.id,
                    'name': repository.name,
                    'status': repository.indexing_status,
                    'last_indexed': repository.last_indexed_at,
                    'file_count': repository.file_count,
                },
                'files': {
                    'total': files.count(),
                    'total_size': total_file_size,
                    'languages': dict(sorted(languages.items(), key=lambda x: x[1], reverse=True)),
                },
                'chunks': {
                    'total': chunks.count(),
                    'types': chunk_types,
                    'total_tokens': total_tokens,
                }
            }
            
        except Repository.DoesNotExist:
            return {'error': 'Repository not found'}
