"""
Tornado request handlers for git-based notebook locking and signing.
"""

import json
import logging
import os
from typing import Any, Dict

from jupyter_server.base.handlers import APIHandler
from tornado.web import HTTPError

from .services.git_service import GitService
from .services.gpg_service import GPGService
from .services.notebook_service import NotebookService
from .services.user_service import UserService


logger = logging.getLogger(__name__)


class BaseGitLockSignHandler(APIHandler):
    """Base handler for git lock sign operations."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.git_service = GitService()
        self.gpg_service = GPGService()
        self.notebook_service = NotebookService()
        self.user_service = UserService()
    
    def write_json(self, data: Dict[str, Any]):
        """Write JSON response."""
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(data))
    
    def write_error_json(self, status_code: int, message: str):
        """Write JSON error response."""
        self.set_status(status_code)
        self.write_json({"error": message})


class LockNotebookHandler(BaseGitLockSignHandler):
    """Handler for locking and signing notebooks with git commits."""
    
    async def post(self):
        """Lock and sign a notebook using git commit signing."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode('utf-8'))
            notebook_path = data.get('notebook_path')
            notebook_content = data.get('notebook_content')
            commit_message = data.get('commit_message')
            
            if not notebook_path or not notebook_content:
                self.write_error_json(400, "Missing notebook_path or notebook_content")
                return
            
            if not commit_message:
                self.write_error_json(400, "Missing commit_message for lock operation")
                return
            
            # Convert relative path to absolute path
            abs_notebook_path = os.path.abspath(notebook_path)
            
            # Check if file is in a git repository
            if not self.git_service.is_git_repository(abs_notebook_path):
                self.write_error_json(400, "Notebook is not in a git repository. Please initialize git repository first.")
                return
            
            # Get user info
            user_info = self.user_service.get_user_info()
            if not user_info:
                self.write_error_json(400, "Git user configuration not found. Please configure git user.name and user.email")
                return
            
            # Commit the notebook with git (frontend already saved the file with metadata)
            logger.info("LockNotebookHandler: Calling git_service.commit_and_sign_file()...")
            logger.info(f"LockNotebookHandler: Parameters - file: {abs_notebook_path}, message: {commit_message}")
            
            commit_success, commit_hash, commit_error = self.git_service.commit_and_sign_file(
                abs_notebook_path,
                commit_message
            )
            
            logger.info(f"LockNotebookHandler: Git service returned - success: {commit_success}, hash: {commit_hash}, error: {commit_error}")
            
            if not commit_success:
                logger.error(f"LockNotebookHandler: Git commit failed: {commit_error}")
                self.write_error_json(500, f"Failed to commit notebook: {commit_error}")
                return
            
            # Get commit information
            logger.info("LockNotebookHandler: Getting commit information...")
            commit_info = self.git_service.get_commit_info(abs_notebook_path, commit_hash)
            if not commit_info:
                logger.error("LockNotebookHandler: Failed to get commit information")
                self.write_error_json(500, "Failed to get commit information")
                return
            
            # Generate content hash for additional verification
            content_hash = self.notebook_service.generate_content_hash(notebook_content)
            
            # Check if commit is actually signed
            is_signed = commit_info.get('signed', False)
            
            # Create signature metadata with git commit information (for response only)
            signature_metadata = {
                "locked": True,
                "commit_hash": commit_hash,
                "commit_signed": is_signed,
                "user_name": commit_info.get('author_name', user_info["name"]),
                "user_email": commit_info.get('author_email', user_info["email"]),
                "timestamp": commit_info.get('timestamp', self.notebook_service.get_current_timestamp()),
                "content_hash": content_hash,
                "commit_message": commit_info.get('message', ''),
                "gpg_available": is_signed  # Track if GPG was available during lock
            }
            
            # Log signing status
            if is_signed:
                logger.info(f"Notebook locked with GPG signature: {notebook_path}")
            else:
                logger.warning(f"Notebook locked without GPG signature (GPG may not be available): {notebook_path}")
            
            # Update the notebook file with the actual commit information and amend the commit
            logger.info("LockNotebookHandler: Updating notebook metadata with actual commit info...")
            success = self.notebook_service.save_signature_metadata(
                notebook_path, notebook_content, signature_metadata
            )
            
            if not success:
                logger.warning("LockNotebookHandler: Failed to update metadata in notebook file, but lock succeeded")
                # Don't fail the entire operation, just warn
            else:
                logger.info("LockNotebookHandler: Successfully updated notebook metadata with commit info")
                
                # Amend the commit to include the updated metadata
                logger.info("LockNotebookHandler: Amending commit to include updated metadata...")
                amend_success, new_commit_hash, amend_error = self.git_service.amend_commit_with_file(
                    abs_notebook_path, commit_message
                )
                
                if amend_success and new_commit_hash:
                    logger.info(f"LockNotebookHandler: Successfully amended commit: {new_commit_hash}")
                    # Update the commit hash in our response
                    commit_hash = new_commit_hash
                    signature_metadata["commit_hash"] = new_commit_hash
                    
                    # Re-check if the amended commit is signed
                    updated_commit_info = self.git_service.get_commit_info(abs_notebook_path, new_commit_hash)
                    if updated_commit_info:
                        is_signed = updated_commit_info.get('signed', False)
                        signature_metadata["commit_signed"] = is_signed
                        logger.info(f"LockNotebookHandler: Amended commit signed status: {is_signed}")
                else:
                    logger.warning(f"LockNotebookHandler: Failed to amend commit: {amend_error}")
                    # Continue with original commit, don't fail the operation
            
            logger.info(f"Lock operation completed successfully for: {notebook_path}")
            
            self.write_json({
                "success": True,
                "message": "Notebook locked and signed with git commit successfully",
                "metadata": signature_metadata,
                "commit_hash": commit_hash,
                "signed": is_signed
            })
                
        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error(f"Error locking notebook: {str(e)}")
            self.write_error_json(500, f"Internal server error: {str(e)}")


