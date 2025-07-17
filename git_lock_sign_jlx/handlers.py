"""Handlers for git lock and sign JupyterLab extension."""

import json
import logging
import os
from typing import Any, Dict

from jupyter_server.base.handlers import APIHandler

from .logger_util import default_logger_config
from .services.git_service import GitService
from .services.gpg_service import GPGService
from .services.notebook_service import NotebookService
from .services.user_service import UserService

logger = logging.getLogger(__name__)
default_logger_config(logger)


class BaseGitLockSignHandler(APIHandler):
    """Base handler for git lock sign operations."""

    def __init__(self, *args, **kwargs):
        """Initialize the base handler."""
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

    def data_received(self, chunk):
        """Handle data received."""


class LockNotebookHandler(BaseGitLockSignHandler):
    """Handler for locking and signing notebooks with git commits."""

    async def post(self):
        """Lock and sign a notebook using git commit signing."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode("utf-8"))
            notebook_path = data.get("notebook_path")
            notebook_content = data.get("notebook_content")
            commit_message = data.get("commit_message")

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
                self.write_error_json(
                    400,
                    (
                        "Notebook is not in a git repository. Please initialize "
                        "git repository first."
                    ),
                )
                return

            # Get user info
            user_info = self.user_service.get_user_info()
            if not user_info:
                self.write_error_json(
                    400,
                    (
                        "Git user configuration not found. Please configure git "
                        "user.name and user.email"
                    ),
                )
                return

            # MANDATORY GPG VALIDATION: Pre-lock GPG requirements check
            logger.info("LockNotebookHandler: ===== MANDATORY GPG VALIDATION =====")
            logger.info(
                "LockNotebookHandler: Validating GPG requirements before locking..."
            )

            # Step 1: Check if GPG is available
            if not self.gpg_service.is_gpg_available():
                logger.error(
                    "LockNotebookHandler: ❌ GPG not available - locking "
                    "requires GPG signatures"
                )
                self.write_error_json(
                    400,
                    (
                        "Cannot lock notebook: GPG is required for locking but "
                        "not available. Please ensure GPG is installed and "
                        "configured."
                    ),
                )
                return

            # Step 2: Check if user has signing keys
            if not self.gpg_service.has_signing_key():
                logger.error(
                    "LockNotebookHandler: ❌ No GPG signing keys available - "
                    "locking requires GPG signatures"
                )
                self.write_error_json(
                    400,
                    (
                        "Cannot lock notebook: No GPG signing keys available. "
                        "Please ensure you have a GPG key configured for "
                        "signing."
                    ),
                )
                return

            # Step 3: Check if git signing key is configured
            configured_key = self.gpg_service.get_configured_signing_key()
            if not configured_key:
                logger.error(
                    "LockNotebookHandler: ❌ No git signing key configured - "
                    "locking requires GPG signatures"
                )
                self.write_error_json(
                    400,
                    "Cannot lock notebook: No git signing key configured. "
                    "Please configure a GPG key with: git config "
                    "user.signingkey [YOUR_KEY_ID]",
                )
                return

            logger.info(
                "LockNotebookHandler: Found configured signing key: %s",
                configured_key,
            )

            # Step 4: Test actual signing capability with the configured key
            if not self.gpg_service.can_sign_with_key(configured_key):
                logger.error(
                    "LockNotebookHandler: ❌ Cannot sign with configured GPG "
                    "key - locking requires GPG signatures"
                )
                self.write_error_json(
                    400,
                    (
                        "Cannot lock notebook: Cannot sign with configured GPG "
                        "key. Please ensure you have access to the private key "
                        "for signing."
                    ),
                )
                return

            logger.info(
                "LockNotebookHandler: ✅ GPG validation passed - proceeding "
                "with mandatory signed lock"
            )

            # Step 1: Calculate content hash from the original notebook content.
            # This hash represents the state of the notebook's core content.
            logger.info(
                "LockNotebookHandler: Step 1: Calculating content hash from "
                "original content..."
            )
            content_hash = self.notebook_service.generate_content_hash(notebook_content)
            logger.info("LockNotebookHandler: Original content hash: %s", content_hash)

            # Step 2: Save the notebook content as-is to ensure the file is in a clean
            # state for the first commit.
            logger.info(
                "LockNotebookHandler: Step 2: Saving notebook to disk before "
                "initial commit..."
            )
            save_success = self.notebook_service.save_notebook_content(
                abs_notebook_path, notebook_content
            )
            if not save_success:
                self.write_error_json(
                    500,
                    "Failed to save notebook before committing.",
                )
                return
            logger.info("LockNotebookHandler: Notebook saved successfully.")

            # Step 3: Commit the clean notebook file. This creates the commit that
            # locks the core content.
            logger.info("LockNotebookHandler: Step 3: Creating initial git commit...")
            (
                commit_success,
                commit_hash,
                commit_error,
            ) = self.git_service.commit_and_sign_file(abs_notebook_path, commit_message)
            if not commit_success or not commit_hash:
                logger.error(
                    "LockNotebookHandler: Initial git commit failed: %s",
                    commit_error,
                )
                self.write_error_json(
                    500,
                    f"Failed to commit notebook: {commit_error}",
                )
                return
            logger.info(
                "LockNotebookHandler: Initial commit successful. Hash: %s",
                commit_hash,
            )

            # Step 4: Get the information from the commit we just created.
            logger.info("LockNotebookHandler: Step 4: Getting commit information...")
            commit_info = self.git_service.get_commit_info(
                abs_notebook_path, commit_hash
            )
            if not commit_info:
                logger.error(
                    "LockNotebookHandler: Failed to get commit information "
                    "after commit."
                )
                self.write_error_json(
                    500,
                    "Failed to get commit information.",
                )
                return
            is_signed = commit_info.get("signed", False)
            logger.info(
                "LockNotebookHandler: Commit info retrieved. Signed: %s",
                is_signed,
            )

            # MANDATORY GPG SIGNATURE ENFORCEMENT: Verify commit was actually signed
            logger.info(
                "LockNotebookHandler: ===== POST-COMMIT GPG SIGNATURE "
                "VERIFICATION ====="
            )
            if not is_signed:
                logger.error(
                    "LockNotebookHandler: ❌ CRITICAL: "
                    "Commit was created but NOT signed - rolling back!"
                )
                logger.error(
                    "LockNotebookHandler: Locking requires GPG signatures "
                    "but commit lacks signature"
                )

                # Rollback the commit since it doesn't meet our requirements
                logger.info(
                    "LockNotebookHandler: Attempting to rollback unsigned commit..."
                )
                (
                    rollback_success,
                    rollback_error,
                ) = self.git_service.rollback_last_commit(abs_notebook_path)

                if rollback_success:
                    logger.info(
                        "LockNotebookHandler: ✅ Successfully rolled back "
                        "unsigned commit"
                    )
                    self.write_error_json(
                        400,
                        (
                            "Cannot lock notebook: GPG signature is required "
                            "but the commit was not signed. Please ensure your "
                            "GPG key is properly configured and accessible. The "
                            "unsigned commit has been rolled back."
                        ),
                    )
                else:
                    logger.error(
                        "LockNotebookHandler: ❌ Failed to rollback unsigned "
                        "commit: %s",
                        rollback_error,
                    )
                    self.write_error_json(
                        500,
                        (
                            "CRITICAL ERROR: Commit was created without "
                            "required GPG signature and rollback failed. "
                            "Manual intervention required. Rollback error: "
                            f"{rollback_error}"
                        ),
                    )
                return

            logger.info(
                "LockNotebookHandler: ✅ POST-COMMIT VERIFICATION PASSED - "
                "Commit is properly signed"
            )

            # Step 5: Create the final, complete signature metadata dictionary.
            logger.info(
                "LockNotebookHandler: Step 5: Creating final signature " "metadata..."
            )
            signature_metadata = {
                "locked": True,
                "commit_hash": commit_hash,
                "commit_signed": is_signed,
                "user_name": commit_info.get("author_name", user_info["name"]),
                "user_email": commit_info.get("author_email", user_info["email"]),
                "timestamp": commit_info.get(
                    "timestamp", self.notebook_service.get_current_timestamp()
                ),
                "content_hash": content_hash,  # The hash of the core content
                "commit_message": commit_info.get("message", ""),
                "gpg_available": is_signed,
            }
            logger.info(
                "LockNotebookHandler: Final metadata created: %s",
                signature_metadata,
            )

            # Step 6: Save the notebook again, this time with the final signature
            # metadata.
            logger.info(
                "LockNotebookHandler: Step 6: Saving notebook with final " "metadata..."
            )
            save_with_meta_success = self.notebook_service.save_signature_metadata(
                abs_notebook_path, notebook_content, signature_metadata
            )
            if not save_with_meta_success:
                logger.error(
                    "LockNotebookHandler: Failed to save notebook with final "
                    "metadata."
                )
                self.write_error_json(
                    500,
                    "Failed to save notebook with signature metadata.",
                )
                return
            logger.info(
                "LockNotebookHandler: Successfully saved notebook with final "
                "metadata."
            )

            # Step 7: Amend the previous commit to include the file with the new
            # metadata.
            # This keeps the repository clean (one commit per lock) and ensures the
            # committed state matches the file on disk.
            logger.info(
                "LockNotebookHandler: Step 7: Amending commit to include " "metadata..."
            )
            (
                amend_success,
                new_commit_hash,
                amend_error,
            ) = self.git_service.amend_commit_with_file(
                abs_notebook_path, commit_message
            )
            if not amend_success or not new_commit_hash:
                logger.warning(
                    "LockNotebookHandler: Failed to amend commit: %s. The file "
                    "is locked but the commit does not contain the signature "
                    "metadata.",
                    amend_error,
                )
                # Don't fail the whole operation, but the state is not ideal.
            else:
                logger.info(
                    "LockNotebookHandler: Successfully amended commit. New " "hash: %s",
                    new_commit_hash,
                )
                # Update metadata for the response
                commit_hash = new_commit_hash
                signature_metadata["commit_hash"] = new_commit_hash

            logger.info("Lock operation completed successfully for: %s", notebook_path)

            self.write_json(
                {
                    "success": True,
                    "message": (
                        "Notebook locked and signed with git commit " "successfully"
                    ),
                    "metadata": signature_metadata,
                    "commit_hash": commit_hash,
                    "signed": is_signed,
                }
            )

        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error("Error locking notebook: %s", str(e))
            self.write_error_json(500, f"Internal server error: {str(e)}")


class UnlockNotebookHandler(BaseGitLockSignHandler):
    """Handler for unlocking notebooks after git commit signature verification."""

    async def post(self):
        """Unlock a notebook after verifying git commit signature."""
        try:
            logger.info("=== UnlockNotebookHandler: Starting unlock process ===")

            # Get request data
            logger.info("UnlockNotebookHandler: Parsing request data...")
            data = json.loads(self.request.body.decode("utf-8"))
            notebook_path = data.get("notebook_path")
            notebook_content = data.get("notebook_content")

            logger.info(
                "UnlockNotebookHandler: Received request for notebook: %s",
                notebook_path,
            )
            logger.info(
                "UnlockNotebookHandler: Notebook content size: %s characters",
                len(str(notebook_content)) if notebook_content else 0,
            )
            logger.info(
                "UnlockNotebookHandler: Notebook content type: %s",
                type(notebook_content),
            )

            if not notebook_path or not notebook_content:
                logger.error("UnlockNotebookHandler: Missing required parameters")
                logger.error(
                    "UnlockNotebookHandler: notebook_path present: %s",
                    bool(notebook_path),
                )
                logger.error(
                    "UnlockNotebookHandler: notebook_content present: %s",
                    bool(notebook_content),
                )
                self.write_error_json(400, "Missing notebook_path or notebook_content")
                return

            # Convert relative path to absolute path
            abs_notebook_path = os.path.abspath(notebook_path)
            logger.info("UnlockNotebookHandler: Absolute path: %s", abs_notebook_path)
            logger.info(
                "UnlockNotebookHandler: File exists: %s",
                os.path.exists(abs_notebook_path),
            )

            # Check if file is in a git repository
            logger.info("UnlockNotebookHandler: Checking git repository status...")
            is_git_repo = self.git_service.is_git_repository(abs_notebook_path)
            logger.info("UnlockNotebookHandler: Is git repository: %s", is_git_repo)

            if not is_git_repo:
                logger.error(
                    "UnlockNotebookHandler: Not in git repository: %s",
                    abs_notebook_path,
                )
                self.write_error_json(400, "Notebook is not in a git repository")
                return

            # Get repository status for debugging
            repo_status = self.git_service.get_repository_status(abs_notebook_path)
            logger.info("UnlockNotebookHandler: Repository status: %s", repo_status)

            # Get existing signature metadata
            logger.info("UnlockNotebookHandler: Extracting signature metadata...")
            logger.info(
                "UnlockNotebookHandler: Notebook has 'metadata' key: %s",
                "metadata" in notebook_content,
            )
            if "metadata" in notebook_content:
                logger.info(
                    "UnlockNotebookHandler: Metadata keys: %s",
                    list(notebook_content["metadata"].keys()),
                )
                logger.info(
                    "UnlockNotebookHandler: Has 'git_lock_sign' metadata: %s",
                    "git_lock_sign" in notebook_content["metadata"],
                )

            signature_metadata = self.notebook_service.get_signature_metadata(
                notebook_content
            )
            logger.info(
                "UnlockNotebookHandler: Signature metadata extracted: %s",
                signature_metadata is not None,
            )

            if not signature_metadata:
                logger.error(
                    "UnlockNotebookHandler: No signature metadata found in notebook"
                )
                self.write_error_json(400, "No signature found in notebook")
                return

            logger.info(
                "UnlockNotebookHandler: Signature metadata contents: %s",
                signature_metadata,
            )

            # Get commit hash from metadata
            commit_hash = signature_metadata.get("commit_hash")
            logger.info(
                "UnlockNotebookHandler: Commit hash from metadata: %s",
                commit_hash,
            )

            if not commit_hash:
                logger.error(
                    "UnlockNotebookHandler: No commit hash found in signature metadata"
                )
                self.write_error_json(
                    400, "No git commit hash found in signature metadata"
                )
                return

            # Check if the notebook was originally signed with GPG
            was_gpg_signed = signature_metadata.get("commit_signed", False)
            logger.info(
                "UnlockNotebookHandler: Notebook was originally GPG signed: %s",
                was_gpg_signed,
            )

            # Log all metadata fields for debugging
            logger.info("UnlockNotebookHandler: All signature metadata fields:")
            for key, value in signature_metadata.items():
                logger.info("  %s: %s", key, value)

            # Verify content integrity first
            logger.info("UnlockNotebookHandler: ===== CONTENT HASH VERIFICATION =====")
            logger.info("UnlockNotebookHandler: Starting content hash verification...")

            # Log notebook structure for debugging
            logger.info("UnlockNotebookHandler: Notebook structure analysis:")
            logger.info(
                "  - Top-level keys: %s",
                list(notebook_content.keys())
                if isinstance(notebook_content, dict)
                else "Not a dict",
            )
            if isinstance(notebook_content, dict) and "cells" in notebook_content:
                logger.info("  - Number of cells: %s", len(notebook_content["cells"]))
            if isinstance(notebook_content, dict) and "metadata" in notebook_content:
                logger.info(
                    "  - Metadata keys: %s",
                    list(notebook_content["metadata"].keys()),
                )
                if "git_lock_sign" in notebook_content["metadata"]:
                    git_metadata = notebook_content["metadata"]["git_lock_sign"]
                    logger.info(
                        "  - git_lock_sign metadata keys: %s",
                        list(git_metadata.keys()),
                    )

            # Calculate current hash
            logger.info("UnlockNotebookHandler: Calculating current content hash...")

            # First, let's examine the content being hashed in detail
            logger.info("UnlockNotebookHandler: Analyzing content for hashing...")

            # Log the content preparation process
            import copy

            content_for_hash = copy.deepcopy(notebook_content)
            logger.info(
                "UnlockNotebookHandler: Original content keys: %s",
                list(content_for_hash.keys()),
            )

            # Remove git_lock_sign metadata like the service does
            if (
                "metadata" in content_for_hash
                and "git_lock_sign" in content_for_hash["metadata"]
            ):
                logger.info(
                    "UnlockNotebookHandler: Removing git_lock_sign metadata "
                    "for hash calculation"
                )
                del content_for_hash["metadata"]["git_lock_sign"]

            # Log remaining metadata
            if "metadata" in content_for_hash:
                logger.info(
                    "UnlockNotebookHandler: Remaining metadata keys: %s",
                    list(content_for_hash["metadata"].keys()),
                )
                for key, value in content_for_hash["metadata"].items():
                    logger.info(
                        "  - %s: %s",
                        key,
                        str(value)[:100] + ("..." if len(str(value)) > 100 else ""),
                    )

            # Log cell information
            if "cells" in content_for_hash:
                logger.info(
                    "UnlockNotebookHandler: Number of cells: %s",
                    len(content_for_hash["cells"]),
                )
                for i, cell in enumerate(
                    content_for_hash["cells"][:3]
                ):  # Log first 3 cells
                    logger.info("UnlockNotebookHandler: Cell %s:", i)
                    logger.info("  - Type: %s", cell.get("cell_type", "unknown"))
                    logger.info("  - Execution count: %s", cell.get("execution_count"))
                    if "metadata" in cell:
                        logger.info(
                            "  - Cell metadata keys: %s",
                            list(cell["metadata"].keys()),
                        )
                    if "source" in cell:
                        source_preview = str(cell["source"])[:100]
                        logger.info(
                            "  - Source preview: %s",
                            source_preview
                            + ("..." if len(str(cell["source"])) > 100 else ""),
                        )

            # Generate the hash
            current_hash = self.notebook_service.generate_content_hash(notebook_content)
            stored_hash = signature_metadata.get("content_hash")

            logger.info("UnlockNotebookHandler: Content hash comparison:")
            logger.info("  - Stored hash:  %s", stored_hash)
            logger.info("  - Current hash: %s", current_hash)
            logger.info("  - Hashes match: %s", current_hash == stored_hash)

            if current_hash != stored_hash:
                logger.warning(
                    "UnlockNotebookHandler: ===== HASH MISMATCH DETECTED ====="
                )
                logger.warning(
                    (
                        "UnlockNotebookHandler: Content hash mismatch - stored: %s, "
                        "current: %s"
                    ),
                    stored_hash,
                    current_hash,
                )
                logger.warning(
                    "UnlockNotebookHandler: This may be due to "
                    "the reload process changing the notebook content"
                )
                logger.warning(
                    "UnlockNotebookHandler: Attempting to recalculate hash "
                    "after removing metadata..."
                )

                # Try to recalculate the hash by temporarily removing the metadata
                import copy

                logger.info(
                    "UnlockNotebookHandler: Creating deep copy of notebook "
                    "content for hash recalculation..."
                )
                temp_content = copy.deepcopy(notebook_content)

                logger.info(
                    "UnlockNotebookHandler: Checking for git_lock_sign "
                    "metadata to remove..."
                )
                metadata_removed = False
                if (
                    "metadata" in temp_content
                    and "git_lock_sign" in temp_content["metadata"]
                ):
                    logger.info(
                        "UnlockNotebookHandler: Removing git_lock_sign "
                        "metadata from temporary content..."
                    )
                    del temp_content["metadata"]["git_lock_sign"]
                    metadata_removed = True
                    logger.info(
                        "UnlockNotebookHandler: git_lock_sign metadata "
                        "removed successfully"
                    )
                else:
                    logger.warning(
                        "UnlockNotebookHandler: No git_lock_sign metadata "
                        "found to remove"
                    )

                logger.info(
                    "UnlockNotebookHandler: Metadata removal performed: %s",
                    metadata_removed,
                )
                logger.info(
                    "UnlockNotebookHandler: Recalculating hash with cleaned "
                    "content..."
                )

                recalc_hash = self.notebook_service.generate_content_hash(temp_content)
                logger.info("UnlockNotebookHandler: Hash recalculation results:")
                logger.info("  - Original stored hash: %s", stored_hash)
                logger.info("  - Hash with metadata:    %s", current_hash)
                logger.info("  - Hash without metadata: %s", recalc_hash)
                logger.info("  - Recalc matches stored: %s", recalc_hash == stored_hash)

                if recalc_hash == stored_hash:
                    logger.info(
                        "UnlockNotebookHandler: ✅ Hash matches after removing "
                        "metadata - proceeding with unlock"
                    )
                    current_hash = recalc_hash  # Use the corrected hash
                else:
                    logger.error(
                        "UnlockNotebookHandler: ❌ Hash still doesn't match "
                        "after recalculation"
                    )
                    logger.error(
                        "UnlockNotebookHandler: This indicates the notebook "
                        "content has been genuinely modified"
                    )
                    logger.error("UnlockNotebookHandler: Expected: %s", stored_hash)
                    logger.error("UnlockNotebookHandler: Got:      %s", recalc_hash)
                    logger.error(
                        "UnlockNotebookHandler: Difference: Content may have "
                        "been modified since locking"
                    )
                    self.write_error_json(
                        400,
                        "Content has been modified since locking. Cannot unlock.",
                    )
                    return
            else:
                logger.info(
                    "UnlockNotebookHandler: ✅ Content hash verification "
                    "passed on first attempt"
                )

            logger.info("UnlockNotebookHandler: ===== SIGNATURE VERIFICATION =====")

            # If the notebook was GPG signed, try to verify the signature
            signature_verification_passed = True
            unlock_message = "Notebook unlocked successfully"

            if was_gpg_signed:
                logger.info(
                    "UnlockNotebookHandler: Notebook was GPG signed, "
                    "verifying signature..."
                )
                logger.info("UnlockNotebookHandler: Verifying commit: %s", commit_hash)

                (
                    signature_valid,
                    verify_error,
                ) = self.git_service.verify_commit_signature(
                    abs_notebook_path, commit_hash
                )

                logger.info(
                    "UnlockNotebookHandler: GPG signature verification results:"
                )
                logger.info("  - Signature valid: %s", signature_valid)
                logger.info("  - Verify error: %s", verify_error)

                if signature_valid:
                    unlock_message = (
                        "Notebook unlocked successfully after GPG signature "
                        "verification"
                    )
                    logger.info(
                        "UnlockNotebookHandler: ✅ GPG signature verified "
                        "for unlock: %s",
                        notebook_path,
                    )
                else:
                    # GPG verification failed, but allow unlock with warning
                    logger.warning(
                        "UnlockNotebookHandler: ⚠️ GPG signature verification "
                        "failed but allowing unlock: %s",
                        verify_error,
                    )
                    unlock_message = (
                        "Notebook unlocked with warning: GPG signature "
                        f"verification failed ({verify_error})"
                    )
                    signature_verification_passed = False
            else:
                logger.info(
                    "UnlockNotebookHandler: Notebook was not GPG signed "
                    "originally, verifying git commit exists..."
                )
                logger.info(
                    "UnlockNotebookHandler: Checking commit info for: %s",
                    commit_hash,
                )

                commit_info = self.git_service.get_commit_info(
                    abs_notebook_path, commit_hash
                )
                logger.info(
                    "UnlockNotebookHandler: Commit info retrieved: %s",
                    commit_info is not None,
                )

                if commit_info:
                    logger.info("UnlockNotebookHandler: Commit info: %s", commit_info)
                    unlock_message = (
                        "Notebook unlocked successfully (was not GPG signed)"
                    )
                    logger.info(
                        "UnlockNotebookHandler: ✅ Unlocking notebook that "
                        "was not GPG signed: %s",
                        notebook_path,
                    )
                else:
                    logger.error(
                        "UnlockNotebookHandler: ❌ Git commit %s not found in "
                        "repository",
                        commit_hash,
                    )
                    self.write_error_json(
                        400, f"Git commit {commit_hash} not " "found in repository"
                    )
                    return

            logger.info(
                "UnlockNotebookHandler: ===== UPDATING METADATA FOR UNLOCK ====="
            )

            logger.info("UnlockNotebookHandler: ===== USER IDENTITY VALIDATION =====")

            # Get current user info to validate against original signer
            unlocking_user = self.user_service.get_user_info()
            if not unlocking_user:
                logger.error(
                    "UnlockNotebookHandler: Could not get current git user "
                    "configuration"
                )
                self.write_error_json(
                    400,
                    "Could not identify unlocking user. "
                    "Please configure git user.name and user.email.",
                )
                return

            logger.info(
                "UnlockNotebookHandler: Current user: %s <%s>",
                unlocking_user["name"],
                unlocking_user["email"],
            )

            # Get original signer information from metadata
            original_user_name = signature_metadata.get("user_name")
            original_user_email = signature_metadata.get("user_email")

            logger.info(
                "UnlockNotebookHandler: Original signer: %s <%s>",
                original_user_name,
                original_user_email,
            )

            # Validate that current user matches original signer
            if (
                unlocking_user["name"] != original_user_name
                or unlocking_user["email"] != original_user_email
            ):
                logger.error(
                    "UnlockNotebookHandler: ❌ User identity mismatch - unlock denied"
                )
                logger.error(
                    "UnlockNotebookHandler: Current user: %s <%s>",
                    unlocking_user["name"],
                    unlocking_user["email"],
                )
                logger.error(
                    "UnlockNotebookHandler: Original signer: %s <%s>",
                    original_user_name,
                    original_user_email,
                )

                self.write_error_json(
                    403,
                    (
                        f"Cannot unlock: Current git user ({unlocking_user['name']} "
                        f"<{unlocking_user['email']}>) does not match "
                        f"original signer ({original_user_name} "
                        f"<{original_user_email}>). Only the original signer can "
                        "unlock this notebook."
                    ),
                )
                return

            logger.info(
                "UnlockNotebookHandler: ✅ User identity validation passed - "
                "current user matches original signer"
            )

            # Additional GPG key validation for GPG-signed notebooks
            if was_gpg_signed:
                logger.info(
                    "UnlockNotebookHandler: ===== ENHANCED GPG KEY VALIDATION ====="
                )
                logger.info(
                    "UnlockNotebookHandler: Notebook was GPG-signed, "
                    "performing comprehensive key validation..."
                )

                # Step 1: Check if current user has GPG configured and available
                if not self.gpg_service.is_gpg_available():
                    logger.error(
                        "UnlockNotebookHandler: ❌ GPG not available for " "current user"
                    )
                    self.write_error_json(
                        403,
                        "Cannot unlock GPG-signed notebook: GPG is not "
                        "available. Please ensure GPG is installed and "
                        "configured.",
                    )
                    return

                if not self.gpg_service.has_signing_key():
                    logger.error(
                        "UnlockNotebookHandler: ❌ No GPG signing keys "
                        "available for current user"
                    )
                    self.write_error_json(
                        403,
                        "Cannot unlock GPG-signed notebook: No GPG signing "
                        "keys available. Please ensure you have access to the "
                        "GPG key used to sign this notebook.",
                    )
                    return

                # Step 2: Extract the key ID that was used to sign the original commit
                logger.info(
                    "UnlockNotebookHandler: Extracting original signing key "
                    "ID from commit..."
                )
                original_signing_key_id = self.git_service.get_commit_signing_key_id(
                    abs_notebook_path, commit_hash
                )

                if not original_signing_key_id:
                    logger.error(
                        "UnlockNotebookHandler: ❌ Could not extract signing "
                        "key ID from original commit"
                    )
                    self.write_error_json(
                        403,
                        "Cannot unlock GPG-signed notebook: Unable to "
                        "determine the GPG key used to sign the original "
                        "commit.",
                    )
                    return

                logger.info(
                    "UnlockNotebookHandler: Original commit was signed with " "key: %s",
                    original_signing_key_id,
                )

                # Step 3: Check if current user has the same signing key
                # configured in git
                logger.info(
                    "UnlockNotebookHandler: Checking current git signing key "
                    "configuration..."
                )
                current_configured_key = self.gpg_service.get_configured_signing_key()

                if not current_configured_key:
                    logger.error(
                        "UnlockNotebookHandler: ❌ No git signing key "
                        "configured for current user"
                    )

                    # Use conditional disclosure with truncated key for security
                    user_matches = (
                        unlocking_user["name"] == original_user_name
                        and unlocking_user["email"] == original_user_email
                    )

                    if user_matches:
                        # Safe to show truncated key ID since user identity
                        # matches
                        short_key_id = (
                            original_signing_key_id[-4:]
                            if len(original_signing_key_id) > 4
                            else original_signing_key_id
                        )
                        error_msg = (
                            "Cannot unlock GPG-signed notebook: No git "
                            "signing key configured. Please configure a GPG "
                            f"key ending in {short_key_id} with: git config "
                            "user.signingkey [YOUR_KEY_ID]"
                        )
                    else:
                        # Don't reveal key information to non-matching users
                        error_msg = (
                            "Cannot unlock GPG-signed notebook: You do not "
                            "have access to the required GPG key. Please "
                            "ensure you are the original signer with proper "
                            "GPG configuration."
                        )

                    self.write_error_json(403, error_msg)
                    return

                logger.info(
                    "UnlockNotebookHandler: Current configured signing key: %s",
                    current_configured_key,
                )

                # Step 4: Verify that the configured key matches the original
                # signing key
                # Handle both short and long key ID formats
                keys_match = (
                    current_configured_key == original_signing_key_id
                    or current_configured_key.endswith(original_signing_key_id)
                    or original_signing_key_id.endswith(current_configured_key)
                )

                if not keys_match:
                    logger.error("UnlockNotebookHandler: ❌ Git signing key mismatch")
                    logger.error(
                        "UnlockNotebookHandler: Original key: %s",
                        original_signing_key_id,
                    )
                    logger.error(
                        "UnlockNotebookHandler: Current key:  %s",
                        current_configured_key,
                    )

                    # Use conditional disclosure with truncated key for security
                    user_matches = (
                        unlocking_user["name"] == original_user_name
                        and unlocking_user["email"] == original_user_email
                    )

                    if user_matches:
                        # Safe to show truncated key IDs since user identity matches
                        short_original_key = (
                            original_signing_key_id[-8:]
                            if len(original_signing_key_id) > 8
                            else original_signing_key_id
                        )
                        short_current_key = (
                            current_configured_key[-8:]
                            if len(current_configured_key) > 8
                            else current_configured_key
                        )
                        error_msg = (
                            "Cannot unlock GPG-signed notebook: "
                            "Git signing key mismatch. "
                            "Original commit was signed with key ending in "
                            f"{short_original_key}, but current git "
                            "configuration uses key ending in "
                            f"{short_current_key}. Please configure the "
                            "correct key with: git config user.signingkey "
                            "[YOUR_KEY_ID]"
                        )
                    else:
                        # Don't reveal key information to non-matching users
                        error_msg = (
                            "Cannot unlock GPG-signed notebook: Git signing "
                            "key configuration does not match. Please ensure "
                            "you are the original signer with the correct GPG "
                            "key configured."
                        )

                    self.write_error_json(403, error_msg)
                    return

                logger.info(
                    "UnlockNotebookHandler: ✅ Git signing key configuration "
                    "matches original"
                )

                # Step 5: Test that the user can actually sign with the original key
                logger.info(
                    "UnlockNotebookHandler: Testing actual signing capability "
                    "with original key..."
                )
                can_sign_with_original_key = self.gpg_service.can_sign_with_key(
                    original_signing_key_id
                )

                if not can_sign_with_original_key:
                    logger.error(
                        "UnlockNotebookHandler: ❌ Cannot sign with original " "GPG key"
                    )

                    # Use conditional disclosure with truncated key for security
                    user_matches = (
                        unlocking_user["name"] == original_user_name
                        and unlocking_user["email"] == original_user_email
                    )

                    if user_matches:
                        # Safe to show truncated key ID since user identity matches
                        short_key_id = (
                            original_signing_key_id[-4:]
                            if len(original_signing_key_id) > 4
                            else original_signing_key_id
                        )
                        error_msg = (
                            "Cannot unlock GPG-signed notebook: "
                            "You do not have the private key ending in "
                            f"{short_key_id} required to unlock this notebook. "
                            "Please ensure you have access to the correct GPG "
                            "private key."
                        )
                    else:
                        # Don't reveal key information to non-matching users
                        error_msg = (
                            "Cannot unlock GPG-signed notebook: You do not "
                            "have access to the required private key. Only the "
                            "user with access to the original signing key can "
                            "unlock this notebook."
                        )

                    self.write_error_json(403, error_msg)
                    return

                logger.info(
                    "UnlockNotebookHandler: ✅ Successfully tested signing "
                    "capability with original key"
                )

                # Step 6: Final verification - ensure commit signature can be verified
                logger.info(
                    "UnlockNotebookHandler: Performing final signature "
                    "verification..."
                )
                (
                    signature_valid_with_current_gpg,
                    verify_error,
                ) = self.git_service.verify_commit_signature(
                    abs_notebook_path, commit_hash
                )

                if not signature_valid_with_current_gpg:
                    logger.error(
                        "UnlockNotebookHandler: ❌ Final GPG signature "
                        "verification failed"
                    )
                    logger.error(
                        "UnlockNotebookHandler: Verification error: %s",
                        verify_error,
                    )
                    self.write_error_json(
                        403,
                        "Cannot unlock GPG-signed notebook: "
                        "Final signature verification failed. "
                        f"Error: {verify_error}",
                    )
                    return

                logger.info(
                    "UnlockNotebookHandler: ✅ COMPREHENSIVE GPG KEY "
                    "VALIDATION PASSED"
                )
                logger.info(
                    "UnlockNotebookHandler: User has verified access to "
                    "original signing key %s",
                    original_signing_key_id,
                )

            # Update the metadata to reflect the unlocked state
            logger.info("UnlockNotebookHandler: Updating metadata to unlocked state...")
            import copy

            updated_metadata = copy.deepcopy(signature_metadata)
            updated_metadata["locked"] = False
            updated_metadata[
                "unlock_timestamp"
            ] = self.notebook_service.get_current_timestamp()
            updated_metadata["unlocked_by_user_name"] = unlocking_user.get("name")
            updated_metadata["unlocked_by_user_email"] = unlocking_user.get("email")

            # Save the notebook with the updated "unlocked" metadata
            save_success = self.notebook_service.save_signature_metadata(
                abs_notebook_path, notebook_content, updated_metadata
            )

            if not save_success:
                logger.error(
                    "UnlockNotebookHandler: ❌ Failed to save notebook with "
                    "updated unlock metadata."
                )
                self.write_error_json(500, "Failed to save updated notebook metadata.")
                return

            logger.info(
                "UnlockNotebookHandler: Successfully saved notebook with "
                "unlocked metadata."
            )
            logger.info("UnlockNotebookHandler: ===== AUTO-COMMITTING UNLOCK =====")

            # Automatically commit the unlocked notebook to finalize the state
            unlock_commit_message = (
                f"Unlocked notebook: {os.path.basename(notebook_path)}"
            )
            logger.info(
                "UnlockNotebookHandler: Committing unlocked file with " "message: '%s'",
                unlock_commit_message,
            )

            (
                commit_success,
                unlock_commit_hash,
                commit_error,
            ) = self.git_service.commit_and_sign_file(
                abs_notebook_path, unlock_commit_message
            )

            if not commit_success or not unlock_commit_hash:
                logger.warning(
                    "UnlockNotebookHandler: Failed to auto-commit unlock: %s",
                    commit_error,
                )
                # Don't fail the whole operation, just warn the user.
                unlock_message += " (Warning: failed to auto-commit unlock)"
            else:
                logger.info(
                    "UnlockNotebookHandler: Successfully committed unlock. "
                    "New commit hash: %s",
                    unlock_commit_hash,
                )
                # Final update to metadata with the unlock commit hash
                updated_metadata["unlock_commit_hash"] = unlock_commit_hash
                final_save_success = self.notebook_service.save_signature_metadata(
                    abs_notebook_path, notebook_content, updated_metadata
                )
                if final_save_success:
                    logger.info(
                        "UnlockNotebookHandler: Amending final commit with "
                        "unlock_commit_hash..."
                    )
                    self.git_service.amend_commit_with_file(
                        abs_notebook_path, unlock_commit_message
                    )
                else:
                    logger.warning(
                        "UnlockNotebookHandler: Failed to save final "
                        "unlock_commit_hash to metadata."
                    )

            logger.info("UnlockNotebookHandler: ===== UNLOCK SUCCESSFUL =====")

            response_data = {
                "success": True,
                "message": unlock_message,
                "signature_verification_passed": signature_verification_passed,
                "was_gpg_signed": was_gpg_signed,
                "commit_hash": unlock_commit_hash,  # Send new commit hash to frontend
                "metadata": updated_metadata,
            }

            logger.info(
                "UnlockNotebookHandler: Sending success response: %s",
                response_data,
            )
            logger.info(
                "UnlockNotebookHandler: SUCCESS - Notebook unlocked and "
                "committed: %s",
                notebook_path,
            )

            self.write_json(response_data)

        except json.JSONDecodeError as e:
            logger.error("UnlockNotebookHandler: JSON decode error: %s", str(e))
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error(
                "UnlockNotebookHandler: Unexpected error during unlock: %s",
                str(e),
            )
            logger.error(
                "UnlockNotebookHandler: Error type: %s",
                type(e).__name__,
            )
            import traceback

            logger.error(
                "UnlockNotebookHandler: Full traceback:\n%s",
                traceback.format_exc(),
            )
            self.write_error_json(500, f"Internal server error: {str(e)}")


class UserInfoHandler(BaseGitLockSignHandler):
    """Handler for getting git user information."""

    async def get(self):
        """Get git user name and email."""
        try:
            user_info = self.user_service.get_user_info()

            if user_info:
                self.write_json({"success": True, "user_info": user_info})
            else:
                self.write_json(
                    {
                        "success": False,
                        "message": "Git user configuration not found",
                    }
                )

        except Exception as e:
            logger.error("Error getting user info: %s", str(e))
            self.write_error_json(500, f"Internal server error: {str(e)}")


class NotebookStatusHandler(BaseGitLockSignHandler):
    """Handler for checking notebook lock status and git commit signature."""

    async def post(self):
        """Check if notebook is locked and git commit signature is valid."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode("utf-8"))
            notebook_content = data.get("notebook_content")
            notebook_path = data.get("notebook_path", "")

            if not notebook_content:
                self.write_error_json(400, "Missing notebook_content")
                return

            # Get signature metadata
            signature_metadata = self.notebook_service.get_signature_metadata(
                notebook_content
            )

            if not signature_metadata:
                self.write_json(
                    {
                        "success": True,
                        "locked": False,
                        "signature_valid": False,
                        "message": "No signature found",
                    }
                )
                return

            # Check if locked
            is_locked = signature_metadata.get("locked", False)

            if not is_locked:
                self.write_json(
                    {
                        "success": True,
                        "locked": False,
                        "signature_valid": False,
                        "message": "Notebook is not locked",
                    }
                )
                return

            # If we have a notebook path, verify git commit signature
            signature_valid = False
            message = "Locked but signature verification skipped (no path provided)"

            if notebook_path:
                abs_notebook_path = os.path.abspath(notebook_path)

                if self.git_service.is_git_repository(abs_notebook_path):
                    commit_hash = signature_metadata.get("commit_hash")
                    if commit_hash:
                        (
                            signature_valid,
                            verify_error,
                        ) = self.git_service.verify_commit_signature(
                            abs_notebook_path, commit_hash
                        )
                        message = (
                            "Git commit signature verified"
                            if signature_valid
                            else f"Git signature verification failed: {verify_error}"
                        )
                    else:
                        message = "No git commit hash found in metadata"
                else:
                    message = "Not in a git repository"

            # Verify content integrity
            current_hash = self.notebook_service.generate_content_hash(notebook_content)
            stored_hash = signature_metadata.get("content_hash")

            if current_hash != stored_hash:
                message += " (Content has been modified since signing)"
                signature_valid = False

            self.write_json(
                {
                    "success": True,
                    "locked": True,
                    "signature_valid": signature_valid,
                    "message": message,
                    "metadata": signature_metadata,
                }
            )

        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error("Error checking notebook status: %s", str(e))
            self.write_error_json(500, f"Internal server error: {str(e)}")


