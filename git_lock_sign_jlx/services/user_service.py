"""
Service for extracting git user information.
"""
import os
import logging
import subprocess
from typing import Dict, Optional, Any

import git
from git.exc import GitCommandError, InvalidGitRepositoryError
from git.config import GitConfigParser
from git_lock_sign_jlx.logger_util import default_logger_config

logger = logging.getLogger(__name__)
default_logger_config(logger)

class UserService:
    """Service for managing git user information."""
    
    def __init__(self):
        """Initialize the user service."""
        self._cached_user_info = None
    
    def get_user_info(self) -> Optional[Dict[str, str]]:
        """
        Get git user name and email from git configuration.
        
        Returns:
            Dictionary with 'name' and 'email' keys, or None if not configured.
        """
        if self._cached_user_info:
            return self._cached_user_info
        
        try:
            # Try to get user info using direct git commands
            user_info = self._get_git_config_direct()
            
            if user_info:
                self._cached_user_info = user_info
                return user_info
            
            logger.warning("Git user configuration not found")
            return None
            
        except Exception as e:
            logger.error(f"Error getting git user info: {str(e)}")
            return None
    
    def _get_git_config_direct(self) -> Optional[Dict[str, str]]:
        """Get user info using direct git config commands."""
        try:
            # Use subprocess to call git config directly
            name_result = subprocess.run(
                ['git', 'config', 'user.name'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            email_result = subprocess.run(
                ['git', 'config', 'user.email'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if name_result.returncode == 0 and email_result.returncode == 0:
                name = name_result.stdout.strip()
                email = email_result.stdout.strip()
                
                if name and email:
                    logger.info(f"Found git user config: {name} <{email}>")
                    return {
                        'name': name,
                        'email': email
                    }
            
            # If direct config fails, try global config explicitly
            name_result = subprocess.run(
                ['git', 'config', '--global', 'user.name'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            email_result = subprocess.run(
                ['git', 'config', '--global', 'user.email'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if name_result.returncode == 0 and email_result.returncode == 0:
                name = name_result.stdout.strip()
                email = email_result.stdout.strip()
                
                if name and email:
                    logger.info(f"Found global git user config: {name} <{email}>")
                    return {
                        'name': name,
                        'email': email
                    }
            
            logger.warning("Git user.name and user.email not configured")
            return None
            
        except subprocess.TimeoutExpired:
            logger.error("Git config command timed out")
            return None
        except FileNotFoundError:
            logger.error("Git command not found")
            return None
        except Exception as e:
            logger.error(f"Error executing git config: {str(e)}")
            return None
    def _get_global_git_config(self) -> Optional[Dict[str, Any]]:
        """Get user info from global git configuration (legacy method)."""
        try:
            # Use GitPython to read global config
            global_config_path = os.path.normpath(os.path.expanduser("~/.gitconfig"))
            config_reader = git.GitConfigParser([global_config_path], read_only=True)

            name = config_reader.get_value('user', 'name', default=None)
            email = config_reader.get_value('user', 'email', default=None)

            if name and email:
                return {
                    'name': name,
                    'email': email
                }
            
            return None
            
        except Exception as e:
            logger.debug(f"Could not read global git config: {str(e)}")
            return None
    
    def _get_local_git_config(self) -> Optional[Dict[str, Any]]:
        """Get user info from local repository git configuration (legacy method)."""
        try:
            # Try to find a git repository in current working directory or parent directories
            repo = git.Repo(search_parent_directories=True)
            
            # Get user info from repository config
            config_reader = repo.config_reader()
            
            name = config_reader.get_value('user', 'name', default=None)
            email = config_reader.get_value('user', 'email', default=None)
            
            if name and email:
                return {
                    'name': name,
                    'email': email
                }
            
            return None
            
        except (InvalidGitRepositoryError, GitCommandError) as e:
            logger.debug(f"Could not read local git config: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error reading local git config: {str(e)}")
            return None
    
    def clear_cache(self):
        """Clear cached user info to force refresh."""
        self._cached_user_info = None
    
    def validate_user_info(self, user_info: Dict[str, str]) -> bool:
        """
        Validate user info format.
        
        Args:
            user_info: Dictionary with user information
            
        Returns:
            True if valid, False otherwise
        """
        if not isinstance(user_info, dict):
            return False
        
        required_keys = ['name', 'email']
        for key in required_keys:
            if key not in user_info or not user_info[key]:
                return False
        
        # Basic email validation
        email = user_info['email']
        if '@' not in email or '.' not in email.split('@')[-1]:
            return False
        
        return True