class UnlockNotebookHandler(BaseGitLockSignHandler):
    """Handler for unlocking notebooks after git commit signature verification."""
    
    async def post(self):
        """Unlock a notebook after verifying git commit signature."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode('utf-8'))
            notebook_path = data.get('notebook_path')
            notebook_content = data.get('notebook_content')
            
            if not notebook_path or not notebook_content:
                self.write_error_json(400, "Missing notebook_path or notebook_content")
                return
            
            # Convert relative path to absolute path
            abs_notebook_path = os.path.abspath(notebook_path)
            
            # Check if file is in a git repository
            if not self.git_service.is_git_repository(abs_notebook_path):
                self.write_error_json(400, "Notebook is not in a git repository")
                return
            
            # Get existing signature metadata
            signature_metadata = self.notebook_service.get_signature_metadata(notebook_content)
            if not signature_metadata:
                self.write_error_json(400, "No signature found in notebook")
                return
            
            # Get commit hash from metadata
            commit_hash = signature_metadata.get('commit_hash')
            if not commit_hash:
                self.write_error_json(400, "No git commit hash found in signature metadata")
                return
            
            # Check if the notebook was originally signed with GPG
            was_gpg_signed = signature_metadata.get('commit_signed', False)
            
            # Verify content integrity first
            current_hash = self.notebook_service.generate_content_hash(notebook_content)
            stored_hash = signature_metadata.get('content_hash')
            
            if current_hash != stored_hash:
                self.write_error_json(400, "Content has been modified since locking. Cannot unlock.")
                return
            
            # If the notebook was GPG signed, try to verify the signature
            signature_verification_passed = True
            unlock_message = "Notebook unlocked successfully"
            
            if was_gpg_signed:
                signature_valid, verify_error = self.git_service.verify_commit_signature(
                    abs_notebook_path, commit_hash
                )
                
                if signature_valid:
                    unlock_message = "Notebook unlocked successfully after GPG signature verification"
                    logger.info(f"GPG signature verified for unlock: {notebook_path}")
                else:
                    # GPG verification failed, but allow unlock with warning
                    logger.warning(f"GPG signature verification failed but allowing unlock: {verify_error}")
                    unlock_message = f"Notebook unlocked with warning: GPG signature verification failed ({verify_error})"
                    signature_verification_passed = False
            else:
                # Notebook was not GPG signed originally, just verify git commit exists
                commit_info = self.git_service.get_commit_info(abs_notebook_path, commit_hash)
                if commit_info:
                    unlock_message = "Notebook unlocked successfully (was not GPG signed)"
                    logger.info(f"Unlocking notebook that was not GPG signed: {notebook_path}")
                else:
                    self.write_error_json(400, f"Git commit {commit_hash} not found in repository")
                    return
            
            # Remove signature metadata and unlock
            success = self.notebook_service.remove_signature_metadata(notebook_path, notebook_content)
            
            if success:
                self.write_json({
                    "success": True,
                    "message": unlock_message,
                    "signature_verification_passed": signature_verification_passed,
                    "was_gpg_signed": was_gpg_signed
                })
            else:
                self.write_error_json(500, "Failed to remove signature metadata from notebook")
                
        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error(f"Error unlocking notebook: {str(e)}")
            self.write_error_json(500, f"Internal server error: {str(e)}")


class UserInfoHandler(BaseGitLockSignHandler):
    """Handler for getting git user information."""
    
    async def get(self):
        """Get git user name and email."""
        try:
            user_info = self.user_service.get_user_info()
            
            if user_info:
                self.write_json({
                    "success": True,
                    "user_info": user_info
                })
            else:
                self.write_json({
                    "success": False,
                    "message": "Git user configuration not found"
                })
                
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            self.write_error_json(500, f"Internal server error: {str(e)}")


class NotebookStatusHandler(BaseGitLockSignHandler):
    """Handler for checking notebook lock status and git commit signature."""
    
    async def post(self):
        """Check if notebook is locked and git commit signature is valid."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode('utf-8'))
            notebook_content = data.get('notebook_content')
            notebook_path = data.get('notebook_path', '')
            
            if not notebook_content:
                self.write_error_json(400, "Missing notebook_content")
                return
            
            # Get signature metadata
            signature_metadata = self.notebook_service.get_signature_metadata(notebook_content)
            
            if not signature_metadata:
                self.write_json({
                    "success": True,
                    "locked": False,
                    "signature_valid": False,
                    "message": "No signature found"
                })
                return
            
            # Check if locked
            is_locked = signature_metadata.get('locked', False)
            
            if not is_locked:
                self.write_json({
                    "success": True,
                    "locked": False,
                    "signature_valid": False,
                    "message": "Notebook is not locked"
                })
                return
            
            # If we have a notebook path, verify git commit signature
            signature_valid = False
            message = "Locked but signature verification skipped (no path provided)"
            
            if notebook_path:
                abs_notebook_path = os.path.abspath(notebook_path)
                
                if self.git_service.is_git_repository(abs_notebook_path):
                    commit_hash = signature_metadata.get('commit_hash')
                    if commit_hash:
                        signature_valid, verify_error = self.git_service.verify_commit_signature(
                            abs_notebook_path, commit_hash
                        )
                        message = "Git commit signature verified" if signature_valid else f"Git signature verification failed: {verify_error}"
                    else:
                        message = "No git commit hash found in metadata"
                else:
                    message = "Not in a git repository"
            
            # Verify content integrity
            current_hash = self.notebook_service.generate_content_hash(notebook_content)
            stored_hash = signature_metadata.get('content_hash')
            
            if current_hash != stored_hash:
                message += " (Content has been modified since signing)"
                signature_valid = False
            
            self.write_json({
                "success": True,
                "locked": True,
                "signature_valid": signature_valid,
                "message": message,
                "metadata": signature_metadata
            })
            
        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error(f"Error checking notebook status: {str(e)}")
            self.write_error_json(500, f"Internal server error: {str(e)}")


