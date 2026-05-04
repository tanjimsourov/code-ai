from typing import List, Dict, Any, Optional

from ..utils.token_counter import TokenCounter


class ContextBuilderService:
    """Service for building token-aware context for AI requests.

    This service truncates input messages and code based on token
    limits rather than raw character counts.  When optional tokenizer
    libraries are unavailable, token counts are approximated using a
    simple heuristic (approximately one token per four characters).

    For backward compatibility, the ``max_chars`` parameter names are
    retained, but they are interpreted as maximum token counts.  Old
    code passing character counts will continue to work because the
    approximate token counter scales proportionally.
    """
    
    @staticmethod
    def build_chat_context(
        messages: List[Dict[str, str]],
        max_chars: int = 100000
    ) -> List[Dict[str, str]]:
        """
        Build a chat context limited by a maximum token budget.

        Messages are truncated from the beginning until the total token
        count of their ``content`` fields fits within ``max_chars``
        (interpreted as a token limit).  The most recent messages are
        retained and the latest user/system message is always
        preserved even if it exceeds the limit.  If no messages fit
        within the budget, the last message is included regardless of
        its size.

        :param messages: List of message dicts with ``content`` keys
        :param max_chars: Maximum number of tokens allowed (legacy name)
        :returns: Truncated list of messages
        """
        if not messages:
            return []
        token_counter = TokenCounter()
        total_tokens = sum(token_counter.count_tokens(m.get('content', '') or '') for m in messages)
        # If messages already fit within the limit, return as is
        if total_tokens <= max_chars:
            return messages
        context_messages: List[Dict[str, str]] = []
        current_tokens = 0
        # Iterate from most recent to oldest and accumulate until limit reached
        for message in reversed(messages):
            msg_content = message.get('content', '') or ''
            msg_tokens = token_counter.count_tokens(msg_content)
            if current_tokens + msg_tokens <= max_chars:
                context_messages.insert(0, message)
                current_tokens += msg_tokens
            else:
                # If this message alone exceeds the budget, we still include it
                # at least to provide some context for the request
                if not context_messages:
                    context_messages = [message]
                break
        return context_messages
    
    @staticmethod
    def build_completion_context(
        prefix: str,
        suffix: Optional[str] = None,
        max_chars: int = 100000
    ) -> Dict[str, str]:
        """
        Build a completion context limited by token budget.

        The prefix is always preserved in full.  The suffix is
        truncated so that the combined token count does not exceed
        ``max_chars`` (interpreted as a token limit).  If the prefix
        alone exceeds the budget, the suffix is dropped entirely.

        :param prefix: Prompt prefix
        :param suffix: Optional suffix
        :param max_chars: Maximum number of tokens allowed
        :returns: Dict with ``prefix`` and optional ``suffix`` keys
        """
        token_counter = TokenCounter()
        context: Dict[str, str] = {'prefix': prefix}
        if not suffix:
            return context
        prefix_tokens = token_counter.count_tokens(prefix)
        suffix_tokens = token_counter.count_tokens(suffix)
        # If the prefix and suffix together fit within the budget, keep both
        if prefix_tokens + suffix_tokens <= max_chars:
            context['suffix'] = suffix
            return context
        # If prefix alone exceeds the budget, drop suffix entirely
        if prefix_tokens >= max_chars:
            context['suffix'] = ''
            return context
        # Otherwise, truncate suffix to fit remaining tokens
        available_tokens = max_chars - prefix_tokens
        # Approximate character limit for suffix
        # We use 4 chars per token heuristic to slice the suffix
        approx_chars = available_tokens * 4
        truncated_suffix = suffix[:approx_chars]
        # In rare cases this may still exceed token limit; trim further
        # iteratively if needed (conservative)
        while token_counter.count_tokens(truncated_suffix) > available_tokens and len(truncated_suffix) > 1:
            truncated_suffix = truncated_suffix[:-1]
        context['suffix'] = truncated_suffix
        return context
    
    @staticmethod
    def build_edit_context(
        instruction: str,
        code: str,
        max_chars: int = 100000
    ) -> Dict[str, str]:
        """
        Build an edit context limited by token budget.

        The instruction is prioritised and always included in full.
        The code is truncated from the end to ensure the combined
        token count does not exceed ``max_chars`` (token budget).  If
        the instruction alone exceeds the limit, it is truncated and
        the code is dropped.

        :param instruction: Instruction string
        :param code: Source code to edit
        :param max_chars: Maximum number of tokens allowed
        :returns: Dict with ``instruction`` and ``code`` keys
        """
        token_counter = TokenCounter()
        instr_tokens = token_counter.count_tokens(instruction)
        code_tokens = token_counter.count_tokens(code)
        # If instruction + code fits, return as is
        if instr_tokens + code_tokens <= max_chars:
            return {'instruction': instruction, 'code': code}
        # If instruction alone exceeds the limit, truncate instruction
        if instr_tokens >= max_chars:
            # Approximate truncation by chars
            approx_chars = max_chars * 4
            truncated_instr = instruction[:approx_chars]
            # Trim down until token count fits
            while token_counter.count_tokens(truncated_instr) > max_chars and len(truncated_instr) > 1:
                truncated_instr = truncated_instr[:-1]
            return {'instruction': truncated_instr, 'code': ''}
        # Otherwise, truncate code to fit remaining tokens
        available_tokens = max_chars - instr_tokens
        approx_chars = available_tokens * 4
        truncated_code = code[:approx_chars]
        while token_counter.count_tokens(truncated_code) > available_tokens and len(truncated_code) > 1:
            truncated_code = truncated_code[:-1]
        return {'instruction': instruction, 'code': truncated_code}
    
    @staticmethod
    def build_embeddings_context(
        texts: List[str],
        max_chars_per_text: int = 8000,
        max_total_chars: int = 100000
    ) -> List[str]:
        """
        Build embeddings context limited by a token budget.

        The ``max_chars_per_text`` and ``max_total_chars`` parameters
        represent token budgets rather than raw character counts.  Each
        input text is truncated individually so that it does not
        exceed ``max_chars_per_text`` tokens, and the list of texts is
        truncated once the cumulative token count reaches
        ``max_total_chars``.  If the optional tokenizer libraries are
        unavailable, token counts are approximated using the heuristic
        of one token per four characters.  Parameter names are
        retained for compatibility with existing code.

        :param texts: List of input strings to embed
        :param max_chars_per_text: Maximum tokens per individual text
        :param max_total_chars: Maximum total tokens across all texts
        :returns: List of truncated texts not exceeding the token budget
        """
        token_counter = TokenCounter()
        processed_texts: List[str] = []
        total_tokens = 0
        for text in texts:
            # Truncate individual text if it exceeds per-text budget
            text_tokens = token_counter.count_tokens(text)
            if text_tokens > max_chars_per_text:
                # Approximate truncation by characters (4 chars per token)
                approx_chars = max_chars_per_text * 4
                truncated = text[:approx_chars]
                # Ensure token count fits within per-text limit
                while token_counter.count_tokens(truncated) > max_chars_per_text and len(truncated) > 1:
                    truncated = truncated[:-1]
                text = truncated
                text_tokens = token_counter.count_tokens(text)
            # Stop adding texts if total token budget would be exceeded
            if total_tokens + text_tokens > max_total_chars:
                break
            processed_texts.append(text)
            total_tokens += text_tokens
        return processed_texts
    
    @staticmethod
    def build_rerank_context(
        query: str,
        documents: List[str],
        max_chars_per_doc: int = 4000,
        max_total_chars: int = 50000
    ) -> tuple[str, List[str]]:
        """
        Build rerank context limited by a token budget.

        The parameters ``max_chars_per_doc`` and ``max_total_chars``
        represent token budgets rather than raw character counts.  The
        query is trimmed to a maximum of 1000 tokens, while each
        document is truncated so that it does not exceed
        ``max_chars_per_doc`` tokens.  Documents are added until the
        cumulative token count of the query and documents reaches
        ``max_total_chars``.  If only approximate token counts are
        available, a 4‑character per token heuristic is used.  Names
        of the parameters are retained for backward compatibility.

        :param query: Search query string
        :param documents: List of documents to rerank
        :param max_chars_per_doc: Maximum tokens per document
        :param max_total_chars: Maximum total tokens for query and docs
        :returns: A tuple of (trimmed_query, list_of_trimmed_docs)
        """
        token_counter = TokenCounter()
        # Trim and cap the query at 1000 tokens (legacy constant)
        query = query.strip()
        if query:
            query_tokens = token_counter.count_tokens(query)
            if query_tokens > 1000:
                # Approximate truncation by characters
                approx_chars = 1000 * 4
                truncated = query[:approx_chars]
                while token_counter.count_tokens(truncated) > 1000 and len(truncated) > 1:
                    truncated = truncated[:-1]
                query = truncated
                query_tokens = token_counter.count_tokens(query)
        else:
            query_tokens = 0
        processed_docs: List[str] = []
        total_tokens = query_tokens
        for doc in documents:
            doc = doc.strip()
            if not doc:
                continue
            doc_tokens = token_counter.count_tokens(doc)
            if doc_tokens > max_chars_per_doc:
                approx_chars = max_chars_per_doc * 4
                truncated_doc = doc[:approx_chars]
                while token_counter.count_tokens(truncated_doc) > max_chars_per_doc and len(truncated_doc) > 1:
                    truncated_doc = truncated_doc[:-1]
                doc = truncated_doc
                doc_tokens = token_counter.count_tokens(doc)
            # Stop adding documents if total token budget exceeded
            if total_tokens + doc_tokens > max_total_chars:
                break
            processed_docs.append(doc)
            total_tokens += doc_tokens
        return query, processed_docs
