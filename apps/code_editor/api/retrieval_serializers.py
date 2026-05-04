from rest_framework import serializers


class SearchRequestSerializer(serializers.Serializer):
    """Serializer for search/retrieval requests"""
    query = serializers.CharField(
        max_length=2000,
        required=True,
        help_text="Search query"
    )
    repository_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="List of repository IDs to search within"
    )
    file_paths = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        help_text="List of file path patterns to search within"
    )
    languages = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        help_text="List of programming languages to filter by"
    )
    chunk_types = serializers.ListField(
        child=serializers.ChoiceField(choices=[
            'code', 'comment', 'docstring', 'import', 'function', 'class'
        ]),
        required=False,
        help_text="List of chunk types to filter by"
    )
    limit = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=10,
        help_text="Maximum number of results to return"
    )
    similarity_threshold = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        default=0.7,
        help_text="Minimum similarity threshold (0.0-1.0)"
    )
    use_rerank = serializers.BooleanField(
        default=True,
        help_text="Whether to use reranking"
    )


class SearchResultSerializer(serializers.Serializer):
    """Serializer for individual search results"""
    chunk_id = serializers.IntegerField(read_only=True)
    file_path = serializers.CharField(read_only=True)
    repository_id = serializers.IntegerField(read_only=True)
    content = serializers.CharField(read_only=True)
    start_line = serializers.IntegerField(read_only=True)
    end_line = serializers.IntegerField(read_only=True)
    chunk_type = serializers.CharField(read_only=True)
    similarity = serializers.FloatField(read_only=True)
    language = serializers.CharField(read_only=True)
    token_count = serializers.IntegerField(read_only=True)


class SearchResponseSerializer(serializers.Serializer):
    """Serializer for search response"""
    results = SearchResultSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    query = serializers.CharField(read_only=True)
    search_time_ms = serializers.IntegerField(read_only=True)


class ContextRequestSerializer(serializers.Serializer):
    """Serializer for context requests"""
    chunk_id = serializers.IntegerField(required=True)
    context_lines = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=10,
        help_text="Number of lines of context before and after the chunk"
    )


class ContextResponseSerializer(serializers.Serializer):
    """Serializer for context response"""
    chunk_id = serializers.IntegerField(read_only=True)
    file_path = serializers.CharField(read_only=True)
    content = serializers.CharField(read_only=True)
    start_line = serializers.IntegerField(read_only=True)
    end_line = serializers.IntegerField(read_only=True)
    chunk_type = serializers.CharField(read_only=True)
    before_context = serializers.ListField(
        child=serializers.CharField(),
        read_only=True
    )
    after_context = serializers.ListField(
        child=serializers.CharField(),
        read_only=True
    )
    total_chunks = serializers.IntegerField(read_only=True)


class FileSearchRequestSerializer(serializers.Serializer):
    """Serializer for file path search requests"""
    file_path_pattern = serializers.CharField(
        max_length=500,
        required=True,
        help_text="File path pattern to search for"
    )
    repository_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="List of repository IDs to search within"
    )
    limit = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=50,
        help_text="Maximum number of results to return"
    )


class FileSearchResultSerializer(serializers.Serializer):
    """Serializer for file search results"""
    chunk_id = serializers.IntegerField(read_only=True)
    file_path = serializers.CharField(read_only=True)
    repository_id = serializers.IntegerField(read_only=True)
    repository_name = serializers.CharField(read_only=True)
    content = serializers.CharField(read_only=True)
    start_line = serializers.IntegerField(read_only=True)
    end_line = serializers.IntegerField(read_only=True)
    chunk_type = serializers.CharField(read_only=True)
    language = serializers.CharField(read_only=True)
    token_count = serializers.IntegerField(read_only=True)