class CommitNotebookHandler(BaseGitLockSignHandler):
    """Handler for staging and committing notebook changes."""

    async def post(self):
        """Stage and commit notebook changes to git."""
        try:
            logger.info("=== CommitNotebookHandler: Starting commit process ===")

            # Get request data
            data = json.loads(self.request.body.decode("utf-8"))
            notebook_path = data.get("notebook_path")
            notebook_content = data.get("notebook_content")
            commit_message = data.get("commit_message")

            logger.info(
                "CommitNotebookHandler: Received request for notebook: %s",
                notebook_path,
            )
            logger.info("CommitNotebookHandler: Commit message: %s", commit_message)

            if not notebook_path or not notebook_content or not commit_message:
                logger.error("CommitNotebookHandler: Missing required parameters")
                self.write_error_json(
                    400,
                    "Missing notebook_path, notebook_content, or commit_message",
                )
                return

            # Convert relative path to absolute path
            abs_notebook_path = os.path.abspath(notebook_path)
            logger.info(
                "CommitNotebookHandler: Absolute path: %s",
                abs_notebook_path,
            )

            # Check if file exists
            if not os.path.exists(abs_notebook_path):
                logger.error(
                    "CommitNotebookHandler: File does not exist: %s",
                    abs_notebook_path,
                )
                self.write_error_json(400, f"File does not exist: {abs_notebook_path}")
                return

            # Check if file is in a git repository
            logger.info(
                "CommitNotebookHandler: Checking if file is in git " "repository..."
            )
            if not self.git_service.is_git_repository(abs_notebook_path):
                logger.error(
                    "CommitNotebookHandler: Not in git repository: %s",
                    abs_notebook_path,
                )
                self.write_error_json(
                    400,
                    "Notebook is not in a git repository. Please initialize git "
                    "repository first.",
                )
                return
            logger.info("CommitNotebookHandler: File is in git repository ✓")

            # Get user info
            logger.info("CommitNotebookHandler: Getting git user info...")
            user_info = self.user_service.get_user_info()
            if not user_info:
                logger.error("CommitNotebookHandler: No git user configuration found")
                self.write_error_json(
                    400,
                    "Git user configuration not found. Please configure git "
                    "user.name and user.email",
                )
                return
            logger.info(
                "CommitNotebookHandler: Git user: %s <%s>",
                user_info["name"],
                user_info["email"],
            )

            # Commit the file with git (notebook already contains metadata
            # from frontend)
            logger.info(
                "CommitNotebookHandler: Calling git_service.commit_and_sign_file()..."
            )
            logger.info(
                "CommitNotebookHandler: Parameters - file: %s, message: %s",
                abs_notebook_path,
                commit_message,
            )

            (
                commit_success,
                commit_hash,
                commit_error,
            ) = self.git_service.commit_and_sign_file(abs_notebook_path, commit_message)

            logger.info(
                "CommitNotebookHandler: Git service returned - success: %s, "
                "hash: %s, error: %s",
                commit_success,
                commit_hash,
                commit_error,
            )

            if not commit_success:
                logger.error(
                    "CommitNotebookHandler: Git commit failed: %s", commit_error
                )
                self.write_error_json(500, f"Failed to commit notebook: {commit_error}")
                return

            # Get commit information
            logger.info("CommitNotebookHandler: Getting commit information...")
            if not commit_hash:
                logger.error("CommitNotebookHandler: No commit hash available")
                self.write_error_json(500, "No commit hash available")
                return

            commit_info = self.git_service.get_commit_info(
                abs_notebook_path, commit_hash
            )
            if not commit_info:
                logger.error("CommitNotebookHandler: Failed to get commit information")
                self.write_error_json(500, "Failed to get commit information")
                return

            # Check if commit is actually signed
            is_signed = commit_info.get("signed", False)

            # Generate content hash for additional verification
            content_hash = self.notebook_service.generate_content_hash(notebook_content)

            # Create updated metadata with actual commit information
            updated_metadata = {
                "commit_hash": commit_hash,
                "commit_signed": is_signed,
                "user_name": commit_info.get("author_name", user_info["name"]),
                "user_email": commit_info.get("author_email", user_info["email"]),
                "timestamp": commit_info.get(
                    "timestamp", self.notebook_service.get_current_timestamp()
                ),
                "content_hash": content_hash,
                "commit_message": commit_info.get("message", ""),
            }

            # If notebook already has git_lock_sign metadata, preserve other fields
            if (
                "metadata" in notebook_content
                and "git_lock_sign" in notebook_content["metadata"]
            ):
                existing_metadata = notebook_content["metadata"]["git_lock_sign"].copy()
                existing_metadata.update(updated_metadata)
                updated_metadata = existing_metadata

            # Update the notebook file with the actual commit information and
            # amend the commit
            logger.info(
                "CommitNotebookHandler: Updating notebook metadata with actual "
                "commit info..."
            )
            success = self.notebook_service.save_signature_metadata(
                notebook_path, notebook_content, updated_metadata
            )

            if not success:
                logger.warning(
                    "CommitNotebookHandler: Failed to update metadata in "
                    "notebook file, but commit succeeded"
                )
                # Don't fail the entire operation, just warn
            else:
                logger.info(
                    "CommitNotebookHandler: Successfully updated notebook "
                    "metadata with commit info"
                )

                # Amend the commit to include the updated metadata
                logger.info(
                    "CommitNotebookHandler: Amending commit to include "
                    "updated metadata..."
                )
                (
                    amend_success,
                    new_commit_hash,
                    amend_error,
                ) = self.git_service.amend_commit_with_file(
                    abs_notebook_path, commit_message
                )

                if amend_success and new_commit_hash:
                    logger.info(
                        "CommitNotebookHandler: Successfully amended commit: %s",
                        new_commit_hash,
                    )
                    # Update the commit hash in our response
                    commit_hash = new_commit_hash
                    updated_metadata["commit_hash"] = new_commit_hash

                    # Re-check if the amended commit is signed
                    updated_commit_info = self.git_service.get_commit_info(
                        abs_notebook_path, new_commit_hash
                    )
                    if updated_commit_info:
                        is_signed = updated_commit_info.get("signed", False)
                        updated_metadata["commit_signed"] = is_signed
                        logger.info(
                            "CommitNotebookHandler: Amended commit signed "
                            "status: %s",
                            is_signed,
                        )
                else:
                    logger.warning(
                        "CommitNotebookHandler: Failed to amend commit: %s",
                        amend_error,
                    )
                    # Continue with original commit, don't fail the operation

            logger.info(
                "CommitNotebookHandler: SUCCESS - Notebook committed: %s, "
                "commit: %s, signed: %s",
                notebook_path,
                commit_hash,
                is_signed,
            )
            signed = "with GPG signature" if is_signed else "without GPG signature"
            self.write_json(
                {
                    "success": True,
                    "message": f"Notebook committed successfully {signed}",
                    "commit_hash": commit_hash,
                    "signed": is_signed,
                }
            )

        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error("Error committing notebook: %s", {str(e)})
            self.write_error_json(500, f"Internal server error: {str(e)}")


class GitRepositoryStatusHandler(BaseGitLockSignHandler):
    """Handler for getting git repository status information."""

    async def post(self):
        """Get git repository status for a notebook path."""
        try:
            # Get request data
            data = json.loads(self.request.body.decode("utf-8"))
            notebook_path = data.get("notebook_path")

            if not notebook_path:
                self.write_error_json(400, "Missing notebook_path")
                return

            abs_notebook_path = os.path.abspath(notebook_path)
            repo_status = self.git_service.get_repository_status(abs_notebook_path)

            self.write_json({"success": True, "repository_status": repo_status})

        except json.JSONDecodeError:
            self.write_error_json(400, "Invalid JSON in request body")
        except Exception as e:
            logger.error("Error getting repository status: %s", str(e))
            self.write_error_json(500, f"Internal server error: {str(e)}")
