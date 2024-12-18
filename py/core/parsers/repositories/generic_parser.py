from typing import AsyncGenerator, Dict, Type
from pathlib import Path
import logging

from core.base.parsers.base_parser import AsyncParser
from core.base.models import Document, DocumentExtraction
from .ha_parser import HomeAssistantParser

logger = logging.getLogger(__name__)

class GenericCodeParser(AsyncParser[Document]):
    """
    A generic parser that routes to specific parsers based on repository context
    """
    
    # Registry of repository-specific parsers
    REPO_PARSERS = {
        "home-assistant": HomeAssistantParser,
        # Add more repository parsers as they're implemented
        # "other-repo": OtherRepoParser,
    }

    def __init__(self, config=None, database_provider=None, llm_provider=None):
        self.config = config
        self.database_provider = database_provider
        self.llm_provider = llm_provider
        self._current_parser = None

    def _detect_repo_type(self, document: Document) -> str:
        """
        Detect repository type from document path or other characteristics
        """
        # Get the full path and convert to Path object
        path = Path(document.filename)
        
        # Get root directory name (you might need to adjust this logic)
        root_dir = path.parts[0].lower()

        # Check for home assistant repository
        if "home-assistant" in root_dir or "hassio" in root_dir:
            return "home-assistant"
            
        # Add more repository detection logic here
        
        return "unknown"

    def _get_parser_for_repo(self, repo_type: str) -> AsyncParser:
        """
        Get the appropriate parser for the detected repository type
        """
        parser_class = self.REPO_PARSERS.get(repo_type)
        if parser_class:
            return parser_class(
                config=self.config,
                database_provider=self.database_provider,
                llm_provider=self.llm_provider
            )
        logger.warning(f"No specific parser found for repo type: {repo_type}")
        return None

    async def ingest(self, document: Document, **kwargs) -> AsyncGenerator[DocumentExtraction, None]:
        """
        Route to appropriate parser based on repository context
        """
        try:
            # Detect repository type
            repo_type = self._detect_repo_type(document)
            
            # Get appropriate parser
            specific_parser = self._get_parser_for_repo(repo_type)
            
            if specific_parser:
                # Use specific parser
                async for extraction in specific_parser.ingest(document, **kwargs):
                    yield extraction
            else:
                # Fallback behavior - could implement basic parsing or yield empty
                yield DocumentExtraction(
                    content="",
                    metadata={
                        "error": f"No parser available for repository type: {repo_type}",
                        "file": document.filename
                    }
                )

        except Exception as e:
            logger.error(f"Error in generic parser: {str(e)}")
            yield DocumentExtraction(
                content="",
                metadata={"error": str(e)}
            )