"""Utility functions for code editor app."""

import secrets
import json
import time
from typing import Dict, Any, List
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder

__all__ = [
    "generate_secure_token",
    "sanitize_input",
    "calculate_token_estimate",
    "format_latency_ms",
    "format_file_size",
    "extract_code_language",
    "create_error_response",
    "create_success_response",
    "safe_json_serialize",
    "get_client_ip",
    "is_valid_model_name",
    "truncate_string",
    "merge_dicts",
    "parse_accept_language",
    "get_request_id",
]

def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure token."""
    return secrets.token_urlsafe(length)

def sanitize_input(text: str, max_length: int = 100000) -> str:
    """Sanitize and truncate input text."""
    if not text:
        return ""

    # Remove null bytes and other problematic characters
    sanitized = text.replace('\x00', '')

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized.strip()

def calculate_token_estimate(text: str) -> int:
    """Estimate token count for text (rough approximation)."""
    if not text:
        return 0

    # Rough estimation: ~4 characters per token for English
    # This is a very rough approximation and would need proper tokenization
    return max(1, len(text) // 4)

def format_latency_ms(latency_ms: int) -> str:
    """Format latency in human readable format."""
    if latency_ms < 1000:
        return f"{latency_ms}ms"
    elif latency_ms < 60000:
        return f"{latency_ms / 1000:.1f}s"
    else:
        minutes = latency_ms // 60000
        seconds = (latency_ms % 60000) / 1000
        return f"{minutes}m {seconds:.1f}s"

def format_file_size(bytes_count: int) -> str:
    """Format file size in human readable format."""
    if bytes_count < 1024:
        return f"{bytes_count}B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f}KB"
    elif bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f}MB"
    else:
        return f"{bytes_count / (1024 * 1024 * 1024):.1f}GB"

def extract_code_language(filename: str, content: str = "") -> str:
    """Extract programming language from filename or content."""
    if not filename:
        return ""

    # File extension mapping
    extension_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'jsx',
        '.tsx': 'tsx',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.cs': 'csharp',
        '.php': 'php',
        '.rb': 'ruby',
        '.go': 'go',
        '.rs': 'rust',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.r': 'r',
        '.sql': 'sql',
        '.sh': 'bash',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.sass': 'sass',
        '.less': 'less',
        '.xml': 'xml',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.toml': 'toml',
        '.ini': 'ini',
        '.md': 'markdown',
        '.dockerfile': 'dockerfile',
    }

    # Extract extension
    if '.' in filename:
        ext = filename.lower().split('.')[-1]
        ext = '.' + ext
        if ext in extension_map:
            return extension_map[ext]

    # Fallback to content analysis
    if content:
        content_lower = content.lower()

        # Simple heuristics
        if 'def ' in content and 'import ' in content:
            return 'python'
        elif 'function ' in content and 'const ' in content:
            return 'javascript'
        elif 'public class ' in content:
            return 'java'
        elif '#include' in content:
            return 'c'
        elif 'package ' in content and 'import ' in content:
            return 'java'

    return ""

def create_error_response(error_message: str, error_type: str = "Error", status_code: int = 500) -> Dict[str, Any]:
    """Create standardized error response."""
    return {
        'error': {
            'message': error_message,
            'type': error_type,
            'code': status_code,
            'timestamp': timezone.now().isoformat()
        }
    }

def create_success_response(data: Any, message: str = "Success") -> Dict[str, Any]:
    """Create standardized success response."""
    return {
        'success': True,
        'message': message,
        'data': data,
        'timestamp': timezone.now().isoformat()
    }

def safe_json_serialize(obj: Any) -> str:
    """Safely serialize object to JSON."""
    try:
        return json.dumps(obj, cls=DjangoJSONEncoder, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(str(obj), ensure_ascii=False)

def get_client_ip(request) -> str:
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip or 'unknown'

def is_valid_model_name(model_name: str) -> bool:
    """Validate model name format."""
    if not model_name or len(model_name) < 1 or len(model_name) > 255:
        return False

    # Allow alphanumeric, hyphens, underscores, and dots
    allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.')
    return all(c in allowed_chars for c in model_name)

def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate string to max length with suffix."""
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix

def merge_dicts(dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dictionaries recursively."""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result

def parse_accept_language(accept_header: str) -> List[str]:
    """Parse Accept-Language header."""
    if not accept_header:
        return []

    languages: List[str] = []
    for lang in accept_header.split(','):
        lang = lang.strip().split(';')[0]  # Remove quality factor
        languages.append(lang)
    return languages

def get_request_id(request) -> str:
    """Generate or get request ID."""
    # Try to get from header first
    request_id = None
    if hasattr(request, 'headers') and request.headers:
        request_id = request.headers.get('X-Request-ID')
    if not request_id:
        # Generate new request ID
        request_id = f"req_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    return request_id