class CommitNotebookHandler(BaseGitLockSignHandler):
    """Handler for staging and committing notebook changes."""
    
    async def post(self):
        """Stage and commit notebook changes to git."""
        try:
            logger.info("=== CommitNotebookHandler: Starting commit process ===")
            
            # Get request data
            data = json.loads(self.request.body.decode('utf-8'))
            notebook_path = data.get('notebook_path')
            notebook_content = data.get('notebook_content')
            commit_message = data.get('commit_message')
            
            logger.info(f"CommitNotebookHandler: Received request for notebook: {notebook_path}")
            logger.info(f"CommitNotebookHandler: Commit message: {commit_message}")
            
            if not notebook_path or not notebook_content or not commit_message:
                logger.error("CommitNotebookHandler: Missing required parameters")
                self.write_error_json(400, "Missing notebook_path, notebook_content, or commit_message")
                return
            
            # Convert relative path to absolute path
            abs_notebook_path = os.path.abspath(notebook_path)
            logger.info(f"CommitNotebookHandler: Absolute path: {abs_notebook_path}")
            
            # Check if file exists
            if not os.path.exists(abs_notebook_path):
                logger.error(f"CommitNotebookHandler: File does not exist: {abs_notebook_path}")
                self.write_error_json(400, f"File does not exist: {abs_notebook_path}")
                return
            
            # Check if file is in a git repository
            logger.info("CommitNotebookHandler: Checking if file is in git repository...")
            if not self.git_service.is_git_repository(abs_notebook_path):
                logger.error(f"CommitNotebookHandler: Not in git repository: {abs_notebook_path}")
                self.write_error_json(400, "Notebook is not in a git repository. Please initialize git repository first.")
                return
            logger.info("CommitNotebookHandler: File is in git repository ✓")
            
            # Get user info
            logger.info("CommitNotebookHandler: Getting git user info...")
            user_info = self.user_service.get_user_info()
            if not user_info:
                logger.error("CommitNotebookHandler: No git user configuration found")
                self.write_error_json(400, "Git user configuration not found. Please configure git user.name and user.email")
                return
            logger.info(f"CommitNotebookHandler: Git user: {user_info['name']} <{user_info['email']}>")
            
            # Commit the file with git (notebook already contains metadata from frontend)
            logger.info("CommitNotebookHandler: Calling git_service.commit_and_sign_file()...")
            logger.info(f"CommitNotebookHandler: Parameters - file: {abs_notebook_path}, message: {commit_message}")
            
            commit_success, commit_hash, commit_error = self.git_service.commit_and_sign_file(
                abs_notebook_path,
                commit_message
            )
            
            logger.info(f"CommitNotebookHandler: Git service returned - success: {commit_success}, hash: {commit_hash}, error: {commit_error}")
            
            if not commit_success:
                logger.error(f"CommitNotebookHandler: Git commit failed: {commit_error}")
                self.write_error_json(500, f"Failed to commit notebook: {commit_error}")
                return
            
            # Get commit information
            logger.info("CommitNotebookHandler: Getting commit information...")
            commit_info = self.git_service.get_commit_info(abs_notebook_path, commit_hash)
            if not commit_info:
                logger.error("CommitNotebookHandler: Failed to get commit information")
                self.write_error_json(500, "Failed to get commit information")
                return
            
            # Check if commit is actually signed
            is_signed = commit_info.get('signed', False)
            
            # Generate content hash for additional verification
            content_hash = self.notebook_service.generate_content_hash(notebook_content)
            
            # Create updated metadata with actual commit information
            updated_metadata = {
                'commit_hash': commit_hash,
                'commit_signed': is_signed,
                'user_name': commit_info.get('author_name', user_info["name"]),
                'user_email': commit_info.get('author_email', user_info["email"]),
                'timestamp': commit_info.get('timestamp', self.notebook_service.get_current_timestamp()),
                'content_hash': content_hash,
                'commit_message': commit_info.get('message', ''),
            }
            
            # If notebook already has git_lock_sign metadata, preserve other fields
            if 'metadata' in notebook_content and 'git_lock_sign' in notebook_content['metadata']:
                existing_metadata = notebook_content['metadata']['git_lock_sign'].copy()
                existing_metadata.update(updated_metadata)
                updated_metadata = existing_metadata
            
            # Update the notebook file with the actual commit information and amend the commit
            logger.info("CommitNotebookHandler: Updating notebook metadata with actual commit info...")
            success = self.notebook_service.save_signature_metadata(
                notebook_path, notebook_content, updated_metadata
            )
            
            if not success:
                logger.warning("CommitNotebookHandler: Failed to update metadata in notebook file, but commit succeeded")
                # Don't fail the entire operation, just warn
            else:
                logger.info("CommitNotebookHandler: Successfully updated notebook metadata with commit info")
                
                # Amend the commit to include the updated metadata
                logger.info("CommitNotebookHandler: Amending commit to include updated metadata...")
                amend_success, new_commit_hash, amend_error = self.git_service.amend_commit_with_file(
                    abs_notebook_path, commit_message
                )
                
                if amend_success and new_commit_hash:
                    logger.info(f"CommitNotebookHandler: Successfully amended commit: {new_commit_hash}")
                    # Update the commit hash in our response
                    commit_hash = new_commit_hash
                    updated_metadata["commit_hash"] = new_commit_hash
                    
                    # Re-check if the amended commit is signed
                    updated_commit_info = self.git_service.get_commit_info(abs_notebook_path, new_commit_hash)
                    if updated_commit_info:
                        is_signed = updated_commit_info.get('signed', False)
                        updated_metadata["commit_signed"] = is_signed
                        logger.info(f"CommitNotebookHandler: Amended commit signed status: {is_signed}")
                else:
                    logger.warning(f"CommitNotebookHandler: Failed to amend commit: {amend_error}")
                    # Continue with original commit, don't fail the operation
            
            logger.info(f"CommitNotebookHandler: SUCCESS - Notebook committed: {notebook_path}, commit: {commit_hash}, signed: {is_signed}")
            
            self.write_json({
                "success": True,
                "message": f"Notebook committed successfully {'with GPG signature' if is_signed else 'without GPG signature'}",
                "commit_hash": commit_hash,
                "signed": is_signed
            })
                
        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error(f"Error committing notebook: {str(e)}")
            self.write_error_json(500, f"Internal server error: {str(e)}")


class GitRepositoryStatusHandler(BaseGitLockSignHandler):
    """Handler for getting git repository status information."""
    
    async def post(self):
        """Get git repository status for a notebook path."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode('utf-8'))
            notebook_path = data.get('notebook_path')
            
            if not notebook_path:
                self.write_error_json(400, "Missing notebook_path")
                return
            
            abs_notebook_path = os.path.abspath(notebook_path)
            repo_status = self.git_service.get_repository_status(abs_notebook_path)
            
            self.write_json({
                "success": True,
                "repository_status": repo_status
            })
            
        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error(f"Error getting repository status: {str(e)}")
            self.write_error_json(500, f"Internal server error: {str(e)}")
