# src/utils/llm_client.py
"""
Configurable LLM client supporting both local and API-based models.
Provides unified interface for RAG semantic tagging with batch processing.
"""

import json
import logging
import time
from typing import Dict, List, Any, Optional, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMRequest:
    """Single LLM request for semantic tagging"""
    entity_id: str
    entity_type: str  # container, host, service, etc.
    content: str
    context: Dict[str, Any] = None


@dataclass
class LLMResponse:
    """LLM response with semantic tags"""
    entity_id: str
    success: bool
    tags: Dict[str, str] = None  # {category: tag}
    error: str = None
    metadata: Dict[str, Any] = None


class BaseLLMClient(ABC):
    """Base class for LLM clients"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f'llm.{self.__class__.__name__}')
    
    @abstractmethod
    def generate_tags(self, requests: List[LLMRequest]) -> List[LLMResponse]:
        """Generate semantic tags for a batch of requests"""
        pass
    
    def _create_tagging_prompt(self, request: LLMRequest) -> str:
        """Create the four-question prompt for semantic tagging"""
        entity_type = request.entity_type
        content = request.content
        
        prompt = f"""Please analyze this {entity_type} configuration and answer four questions about it. 
Respond in JSON format with exactly these four fields:

{{
  "generic_name": "one or two word generic/common name for this {entity_type}",
  "problem_solved": "one or two words describing what problem this solves", 
  "infrastructure_role": "one or two words describing its infrastructure role",
  "system_component": "one or two words for the larger system this belongs to, or 'none'"
}}

Configuration to analyze:
{content}

Remember:
- Keep responses to 1-2 words maximum
- Use common technical terms people would search for
- For system_component, respond 'none' if it's not part of a larger system
- Focus on function over implementation details
"""
        return prompt


class OpenAIClient(BaseLLMClient):
    """OpenAI API client for semantic tagging"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get('api_key')
        self.model = config.get('model', 'gpt-3.5-turbo')
        self.max_tokens = config.get('max_tokens', 150)
        self.temperature = config.get('temperature', 0.1)
        self.batch_size = config.get('batch_size', 5)
        
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
    
    def generate_tags(self, requests: List[LLMRequest]) -> List[LLMResponse]:
        """Generate tags using OpenAI API"""
        try:
            import openai
            openai.api_key = self.api_key
        except ImportError:
            self.logger.error("OpenAI library not installed. Run: pip install openai")
            return [LLMResponse(req.entity_id, False, error="OpenAI library not available") 
                   for req in requests]
        
        responses = []
        
        # Process in batches
        for i in range(0, len(requests), self.batch_size):
            batch = requests[i:i + self.batch_size]
            batch_responses = self._process_batch(batch)
            responses.extend(batch_responses)
            
            # Rate limiting
            if i + self.batch_size < len(requests):
                time.sleep(1)
        
        return responses
    
    def _process_batch(self, batch: List[LLMRequest]) -> List[LLMResponse]:
        """Process a single batch of requests"""
        responses = []
        
        for request in batch:
            try:
                prompt = self._create_tagging_prompt(request)
                
                # Make API call
                import openai
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=30
                )
                
                # Parse response
                content = response.choices[0].message.content.strip()
                tags = self._parse_tag_response(content)
                
                responses.append(LLMResponse(
                    entity_id=request.entity_id,
                    success=True,
                    tags=tags,
                    metadata={
                        'model': self.model,
                        'tokens_used': response.usage.total_tokens
                    }
                ))
                
            except Exception as e:
                self.logger.error(f"OpenAI API error for {request.entity_id}: {e}")
                responses.append(LLMResponse(
                    entity_id=request.entity_id,
                    success=False,
                    error=str(e)
                ))
        
        return responses
    
    def _parse_tag_response(self, content: str) -> Dict[str, str]:
        """Parse LLM JSON response into tags dictionary"""
        try:
            # Try to parse as JSON
            data = json.loads(content)
            
            # Validate expected fields
            expected_fields = ['generic_name', 'problem_solved', 'infrastructure_role', 'system_component']
            tags = {}
            
            for field in expected_fields:
                if field in data and data[field] and data[field].lower() != 'none':
                    tags[field] = str(data[field]).strip().lower()
            
            return tags
            
        except json.JSONDecodeError:
            # Fallback: try to extract fields from text
            self.logger.warning(f"Failed to parse JSON response, attempting text extraction: {content}")
            return self._extract_tags_from_text(content)
    
    def _extract_tags_from_text(self, content: str) -> Dict[str, str]:
        """Fallback method to extract tags from unstructured text"""
        # Simple text extraction as fallback
        lines = content.lower().split('\\n')
        tags = {}
        
        for line in lines:
            if 'generic' in line or 'name' in line:
                # Extract after colon or quotes
                parts = line.split(':')[-1].strip(' "')
                if parts and parts != 'none':
                    tags['generic_name'] = parts
            elif 'problem' in line or 'solve' in line:
                parts = line.split(':')[-1].strip(' "')
                if parts and parts != 'none':
                    tags['problem_solved'] = parts
            elif 'role' in line or 'infrastructure' in line:
                parts = line.split(':')[-1].strip(' "')
                if parts and parts != 'none':
                    tags['infrastructure_role'] = parts
            elif 'system' in line or 'component' in line:
                parts = line.split(':')[-1].strip(' "')
                if parts and parts != 'none':
                    tags['system_component'] = parts
        
        return tags


