import math
from typing import Dict, Any, List, Optional, Tuple
import re
import os
from django.db import connection
from django.db.models import Q, F
from ..models import CodeChunk, IndexedFile
from ..services.embeddings_service import EmbeddingsService
from ..services.rerank_service import RerankService
from ..services.config import ConfigService


class RetrievalService:
    """Service for retrieving relevant code chunks"""
    
    def __init__(self):
        self.embeddings_service = EmbeddingsService()
        self.rerank_service = RerankService()
    
    def search_chunks(
        self,
        query: str,
        repository_ids: Optional[List[int]] = None,
        file_paths: Optional[List[str]] = None,
        languages: Optional[List[str]] = None,
        chunk_types: Optional[List[str]] = None,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        use_rerank: bool = True
    ) -> List[Dict[str, Any]]:
        """Search for relevant code chunks.

        This method first attempts to perform a vector similarity search using
        embeddings. If embeddings are unavailable or an error occurs, it falls
        back to a simple lexical search based on file paths, symbol names, and
        term frequencies. Results are returned as a list of dictionaries with
        relevant metadata. If vector search yields results below the similarity
        threshold, lexical fallback is used as well.
        """
        # Try to generate an embedding for the query. If this fails, we'll do a lexical fallback.
        query_embedding = None
        try:
            query_embedding = self.embeddings_service.generate_embeddings(
                texts=[query],
                model=ConfigService.get_embeddings_config().get('model')
            )[0]
        except Exception:
            query_embedding = None

        results: List[Dict[str, Any]] = []

        # Vector search path
        if query_embedding is not None:
            # Build base SQL query for pgvector similarity search
            base_sql = """
                SELECT cc.id, cc.indexed_file_id, cc.content, cc.start_line, cc.end_line, cc.chunk_type,
                       cc.token_count, cc.symbol_name,
                       1 - (cc.embedding <=> %s) AS similarity
                FROM code_editor_code_chunk cc
                JOIN code_editor_indexed_file fi ON cc.indexed_file_id = fi.id
                WHERE cc.embedding IS NOT NULL
            """
            sql_params: List[Any] = [query_embedding]
            conditions_sql: List[str] = []
            # Apply filters on the indexed_file table
            if repository_ids:
                conditions_sql.append("fi.repository_id = ANY(%s)")
                sql_params.append(repository_ids)
            if file_paths:
                conditions_sql.append("fi.file_path = ANY(%s)")
                sql_params.append(file_paths)
            if languages:
                conditions_sql.append("fi.language = ANY(%s)")
                sql_params.append(languages)
            # Apply filters on chunk_type
            if chunk_types:
                conditions_sql.append("cc.chunk_type = ANY(%s)")
                sql_params.append(chunk_types)
            if conditions_sql:
                base_sql += " AND " + " AND ".join(conditions_sql)
            # Order by similarity, limit results
            base_sql += " ORDER BY similarity DESC LIMIT %s"
            sql_params.append(limit)

            try:
                with connection.cursor() as cursor:
                    cursor.execute(base_sql, sql_params)
                    columns = [col[0] for col in cursor.description]
                    vector_results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                # Filter by similarity threshold
                filtered_results = [
                    r for r in vector_results
                    if r.get('similarity') is not None and r.get('similarity') >= similarity_threshold
                ]
                # Rerank if enabled and multiple results
                if use_rerank and len(filtered_results) > 1:
                    try:
                        filtered_results = self._rerank_results(query, filtered_results, limit)
                    except Exception:
                        pass

                # Format results
                if filtered_results:
                    # Fetch indexed files in bulk to avoid N+1 queries
                    indexed_ids = {r['indexed_file_id'] for r in filtered_results}
                    # Prefetch indexed files and related repository in bulk to avoid N+1 queries
                    file_qs = IndexedFile.objects.filter(id__in=indexed_ids).select_related('repository')
                    files_map = {f.id: f for f in file_qs}
                    for res in filtered_results[:limit]:
                        file_obj = files_map.get(res['indexed_file_id'])
                        if not file_obj:
                            continue
                        results.append({
                            'chunk_id': res['id'],
                            'file_path': file_obj.file_path,
                            'repository_id': file_obj.repository_id,
                            'content': res['content'],
                            'start_line': res['start_line'],
                            'end_line': res['end_line'],
                            'chunk_type': res['chunk_type'],
                            'similarity': res.get('similarity', 0),
                            'language': file_obj.language or 'unknown',
                            'token_count': res['token_count'],
                            'symbol_name': res.get('symbol_name'),
                            'retrieval_strategy': 'vector',
                        })
            except Exception:
                # If vector search fails for any reason, fallback to lexical search
                results = []

            # If we found results above the similarity threshold, return them
            if results:
                return results

        # Lexical fallback search: case-insensitive search on file paths, symbol names, and content
        query_terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", query) if t]
        if not query_terms:
            return []
        # Build Django queryset with OR conditions across query terms
        fallback_queryset = CodeChunk.objects.all()
        if repository_ids:
            fallback_queryset = fallback_queryset.filter(indexed_file__repository_id__in=repository_ids)
        if file_paths:
            fallback_queryset = fallback_queryset.filter(indexed_file__file_path__in=file_paths)
        if languages:
            fallback_queryset = fallback_queryset.filter(indexed_file__language__in=languages)
        if chunk_types:
            fallback_queryset = fallback_queryset.filter(chunk_type__in=chunk_types)
        # Compose Q objects for content and file path matching
        q_objects = Q()
        for term in query_terms:
            q_objects |= Q(content__icontains=term) | Q(indexed_file__file_path__icontains=term) | Q(symbol_name__icontains=term)
        fallback_queryset = fallback_queryset.filter(q_objects)
        # Limit initial candidates to reduce work; adjust multiplier to allow enough ranking
        candidates = list(fallback_queryset.select_related('indexed_file', 'indexed_file__repository')[: limit * 5])

        # Rank candidates based on term frequency and path/symbol matches
        scored: List[Tuple[int, Any]] = []
        for chunk in candidates:
            score = 0
            path_lower = chunk.indexed_file.file_path.lower() if chunk.indexed_file and chunk.indexed_file.file_path else ''
            sym_lower = chunk.symbol_name.lower() if chunk.symbol_name else ''
            content_lower = chunk.content.lower()
            for term in query_terms:
                # Weight exact filename or symbol match higher
                filename = os.path.splitext(os.path.basename(path_lower))[0]
                if term == filename or term == sym_lower:
                    score += 10
                # Count occurrences in path
                if term in path_lower:
                    score += 3
                # Count occurrences in symbol name
                if sym_lower and term in sym_lower:
                    score += 5
                # Count occurrences in content; simple frequency measure
                count = content_lower.count(term)
                score += count
            # Add slight boost for more recent files if available (smaller index indicates earlier chunk)
            scored.append((score, chunk))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, chunk in scored[:limit]:
            results.append({
                'chunk_id': chunk.id,
                'file_path': chunk.indexed_file.file_path,
                'repository_id': chunk.indexed_file.repository.id,
                'content': chunk.content,
                'start_line': chunk.start_line,
                'end_line': chunk.end_line,
                'chunk_type': chunk.chunk_type,
                'similarity': None,
                'language': chunk.indexed_file.language or 'unknown',
                'token_count': chunk.token_count,
                'symbol_name': chunk.symbol_name,
                'retrieval_strategy': 'lexical',
            })
        return results
    
    def _rerank_results(self, query: str, results: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Rerank search results.

        This method delegates to the ``RerankService`` to obtain a
        list of document indices ranked by relevance.  It then
        annotates each result with a ``rerank_score`` (defaulting to
        zero) and sorts the results accordingly.  If reranking is
        unavailable or fails, the original ordering is preserved.

        :param query: Query string
        :param results: List of result dictionaries containing at least a ``content`` key
        :param limit: Maximum number of results to return
        :returns: Reranked list of result dictionaries
        """
        if len(results) <= 1:
            return results
        # Extract document texts from results
        documents = [res.get('content', '') for res in results]
        try:
            # Call rerank service to get relevance scores
            rerank_scores = self.rerank_service.rerank_documents(
                query=query,
                documents=documents,
                top_k=limit
            )
            # Build a mapping from document index to score
            score_map = {entry['index']: entry['relevance_score'] for entry in rerank_scores}
            # Annotate each result with its rerank score (default zero if missing)
            for idx, result in enumerate(results):
                result['rerank_score'] = float(score_map.get(idx, 0.0))
            # Sort results by rerank score descending
            sorted_results = sorted(results, key=lambda x: x.get('rerank_score', 0.0), reverse=True)
            # Limit to the number of rerank scores returned
            if rerank_scores:
                return sorted_results[: len(rerank_scores)]
            else:
                return sorted_results[: limit]
        except Exception:
            # On failure, return original results without reranking
            return results
    
    def _get_file_path(self, indexed_file_id: int) -> str:
        """Get file path from indexed file ID"""
        try:
            file = IndexedFile.objects.get(id=indexed_file_id)
            return file.file_path
        except IndexedFile.DoesNotExist:
            return 'unknown'
    
    def _get_repository_id(self, indexed_file_id: int) -> int:
        """Get repository ID from indexed file ID"""
        try:
            file = IndexedFile.objects.get(id=indexed_file_id)
            return file.repository_id
        except IndexedFile.DoesNotExist:
            return 0
    
    def _get_file_language(self, indexed_file_id: int) -> str:
        """Get file language from indexed file ID"""
        try:
            file = IndexedFile.objects.get(id=indexed_file_id)
            return file.language or 'unknown'
        except IndexedFile.DoesNotExist:
            return 'unknown'
    
    def get_context_for_chunk(
        self,
        chunk_id: int,
        context_lines: int = 10
    ) -> Dict[str, Any]:
        """Get surrounding context for a chunk"""
        try:
            chunk = CodeChunk.objects.select_related('indexed_file').get(id=chunk_id)
            file_path = chunk.indexed_file.file_path
            
            # Get nearby chunks from the same file
            nearby_chunks = CodeChunk.objects.filter(
                indexed_file=chunk.indexed_file
            ).filter(
                Q(chunk_index__gte=chunk.chunk_index - context_lines) &
                Q(chunk_index__lte=chunk.chunk_index + context_lines)
            ).order_by('chunk_index')
            
            # Build context
            before_chunks = []
            after_chunks = []
            current_chunk_found = False
            
            for nearby_chunk in nearby_chunks:
                if nearby_chunk.id == chunk_id:
                    current_chunk_found = True
                elif not current_chunk_found:
                    before_chunks.append(nearby_chunk)
                else:
                    after_chunks.append(nearby_chunk)
            
            return {
                'chunk_id': chunk_id,
                'file_path': file_path,
                'content': chunk.content,
                'start_line': chunk.start_line,
                'end_line': chunk.end_line,
                'chunk_type': chunk.chunk_type,
                'before_context': [c.content for c in before_chunks[-5:]],  # Last 5 before
                'after_context': [c.content for c in after_chunks[:5]],   # First 5 after
                'total_chunks': nearby_chunks.count()
            }
            
        except CodeChunk.DoesNotExist:
            return {
                'chunk_id': chunk_id,
                'error': 'Chunk not found'
            }
    
    def search_by_file_path(
        self,
        file_path_pattern: str,
        repository_ids: Optional[List[int]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search chunks by file path pattern"""
        queryset = CodeChunk.objects.filter(
            indexed_file__file_path__icontains=file_path_pattern
        )
        
        if repository_ids:
            queryset = queryset.filter(
                indexed_file__repository_id__in=repository_ids
            )
        
        chunks = queryset.select_related('indexed_file__repository')[:limit]
        
        results = []
        for chunk in chunks:
            results.append({
                'chunk_id': chunk.id,
                'file_path': chunk.indexed_file.file_path,
                'repository_id': chunk.indexed_file.repository.id,
                'repository_name': chunk.indexed_file.repository.name,
                'content': chunk.content,
                'start_line': chunk.start_line,
                'end_line': chunk.end_line,
                'chunk_type': chunk.chunk_type,
                'language': chunk.indexed_file.language,
                'token_count': chunk.token_count
            })
        
        return results
