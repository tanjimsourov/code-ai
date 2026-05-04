from typing import List, Dict, Any, Optional


class PromptBuilderService:
    """Service for building prompts for different AI tasks"""
    
    @staticmethod
    def build_chat_prompt(messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        """Build chat prompt with optional system message"""
        if system_prompt:
            # Insert system message at the beginning if not already present
            if not messages or messages[0].get('role') != 'system':
                return [{'role': 'system', 'content': system_prompt}] + messages
        return messages
    
    @staticmethod
    def build_completion_prompt(
        prefix: str,
        suffix: Optional[str] = None,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        cursor_context: Optional[str] = None
    ) -> str:
        """Build completion prompt"""
        prompt_parts = []
        
        # Add language context
        if language:
            prompt_parts.append(f"Language: {language}")
        
        # Add filename context
        if filename:
            prompt_parts.append(f"File: {filename}")
        
        # Add cursor context
        if cursor_context:
            prompt_parts.append(f"Context: {cursor_context}")
        
        # Add the main prefix
        prompt_parts.append(f"Code to complete:\n{prefix}")
        
        # Add suffix if provided
        if suffix:
            prompt_parts.append(f"Expected suffix:\n{suffix}")
        
        return "\n\n".join(prompt_parts)
    
    @staticmethod
    def build_edit_prompt(
        instruction: str,
        code: str,
        language: Optional[str] = None,
        filename: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Build edit prompt"""
        system_prompt = "You are a code editing assistant. Follow the instruction to edit the provided code. Return only the modified code without explanations."
        
        if language:
            system_prompt += f" The code is written in {language}."
        
        user_prompt = f"Instruction: {instruction}\n\nCode:\n```\n{code}\n```"
        
        if filename:
            user_prompt += f"\n\nFile: {filename}"
        
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
    
    @staticmethod
    def build_embeddings_context(texts: List[str], task: Optional[str] = None) -> List[str]:
        """Build context for embeddings"""
        if task == 'search':
            # For search queries, keep as-is
            return texts
        elif task == 'code':
            # For code, add language hints if possible
            processed_texts = []
            for text in texts:
                if any(char in text for char in ['{', '}', ';', 'def', 'class', 'import']):
                    processed_texts.append(f"Code: {text}")
                else:
                    processed_texts.append(text)
            return processed_texts
        else:
            return texts
    
    @staticmethod
    def build_rerank_context(query: str, documents: List[str]) -> tuple[str, List[str]]:
        """Build context for reranking"""
        # Clean up query
        clean_query = query.strip()
        
        # Process documents
        processed_docs = []
        for doc in documents:
            clean_doc = doc.strip()
            if clean_doc:
                processed_docs.append(clean_doc)
        
        return clean_query, processed_docs

    # ------------------------------------------------------------------
    # Infill prompt builder

    @staticmethod
    def build_infill_prompt(
        prefix: str,
        suffix: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        cursor_context: Optional[str] = None
    ) -> str:
        """Build a fill‑in‑the‑middle prompt.

        This helper constructs a deterministic prompt for infill
        completions.  It incorporates optional hints such as the
        programming language, filename and cursor context.  The
        resulting prompt instructs the model to return only the code
        that should be inserted between the given prefix and suffix.

        :param prefix: Code appearing before the insertion point
        :param suffix: Code appearing after the insertion point
        :param language: Optional programming language hint
        :param filename: Optional filename hint
        :param cursor_context: Optional additional context near the cursor
        :returns: A single string prompt
        """
        prompt_parts: List[str] = []
        # Add language hint
        if language:
            prompt_parts.append(f"Language: {language}")
        # Add filename hint
        if filename:
            prompt_parts.append(f"File: {filename}")
        # Add cursor context hint
        if cursor_context:
            prompt_parts.append(f"Context: {cursor_context}")
        # Instruction for infill
        prompt_parts.append(
            "Please insert the missing code between the following prefix and suffix. "
            "Return only the code that should be inserted, without any additional explanations."
        )
        # Include the prefix and suffix
        prompt_parts.append(f"Prefix:\n{prefix}")
        prompt_parts.append(f"Suffix:\n{suffix}")
        return "\n\n".join(prompt_parts)