class LocalLLMClient(BaseLLMClient):
    """Local LLM client (placeholder for future implementation)"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_path = config.get('model_path')
        self.model_type = config.get('model_type', 'llama')
    
    def generate_tags(self, requests: List[LLMRequest]) -> List[LLMResponse]:
        """Generate tags using local LLM"""
        # TODO: Implement local LLM integration (ollama, llama.cpp, etc.)
        self.logger.warning("Local LLM not yet implemented, returning fallback tags")
        
        responses = []
        for request in requests:
            # Fallback to rule-based tagging
            tags = self._generate_fallback_tags(request)
            responses.append(LLMResponse(
                entity_id=request.entity_id,
                success=True,
                tags=tags,
                metadata={'method': 'fallback_rules'}
            ))
        
        return responses
    
    def _generate_fallback_tags(self, request: LLMRequest) -> Dict[str, str]:
        """Rule-based fallback tagging"""
        content = request.content.lower()
        tags = {}
        
        # Simple rule-based extraction based on common patterns
        if 'redis' in content:
            tags.update({
                'generic_name': 'redis',
                'problem_solved': 'caching',
                'infrastructure_role': 'middleware'
            })
        elif 'postgres' in content or 'mysql' in content:
            tags.update({
                'generic_name': 'database',
                'problem_solved': 'storage',
                'infrastructure_role': 'backend'
            })
        elif 'nginx' in content or 'traefik' in content:
            tags.update({
                'generic_name': 'proxy',
                'problem_solved': 'routing',
                'infrastructure_role': 'frontend'
            })
        elif 'grafana' in content:
            tags.update({
                'generic_name': 'grafana',
                'problem_solved': 'visualization',
                'infrastructure_role': 'monitoring'
            })
        elif 'prometheus' in content:
            tags.update({
                'generic_name': 'prometheus',
                'problem_solved': 'metrics',
                'infrastructure_role': 'monitoring'
            })
        
        return tags


class LLMClientFactory:
    """Factory for creating LLM clients"""
    
    @staticmethod
    def create_client(llm_config: Dict[str, Any]) -> BaseLLMClient:
        """Create appropriate LLM client based on configuration"""
        client_type = llm_config.get('type', 'local').lower()
        
        if client_type == 'openai':
            return OpenAIClient(llm_config)
        elif client_type == 'local':
            return LocalLLMClient(llm_config)
        else:
            raise ValueError(f"Unknown LLM client type: {client_type}")


# Convenience function for processors
def create_llm_client(config: Dict[str, Any]) -> BaseLLMClient:
    """Create LLM client from configuration"""
    return LLMClientFactory.create_client(config)