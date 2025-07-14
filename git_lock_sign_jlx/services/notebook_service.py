"""
Service for notebook metadata management and content hashing.
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional
from git_lock_sign_jlx.logger_util import default_logger_config


logger = logging.getLogger(__name__)
default_logger_config(logger)


class NotebookService:
    """Service for managing notebook metadata and content operations."""
    
    def __init__(self):
        """Initialize the notebook service."""
        pass
    
    def generate_content_hash(self, notebook_content: Dict[str, Any]) -> str:
        """
        Generate SHA-256 hash of notebook content.
        
        Args:
            notebook_content: Notebook content as dictionary
            
        Returns:
            SHA-256 hash as hexadecimal string
        """
        try:
            # Create a copy of notebook content without metadata to ensure consistent hashing
            content_for_hash = self._prepare_content_for_hashing(notebook_content)
            
            # Convert to JSON string with consistent formatting
            content_json = json.dumps(content_for_hash, sort_keys=True, separators=(',', ':'))
            
            # Generate SHA-256 hash
            hash_object = hashlib.sha256(content_json.encode('utf-8'))
            content_hash = hash_object.hexdigest()
            
            logger.debug(f"Generated content hash: {content_hash}")
            return content_hash
            
        except Exception as e:
            logger.error(f"Error generating content hash: {str(e)}")
            raise
    
    def _prepare_content_for_hashing(self, notebook_content: Dict[str, Any]) -> Any:
        """
        Prepare notebook content for consistent hashing by extracting only the essential,
        user-generated content: cell source and outputs. This makes the hash immune
        to any metadata changes.

        Args:
            notebook_content: Original notebook content as a dictionary.

        Returns:
            A simplified, clean data structure (list of dicts) for hashing.
        """
        logger.info("NotebookService: Preparing content for hashing based on cell source and outputs.")
        
        if 'cells' not in notebook_content or not isinstance(notebook_content['cells'], list):
            logger.warning("NotebookService: 'cells' key not found or not a list. Hashing the entire content as a fallback.")
            return notebook_content

        essential_content = []
        for i, cell in enumerate(notebook_content['cells']):
            if not isinstance(cell, dict):
                logger.warning(f"NotebookService: Item at cell index {i} is not a dictionary, skipping.")
                continue

            cell_data = {}

            # 1. Add the cell's source code
            cell_data['source'] = cell.get('source', '')

            # 2. Add the cell's outputs, normalizing volatile parts
            outputs = cell.get('outputs', [])
            if outputs and isinstance(outputs, list):
                # Create a deep copy to avoid modifying the original notebook object
                import copy
                cleaned_outputs = copy.deepcopy(outputs)
                
                for output in cleaned_outputs:
                    if not isinstance(output, dict):
                        continue
                    # Normalize execution_count as it's highly volatile
                    if 'execution_count' in output:
                        output['execution_count'] = None
                    # Remove transient metadata that can change between sessions
                    if 'transient' in output:
                        del output['transient']
                    if 'metadata' in output:
                        # Clear output metadata as it can contain session-specific info
                        output['metadata'] = {}
                
                cell_data['outputs'] = cleaned_outputs
            else:
                cell_data['outputs'] = []
            
            essential_content.append(cell_data)
            
        logger.info(f"NotebookService: Prepared essential content from {len(essential_content)} cells for hashing.")
        return essential_content
    
    def get_signature_metadata(self, notebook_content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get signature metadata from notebook.
        
        Args:
            notebook_content: Notebook content as dictionary
            
        Returns:
            Signature metadata dictionary, or None if not found
        """
        try:
            metadata = notebook_content.get('metadata', {})
            return metadata.get('git_lock_sign')
        except Exception as e:
            logger.error(f"Error getting signature metadata: {str(e)}")
            return None
    
    def save_signature_metadata(
        self, 
        notebook_path: str, 
        notebook_content: Dict[str, Any], 
        signature_metadata: Dict[str, Any]
    ) -> bool:
        """
        Save signature metadata to notebook file.
        
        Args:
            notebook_path: Path to notebook file
            notebook_content: Current notebook content
            signature_metadata: Signature metadata to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create a copy of notebook content
            import copy
            updated_content = copy.deepcopy(notebook_content)
            
            # Ensure metadata section exists
            if 'metadata' not in updated_content:
                updated_content['metadata'] = {}
            
            # Add signature metadata
            updated_content['metadata']['git_lock_sign'] = signature_metadata
            
            # Save the updated notebook
            self._save_notebook_file(notebook_path, updated_content)
            
            logger.info(f"Signature metadata saved to {notebook_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving signature metadata: {str(e)}")
            return False
    
    def remove_signature_metadata(
        self, 
        notebook_path: str, 
        notebook_content: Dict[str, Any]
    ) -> bool:
        """
        Remove signature metadata from notebook file.
        
        Args:
            notebook_path: Path to notebook file
            notebook_content: Current notebook content
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create a copy of notebook content
            import copy
            updated_content = copy.deepcopy(notebook_content)
            
            # Remove signature metadata if it exists
            if 'metadata' in updated_content:
                if 'git_lock_sign' in updated_content['metadata']:
                    del updated_content['metadata']['git_lock_sign']
            
            # Save the updated notebook
            self._save_notebook_file(notebook_path, updated_content)
            
            logger.info(f"Signature metadata removed from {notebook_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing signature metadata: {str(e)}")
            return False
    
    def _save_notebook_file(self, notebook_path: str, notebook_content: Dict[str, Any]):
        """
        Save notebook content to file.
        
        Args:
            notebook_path: Path to notebook file
            notebook_content: Notebook content to save
        """
        try:
            # Ensure the path is properly formatted
            if not notebook_path.endswith('.ipynb'):
                notebook_path += '.ipynb'
            
            # Convert to absolute path to ensure we can write to it
            abs_path = os.path.abspath(notebook_path)
            
            # Ensure the directory exists
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            
            # Write notebook content as JSON
            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(notebook_content, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Successfully saved notebook to: {abs_path}")
            
        except PermissionError as e:
            logger.error(f"Permission denied saving notebook file: {str(e)}")
            raise Exception(f"Permission denied: Cannot write to {notebook_path}")
        except OSError as e:
            logger.error(f"OS error saving notebook file: {str(e)}")
            raise Exception(f"File system error: {str(e)}")
        except Exception as e:
            logger.error(f"Error saving notebook file: {str(e)}")
            raise Exception(f"Failed to save notebook file: {str(e)}")
    
    def get_current_timestamp(self) -> str:
        """
        Get current timestamp in ISO format.
        
        Returns:
            Current timestamp as ISO format string
        """
        return datetime.utcnow().isoformat() + 'Z'
    
    def validate_notebook_content(self, notebook_content: Any) -> bool:
        """
        Validate that content is a valid notebook structure.
        
        Args:
            notebook_content: Content to validate
            
        Returns:
            True if valid notebook structure, False otherwise
        """
        try:
            if not isinstance(notebook_content, dict):
                return False
            
            # Check for required notebook fields
            required_fields = ['cells', 'metadata', 'nbformat', 'nbformat_minor']
            for field in required_fields:
                if field not in notebook_content:
                    return False
            
            # Check that cells is a list
            if not isinstance(notebook_content['cells'], list):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating notebook content: {str(e)}")
            return False
    
    def is_notebook_locked(self, notebook_content: Dict[str, Any]) -> bool:
        """
        Check if notebook is currently locked.
        
        Args:
            notebook_content: Notebook content to check
            
        Returns:
            True if locked, False otherwise
        """
        try:
            signature_metadata = self.get_signature_metadata(notebook_content)
            if not signature_metadata:
                return False
            
            return signature_metadata.get('locked', False)
            
        except Exception as e:
            logger.error(f"Error checking lock status: {str(e)}")
            return False
    
    def save_notebook_content(self, notebook_path: str, notebook_content: Dict[str, Any]) -> bool:
        """
        Save notebook content to file without modifying metadata.
        
        Args:
            notebook_path: Path to notebook file
            notebook_content: Notebook content to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self._save_notebook_file(notebook_path, notebook_content)
            logger.info(f"Notebook content saved to {notebook_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving notebook content: {str(e)}")
            return False

    def get_signature_info(self, notebook_content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get signature information for display purposes.
        
        Args:
            notebook_content: Notebook content
            
        Returns:
            Dictionary with signature info, or None if not signed
        """
        try:
            signature_metadata = self.get_signature_metadata(notebook_content)
            if not signature_metadata:
                return None
            
            return {
                'locked': signature_metadata.get('locked', False),
                'user_name': signature_metadata.get('user_name'),
                'user_email': signature_metadata.get('user_email'),
                'timestamp': signature_metadata.get('timestamp'),
                'has_signature': bool(signature_metadata.get('signature'))
            }
            
        except Exception as e:
            logger.error(f"Error getting signature info: {str(e)}")
            return None
