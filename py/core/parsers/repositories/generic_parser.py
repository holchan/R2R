from typing import AsyncGenerator
from pathlib import Path
import logging

from core.base.parsers.base_parser import AsyncParser

logger = logging.getLogger(__name__)

class GenericCodeParser(AsyncParser[bytes]):
    """
    A generic parser that routes to specific parsers based on repository context.
    This parser handles various code files by detecting the repository type
    and using appropriate specialized parsers.
    """
    
    # Registry of repository-specific parsers
    REPO_PARSERS = {
        "home-assistant": "HAParser",
        # Add more repository parsers as they're implemented
        # "other-repo": "OtherRepoParser",
    }

    def __init__(self, config=None, database_provider=None, llm_provider=None):
        """
        Initialize the generic code parser.
        
        Args:
            config: Configuration settings for the parser
            database_provider: Database provider instance
            llm_provider: Language model provider instance
        """
        self.config = config
        self.database_provider = database_provider
        self.llm_provider = llm_provider
        self._current_parser = None

    def _detect_repo_type(self, path: Path) -> str:
        """
        Detect repository type from file path or characteristics.
        
        Args:
            path: Path object representing the file location
            
        Returns:
            str: Detected repository type or "unknown"
        """
        path_str = str(path).lower()
        
        # Check for home assistant repository
        if any(x in path_str for x in ["home-assistant", "hassio", "homeassistant"]):
            return "home-assistant"
            
        # Add more repository detection logic here
        
        return "unknown"

    def _get_parser_for_repo(self, repo_type: str) -> AsyncParser | None:
        """
        Get the appropriate parser instance for the detected repository type.
        
        Args:
            repo_type: String identifying the repository type
            
        Returns:
            AsyncParser or None: Parser instance if available
        """
        parser_name = self.REPO_PARSERS.get(repo_type)
        if not parser_name:
            return None
            
        # Import parser dynamically to avoid circular imports
        try:
            # Dynamic import based on repo type
            if repo_type == "home-assistant":
                from .ha_parser import HAParser
                return HAParser(
                    config=self.config,
                    database_provider=self.database_provider,
                    llm_provider=self.llm_provider
                )
            # Add more parser imports as needed
            
        except ImportError as e:
            logger.error(f"Failed to import parser {parser_name}: {str(e)}")
            return None

    async def ingest(self, data: bytes, **kwargs) -> AsyncGenerator[str, None]:
        """
        Parse code files based on repository context.
        
        Args:
            data: Raw bytes of the file content
            **kwargs: Additional arguments including filename
            
        Yields:
            str: Parsed content chunks
        """
        try:
            # Get filename from kwargs
            filename = kwargs.get("filename", "")
            if not filename:
                logger.warning("No filename provided in kwargs")
                yield ""
                return
                
            # Detect repository type from path
            repo_type = self._detect_repo_type(Path(filename))
            logger.info(f"Detected repository type: {repo_type}")
            
            # Get appropriate parser
            specific_parser = self._get_parser_for_repo(repo_type)
            
            if specific_parser:
                # Use specific parser
                async for chunk in specific_parser.ingest(data, **kwargs):
                    yield chunk
            else:
                # Fallback to basic text extraction
                logger.info(f"No specific parser for {repo_type}, falling back to basic text extraction")
                text = data.decode('utf-8', errors='ignore')
                yield text

        except Exception as e:
            logger.error(f"Error in generic parser: {str(e)}")
            yield ""

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._current_parser:
            await self._current_parser.__aexit__(exc_type, exc_val, exc_tb)