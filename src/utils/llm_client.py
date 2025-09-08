"""
Configurable LLM client supporting both local and API-based models.
Provides unified interface for RAG semantic tagging with batch processing.
"""

import json
import logging
import time
import requests
from typing import Dict, List, Any, Optional
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
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 2)

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


class OllamaClient(BaseLLMClient):
    """Ollama local LLM client"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Get Ollama-specific config
        ollama_config = config.get('local', config.get('ollama', {}))
        self.base_url = ollama_config.get('base_url', 'http://localhost:11434')
        self.model = ollama_config.get('model', 'llama3.2:3b')
        self.timeout = ollama_config.get('timeout', 60)
        self.max_tokens = config.get('max_tokens', 150)
        self.temperature = config.get('temperature', 0.1)
        self.batch_size = config.get('batch_size', 1)  # Ollama works better with single requests

        # Ensure URL format
        if not self.base_url.startswith('http'):
            self.base_url = f'http://{self.base_url}'
        if not self.base_url.endswith('/api/generate'):
            self.base_url = f"{self.base_url.rstrip('/')}/api/generate"

    def generate_tags(self, requests: List[LLMRequest]) -> List[LLMResponse]:
        """Generate tags using Ollama API"""
        responses = []

        # Test connection first
        if not self._test_connection():
            return [LLMResponse(req.entity_id, False, error="Ollama connection failed") for req in requests]

        # Process requests (Ollama typically works better with individual requests)
        for request in requests:
            response = self._process_single_request(request)
            responses.append(response)

            # Small delay between requests to avoid overwhelming local LLM
            if len(requests) > 1:
                time.sleep(0.5)

        return responses

    def _test_connection(self) -> bool:
        """Test connection to Ollama server"""
        try:
            # Check if Ollama is running
            health_url = self.base_url.replace('/api/generate', '/api/tags')
            response = requests.get(health_url, timeout=5)

            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [m.get('name', '') for m in models]

                if self.model in model_names:
                    self.logger.info(f"Ollama connection successful, model {self.model} available")
                    return True
                else:
                    self.logger.warning(f"Model {self.model} not found. Available: {model_names}")
                    return False
            else:
                self.logger.error(f"Ollama health check failed: {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to connect to Ollama at {self.base_url}: {e}")
            return False

    def _process_single_request(self, request: LLMRequest) -> LLMResponse:
        """Process a single request with retries"""
        prompt = self._create_tagging_prompt(request)

        for attempt in range(self.max_retries):
            try:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens
                    }
                }

                response = requests.post(
                    self.base_url,
                    json=payload,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result.get('response', '').strip()

                    # Parse the JSON response
                    tags = self._parse_tag_response(content)

                    return LLMResponse(
                        entity_id=request.entity_id,
                        success=True,
                        tags=tags,
                        metadata={
                            'model': self.model,
                            'attempt': attempt + 1,
                            'response_time': result.get('total_duration', 0) / 1000000  # Convert to ms
                        }
                    )
                else:
                    self.logger.warning(f"Ollama API error {response.status_code}: {response.text}")

            except Exception as e:
                self.logger.error(f"Ollama request failed (attempt {attempt + 1}): {e}")

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))

        return LLMResponse(
            entity_id=request.entity_id,
            success=False,
            error=f"Failed after {self.max_retries} attempts"
        )

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
            self.logger.warning(f"Failed to parse JSON response, attempting text extraction")
            return self._extract_tags_from_text(content)

    def _extract_tags_from_text(self, content: str) -> Dict[str, str]:
        """Fallback method to extract tags from unstructured text"""
        tags = {}
        lines = content.lower().split('\n')

        for line in lines:
            if 'generic' in line or 'name' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['generic_name'] = parts
            elif 'problem' in line or 'solve' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['problem_solved'] = parts
            elif 'role' in line or 'infrastructure' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['infrastructure_role'] = parts
            elif 'system' in line or 'component' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['system_component'] = parts

        return tags


class OpenAICompatibleClient(BaseLLMClient):
    """Client for OpenAI-compatible APIs (LM Studio, text-generation-webui, etc.)"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Determine which local config to use
        if config.get('type') == 'lmstudio':
            api_config = config.get('lmstudio', {})
        elif config.get('type') == 'textgen':
            api_config = config.get('textgen', {})
        else:
            api_config = config.get('openai', {})

        self.base_url = api_config.get('base_url', 'http://localhost:1234/v1')
        self.model = api_config.get('model', 'local-model')
        self.api_key = api_config.get('api_key', 'not-needed')  # Local APIs often don't need real keys
        self.timeout = api_config.get('timeout', 60)
        self.max_tokens = config.get('max_tokens', 150)
        self.temperature = config.get('temperature', 0.1)
        self.batch_size = config.get('batch_size', 3)

    def generate_tags(self, requests: List[LLMRequest]) -> List[LLMResponse]:
        """Generate tags using OpenAI-compatible API"""
        responses = []

        # Process in batches
        for i in range(0, len(requests), self.batch_size):
            batch = requests[i:i + self.batch_size]
            batch_responses = self._process_batch(batch)
            responses.extend(batch_responses)

            # Small delay between batches
            if i + self.batch_size < len(requests):
                time.sleep(1)

        return responses

    def _process_batch(self, batch: List[LLMRequest]) -> List[LLMResponse]:
        """Process a batch of requests"""
        responses = []

        for request in batch:
            response = self._process_single_request(request)
            responses.append(response)

        return responses

    def _process_single_request(self, request: LLMRequest) -> LLMResponse:
        """Process single request with OpenAI-compatible API"""
        prompt = self._create_tagging_prompt(request)

        for attempt in range(self.max_retries):
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self.api_key}'
                }

                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature
                }

                response = requests.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content'].strip()

                    # Parse response
                    tags = self._parse_tag_response(content)

                    return LLMResponse(
                        entity_id=request.entity_id,
                        success=True,
                        tags=tags,
                        metadata={
                            'model': self.model,
                            'attempt': attempt + 1,
                            'tokens_used': result.get('usage', {}).get('total_tokens', 0)
                        }
                    )
                else:
                    self.logger.warning(f"API error {response.status_code}: {response.text}")

            except Exception as e:
                self.logger.error(f"API request failed (attempt {attempt + 1}): {e}")

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))

        return LLMResponse(
            entity_id=request.entity_id,
            success=False,
            error=f"Failed after {self.max_retries} attempts"
        )

    def _parse_tag_response(self, content: str) -> Dict[str, str]:
        """Parse LLM response (same as Ollama)"""
        try:
            data = json.loads(content)
            expected_fields = ['generic_name', 'problem_solved', 'infrastructure_role', 'system_component']
            tags = {}

            for field in expected_fields:
                if field in data and data[field] and data[field].lower() != 'none':
                    tags[field] = str(data[field]).strip().lower()

            return tags

        except json.JSONDecodeError:
            return self._extract_tags_from_text(content)

    def _extract_tags_from_text(self, content: str) -> Dict[str, str]:
        """Same text extraction as Ollama client"""
        tags = {}
        lines = content.lower().split('\n')

        for line in lines:
            if 'generic' in line or 'name' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['generic_name'] = parts
            elif 'problem' in line or 'solve' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['problem_solved'] = parts
            elif 'role' in line or 'infrastructure' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['infrastructure_role'] = parts
            elif 'system' in line or 'component' in line:
                parts = line.split(':')[-1].strip(' "\'')
                if parts and parts != 'none':
                    tags['system_component'] = parts

        return tags


class LLMClientFactory:
    """Enhanced factory for creating LLM clients"""

    @staticmethod
    def create_client(llm_config: Dict[str, Any]) -> BaseLLMClient:
        """Create appropriate LLM client based on configuration"""
        client_type = llm_config.get('type', 'local').lower()

        if client_type in ['ollama', 'local']:
            return OllamaClient(llm_config)
        elif client_type in ['lmstudio', 'textgen']:
            return OpenAICompatibleClient(llm_config)
        elif client_type == 'openai':
            return OpenAIClient(llm_config)  # Keep existing OpenAI client
        else:
            raise ValueError(f"Unknown LLM client type: {client_type}")


# Convenience function for processors
def create_llm_client(config: Dict[str, Any]) -> BaseLLMClient:
    """Create LLM client from configuration"""
    return LLMClientFactory.create_client(config)