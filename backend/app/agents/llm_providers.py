"""
LLM provider abstraction for multiple providers.
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Base class for LLM providers."""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate response from LLM."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider."""
    
    def __init__(self):
        try:
            import openai
            self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            self.model = settings.LLM_MODEL
        except ImportError:
            raise ImportError("openai package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI: {e}")
            raise
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate response using OpenAI."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}", exc_info=True)
            raise


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider."""
    
    def __init__(self):
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = settings.LLM_MODEL
        except ImportError:
            raise ImportError("anthropic package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic: {e}")
            raise
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate response using Anthropic."""
        try:
            system = system_prompt or "You are a helpful assistant."
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic generation failed: {e}", exc_info=True)
            raise


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""
    
    def __init__(self):
        try:
            import ollama
            self.client = ollama.Client(host=settings.OLLAMA_BASE_URL)
            self.model = settings.LLM_MODEL
        except ImportError:
            raise ImportError("ollama package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama: {e}")
            raise
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate response using Ollama."""
        try:
            system = system_prompt or "You are a helpful assistant."
            
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                system=system
            )
            
            return response.get("response", "")
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}", exc_info=True)
            raise


def get_llm_provider() -> LLMProvider:
    """Get LLM provider based on configuration."""
    provider_name = settings.LLM_PROVIDER.lower()
    
    if provider_name == "openai":
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not configured")
        return OpenAIProvider()
    elif provider_name == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not configured")
        return AnthropicProvider()
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        raise ValueError(f"Unsupported LLM provider: {provider_name}")

