"""Service for git operations including commit signing and verification."""

import logging
import os
import subprocess
from typing import Any, Dict, Optional, Tuple

from git import InvalidGitRepositoryError, Repo

from git_lock_sign_jlx.logger_util import default_logger_config

logger = logging.getLogger(__name__)
default_logger_config(logger)


class GitService:
    """Service for managing git operations and commit signing."""

    def __init__(self):
        """Initialize the git service."""
        self._repo_cache = {}

    def get_repository(self, file_path: str) -> Optional[Repo]:
        """
        Get git repository for a given file path.

        Args:
            file_path: Path to file within git repository

        Returns:
            Git repository object, or None if not in a git repo
        """
        try:
            # Get directory containing the file
            if os.path.isfile(file_path):
                repo_path = os.path.dirname(file_path)
            else:
                repo_path = file_path

            # Check cache first
            if repo_path in self._repo_cache:
                return self._repo_cache[repo_path]

            # Find git repository
            repo = Repo(repo_path, search_parent_directories=True)
            self._repo_cache[repo_path] = repo

            logger.debug("Found git repository at: %s", repo.working_dir)
            return repo

        except InvalidGitRepositoryError:
            logger.warning("No git repository found for path: %s", file_path)
            return None
        except Exception as e:
            logger.error("Error accessing git repository: %s", str(e))
            return None

    def is_git_repository(self, file_path: str) -> bool:
        """
        Check if file is within a git repository.

        Args:
            file_path: Path to check

        Returns:
            True if within git repository, False otherwise
        """
        return self.get_repository(file_path) is not None

    def commit_and_sign_file(
        self, file_path: str, commit_message: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Add file to git, commit with GPG signature.

        Args:
            file_path: Path to file to commit
            commit_message: Commit message

        Returns:
            Tuple of (success, commit_hash, error_message)
        """
        try:
            logger.info("=== GitService.commit_and_sign_file called ===")
            logger.info("GitService: file_path = %s", file_path)
            logger.info("GitService: commit_message = %s", commit_message)

            repo: Repo | None = self.get_repository(file_path)
            if not repo:
                logger.error("GitService: File is not in a git repository")
                return False, None, "File is not in a git repository"

            # Get relative path from repo root
            repo_root = repo.working_dir
            rel_path = os.path.relpath(file_path, repo_root)

            logger.info("GitService: repo_root = %s", repo_root)
            logger.info("GitService: rel_path = %s", rel_path)

            # Check if file exists
            if not os.path.exists(file_path):
                logger.error("GitService: File does not exist: %s", file_path)
                return False, None, f"File does not exist: {file_path}"

            logger.info("GitService: File exists, proceeding with commit...")

            # Try to commit with GPG signature using subprocess for better control
            commit_hash, signed = self._commit_with_subprocess(
                str(repo_root), rel_path, commit_message
            )

            if commit_hash:
                logger.info(
                    (
                        "GitService: Successfully "
                        "committed file: %s, commit: %s, signed: %s"
                    ),
                    rel_path,
                    commit_hash,
                    signed,
                )
                return True, commit_hash, None
            else:
                logger.error("GitService: Failed to create git commit")
                return False, None, "Failed to create git commit"

        except Exception as e:
            error_msg = f"Error committing file: {str(e)}"
            logger.error("GitService: %s", error_msg)
            return False, None, error_msg

    def verify_commit_signature(
        self, file_path: str, commit_hash: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify GPG signature of a git commit.

        Args:
            file_path: Path to file in repository
            commit_hash: Hash of commit to verify

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            repo = self.get_repository(file_path)
            if not repo:
                return False, "File is not in a git repository"

            # Get commit object
            try:
                commit = repo.commit(commit_hash)  # noqa: F841
            except Exception as e:  # noqa: F841
                return False, f"Commit not found: {commit_hash}"

            # Use git command to verify signature
            # GitPython doesn't have built-in signature verification
            result = self._verify_commit_signature_cmd(
                str(repo.working_dir), commit_hash
            )

            if result:
                logger.info("Commit signature verified successfully: %s", commit_hash)
                return True, None
            else:
                return False, "Commit signature verification failed"

        except Exception as e:
            error_msg = f"Error verifying commit signature: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def get_commit_info(
        self, file_path: str, commit_hash: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get information about a git commit.

        Args:
            file_path: Path to file in repository
            commit_hash: Hash of commit

        Returns:
            Dictionary with commit information, or None if error
        """
        try:
            repo = self.get_repository(file_path)
            if not repo:
                return None

            commit = repo.commit(commit_hash)

            return {
                "hash": commit.hexsha,
                "short_hash": commit.hexsha[:8],
                "message": commit.message.strip(),
                "author_name": commit.author.name,
                "author_email": commit.author.email,
                "timestamp": commit.committed_datetime.isoformat(),
                "signed": self._is_commit_signed(str(repo.working_dir), commit_hash),
            }

        except Exception as e:
            logger.error("Error getting commit info: %s", str(e))
            return None

    def _is_gpg_signing_configured(
        self, repo_path: str
    ) -> Tuple[bool, Optional[str], str]:
        """
        Check if GPG signing is configured for the repository using git command line.

        Args:
            repo_path: Path to git repository

        Returns:
            Tuple of (is_configured, signing_key, config_source)
        """
        try:
            logger.info("Checking GPG configuration in repository: %s", repo_path)

            # Check for signing key (local first, then global)
            local_key_result = subprocess.run(
                ["git", "config", "user.signingkey"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if local_key_result.returncode == 0 and local_key_result.stdout.strip():
                signing_key = local_key_result.stdout.strip()
                logger.info("Found LOCAL GPG signing key: %s", signing_key)
                return True, signing_key, "local"

            # Check global signing key
            global_key_result = subprocess.run(
                ["git", "config", "--global", "user.signingkey"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if global_key_result.returncode == 0 and global_key_result.stdout.strip():
                signing_key = global_key_result.stdout.strip()
                logger.info("Found GLOBAL GPG signing key: %s", signing_key)
                return True, signing_key, "global"

            # Check if commit.gpgsign is enabled (local first, then global)
            local_gpgsign_result = subprocess.run(
                ["git", "config", "commit.gpgsign"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if local_gpgsign_result.returncode == 0:
                gpgsign_value = local_gpgsign_result.stdout.strip().lower()
                if gpgsign_value == "true":
                    logger.info("Found LOCAL commit.gpgsign=true (but no signing key)")
                    return True, None, "local"

            # Check global commit.gpgsign
            global_gpgsign_result = subprocess.run(
                ["git", "config", "--global", "commit.gpgsign"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if global_gpgsign_result.returncode == 0:
                gpgsign_value = global_gpgsign_result.stdout.strip().lower()
                if gpgsign_value == "true":
                    logger.info("Found GLOBAL commit.gpgsign=true (but no signing key)")
                    return True, None, "global"

            logger.info("No GPG signing configuration found")
            return False, None, "none"

        except subprocess.TimeoutExpired:
            logger.error("Git config command timed out")
            return False, None, "error"
        except Exception as e:
            logger.error("Error checking GPG configuration: %s", str(e))
            return False, None, "error"

    def _verify_commit_signature_cmd(self, repo_path: str, commit_hash: str) -> bool:
        """
        Verify commit signature using git command line.

        Args:
            repo_path: Path to git repository
            commit_hash: Commit hash to verify

        Returns:
            True if signature is valid, False otherwise
        """
        try:
            # Use git verify-commit command
            result = subprocess.run(
                ["git", "verify-commit", commit_hash],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            return result.returncode == 0

        except subprocess.TimeoutExpired:
            logger.error("Git verify-commit command timed out")
            return False
        except Exception as e:
            logger.error(f"Error running git verify-commit: {str(e)}")
            return False

    def _is_commit_signed(self, repo_path: str, commit_hash: str) -> bool:
        """
        Check if a commit is signed.

        Args:
            repo_path: Path to git repository
            commit_hash: Commit hash to check

        Returns:
            True if commit is signed, False otherwise
        """
        try:
            # Use git show command with signature info
            result = subprocess.run(
                [
                    "git",
                    "show",
                    "--show-signature",
                    "--format=%G?",
                    "-s",
                    commit_hash,
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            logger.info(
                "_is_commit_signed: git show return code: %s", result.returncode
            )
            logger.info("_is_commit_signed: git show stdout: %r", result.stdout)
            logger.info("_is_commit_signed: git show stderr: %r", result.stderr)

            if result.returncode == 0:
                # %G? format returns signature status, but extra output may be
                # present. Extract the last non-empty line and check if it's a
                # valid signature code.
                lines = [
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                ]
                logger.info("_is_commit_signed: split lines: %r", lines)
                if lines:
                    last_line = lines[-1]
                    logger.info("_is_commit_signed: last_line: %r", last_line)
                    return last_line in ["G", "U", "X", "Y"]
                return False

            logger.error(
                "_is_commit_signed: git show failed with return code %s",
                result.returncode,
            )
            return False

        except subprocess.TimeoutExpired:
            logger.error("Git show command timed out")
            return False
        except Exception as e:
            logger.error("Error checking commit signature: %s", str(e))
            return False

    def _commit_with_subprocess(
        self, repo_path: str, file_path: str, commit_message: str
    ) -> Tuple[Optional[str], bool]:
        """
        Create a git commit using subprocess for better GPG control.

        Args:
            repo_path: Path to git repository
            file_path: Relative path to file to stage and commit
            commit_message: Commit message

        Returns:
            Tuple of (commit_hash, is_signed)
        """
        try:
            # Log detailed information for debugging
            logger.info("Attempting to stage file: %s", file_path)
            logger.info("Repository path: %s", repo_path)
            logger.info(
                "File exists check: %s",
                os.path.exists(os.path.join(repo_path, file_path)),
            )

            # First, stage the file using subprocess for consistency
            git_add_cmd = ["git", "add", file_path]
            logger.info(
                "Running command: %s (cwd: %s)",
                " ".join(git_add_cmd),
                repo_path,
            )

            add_result = subprocess.run(
                git_add_cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            logger.info("Git add return code: %s", add_result.returncode)
            logger.info("Git add stdout: %s", add_result.stdout)
            logger.info("Git add stderr: %s", add_result.stderr)

            if add_result.returncode != 0:
                logger.error(
                    "Failed to stage file %s: %s", file_path, add_result.stderr
                )
                return None, False

            logger.info("Successfully staged file: %s", file_path)

            # Check GPG configuration before attempting to commit
            (
                gpg_configured,
                signing_key,
                config_source,
            ) = self._is_gpg_signing_configured(repo_path)

            if gpg_configured:
                logger.info("GPG signing is configured (%s)", config_source)
                if signing_key:
                    logger.info("Using signing key: %s", signing_key)

                # Try to commit with GPG signing
                git_commit_cmd = ["git", "commit", "-S", "-m", commit_message]
                logger.info(
                    "Running command: %s (cwd: %s)",
                    " ".join(git_commit_cmd),
                    repo_path,
                )

                result = subprocess.run(
                    git_commit_cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )

                logger.info("Git commit -S return code: %s", result.returncode)
                logger.info("Git commit -S stdout: %s", result.stdout)
                logger.info("Git commit -S stderr: %s", result.stderr)

                if result.returncode == 0:
                    # Get the commit hash
                    hash_result = subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )

                    if hash_result.returncode == 0:
                        commit_hash = hash_result.stdout.strip()
                        # Check if the commit is actually signed
                        is_signed = self._is_commit_signed(repo_path, commit_hash)
                        logger.info(
                            (
                                "Commit created with GPG signing attempt: "
                                "%s, actually signed: %s"
                            ),
                            commit_hash,
                            is_signed,
                        )
                        return commit_hash, is_signed

                # If GPG signing failed, log the error and try without signing
                logger.warning(
                    "GPG signing failed (return code %s): %s",
                    result.returncode,
                    result.stderr.strip(),
                )
                logger.info("Attempting commit without signature (disabling GPG)")
            else:
                logger.info("No GPG configuration found, committing without signature")
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-m",
                    commit_message,
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if result.returncode == 0:
                # Get the commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                if hash_result.returncode == 0:
                    commit_hash = hash_result.stdout.strip()
                    logger.info("Commit created without GPG signing: %s", commit_hash)
                    return commit_hash, False

            logger.error("Failed to create commit: %s", result.stderr)
            return None, False

        except subprocess.TimeoutExpired:
            logger.error("Git commit command timed out")
            return None, False
        except Exception as e:
            logger.error("Error creating commit with subprocess: %s", str(e))
            return None, False

    def amend_commit_with_file(
        self, file_path: str, commit_message: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Amend the last commit to include updated file content.

        Args:
            file_path: Path to file to stage and amend
            commit_message: Commit message (can be same as original)

        Returns:
            Tuple of (success, commit_hash, error_message)
        """
        try:
            logger.info("=== GitService.amend_commit_with_file called ===")
            logger.info("GitService: file_path = %s", file_path)
            logger.info("GitService: commit_message = %s", commit_message)

            repo = self.get_repository(file_path)
            if not repo:
                logger.error("GitService: File is not in a git repository")
                return False, None, "File is not in a git repository"

            # Get relative path from repo root
            repo_root = str(repo.working_dir)
            rel_path = os.path.relpath(file_path, repo_root)

            logger.info("GitService: repo_root = %s", repo_root)
            logger.info("GitService: rel_path = %s", rel_path)

            # Check if file exists
            if not os.path.exists(file_path):
                logger.error("GitService: File does not exist: %s", file_path)
                return False, None, f"File does not exist: {file_path}"

            # Stage the updated file
            git_add_cmd = ["git", "add", rel_path]
            logger.info(
                "Running command: %s (cwd: %s)",
                " ".join(git_add_cmd),
                repo_root,
            )

            add_result = subprocess.run(
                git_add_cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            logger.info("Git add return code: %s", add_result.returncode)
            if add_result.returncode != 0:
                logger.error("Failed to stage file %s: %s", rel_path, add_result.stderr)
                return False, None, f"Failed to stage file: {add_result.stderr}"

            # Check GPG configuration
            (
                gpg_configured,
                signing_key,
                config_source,
            ) = self._is_gpg_signing_configured(repo_root)

            # Amend the commit
            if gpg_configured:
                logger.info(
                    "GPG signing is configured (%s), amending with signature",
                    config_source,
                )
                git_amend_cmd = [
                    "git",
                    "commit",
                    "--amend",
                    "-S",
                    "-m",
                    commit_message,
                ]
            else:
                logger.info("No GPG configuration found, amending without signature")
                git_amend_cmd = [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--amend",
                    "-m",
                    commit_message,
                ]

            logger.info(
                "Running command: %s (cwd: %s)",
                " ".join(git_amend_cmd),
                repo_root,
            )

            amend_result = subprocess.run(
                git_amend_cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            logger.info("Git commit --amend return code: %s", amend_result.returncode)
            logger.info("Git commit --amend stdout: %s", amend_result.stdout)
            logger.info("Git commit --amend stderr: %s", amend_result.stderr)

            if amend_result.returncode == 0:
                # Get the new commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                if hash_result.returncode == 0:
                    commit_hash = hash_result.stdout.strip()
                    logger.info("Successfully amended commit: %s", commit_hash)
                    return True, commit_hash, None
                else:
                    logger.error("Failed to get amended commit hash")
                    return False, None, "Failed to get amended commit hash"
            else:
                logger.error("Failed to amend commit: %s", amend_result.stderr)
                return (
                    False,
                    None,
                    f"Failed to amend commit: {amend_result.stderr}",
                )

        except subprocess.TimeoutExpired:
            logger.error("Git amend command timed out")
            return False, None, "Git amend command timed out"
        except Exception as e:
            error_msg = f"Error amending commit: {str(e)}"
            logger.error("GitService: %s", error_msg)
            return False, None, error_msg

    def get_commit_signing_key_id(
        self, file_path: str, commit_hash: str
    ) -> Optional[str]:
        """
        Extract the GPG key ID that was used to sign a specific commit.

        Args:
            file_path: Path to file in repository
            commit_hash: Hash of commit to check

        Returns:
            GPG key ID that signed the commit, or None if not signed or error
        """
        try:
            repo = self.get_repository(file_path)
            if not repo:
                logger.error("GitService: File is not in a git repository")
                return None

            repo_path = str(repo.working_dir)
            logger.info(
                "GitService: Extracting signing key ID from commit %s",
                commit_hash,
            )

            # Use git show command to get signature information
            result = subprocess.run(
                [
                    "git",
                    "show",
                    "--show-signature",
                    "--format=%GK",
                    "-s",
                    commit_hash,
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            logger.info(
                "GitService: git show --format=%%GK return code: %s",
                result.returncode,
            )
            logger.info("GitService: git show --format=%%GK stdout: %r", result.stdout)
            logger.info("GitService: git show --format=%%GK stderr: %r", result.stderr)

            if result.returncode == 0:
                # %GK format returns the key ID used for signing
                lines = [
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                ]
                logger.info("GitService: Parsed lines from git show: %r", lines)

                # Look for a line that looks like a key ID (typically 16 hex characters)
                for line in lines:
                    # GPG key IDs are typically 8 or 16 hex characters
                    if len(line) >= 8 and all(
                        c in "0123456789ABCDEFabcdef" for c in line
                    ):
                        logger.info("GitService: Found signing key ID: %s", line)
                        return line

                logger.warning(
                    "GitService: No key ID found in git show output for commit %s",
                    commit_hash,
                )
                return None
            else:
                logger.error(
                    "GitService: git show failed with return code %s",
                    result.returncode,
                )
                return None

        except subprocess.TimeoutExpired:
            logger.error("GitService: git show command timed out")
            return None
        except Exception as e:
            logger.error("GitService: Error extracting signing key ID: %s", str(e))
            return None

    def rollback_last_commit(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Rollback the last commit in the repository.

        Args:
            file_path: Path to file in repository

        Returns:
            Tuple of (success, error_message)
        """
        try:
            repo = self.get_repository(file_path)
            if not repo:
                return False, "File is not in a git repository"

            repo_path = str(repo.working_dir)
            logger.info("GitService: Rolling back last commit in %s", repo_path)

            # Use git reset --hard HEAD~1 to rollback the last commit
            result = subprocess.run(
                ["git", "reset", "--hard", "HEAD~1"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            logger.info("GitService: git reset return code: %s", result.returncode)
            logger.info("GitService: git reset stdout: %s", result.stdout)
            logger.info("GitService: git reset stderr: %s", result.stderr)

            if result.returncode == 0:
                logger.info("GitService: Successfully rolled back last commit")
                return True, None
            else:
                logger.error("GitService: Failed to rollback commit: %s", result.stderr)
                return False, f"Failed to rollback commit: {result.stderr}"

        except subprocess.TimeoutExpired:
            logger.error("GitService: git reset command timed out")
            return False, "Git reset command timed out"
        except Exception as e:
            logger.error("GitService: Error rolling back commit: %s", str(e))
            return False, f"Error rolling back commit: {str(e)}"

    def get_repository_status(self, file_path: str) -> Dict[str, Any]:
        """
        Get comprehensive repository status.

        Args:
            file_path: Path to file in repository

        Returns:
            Dictionary with repository status information
        """
        try:
            repo = self.get_repository(file_path)
            if not repo:
                return {
                    "is_git_repo": False,
                    "error": "Not in a git repository",
                }

            (
                gpg_configured,
                signing_key,
                config_source,
            ) = self._is_gpg_signing_configured(str(repo.working_dir))

            return {
                "is_git_repo": True,
                "repo_path": str(repo.working_dir),
                "current_branch": repo.active_branch.name,
                "is_dirty": repo.is_dirty(),
                "untracked_files": len(repo.untracked_files),
                "gpg_configured": gpg_configured,
                "gpg_signing_key": signing_key,
                "gpg_config_source": config_source,
                "head_commit": repo.head.commit.hexsha[:8]
                if repo.head.commit
                else None,
            }

        except Exception as e:
            return {"is_git_repo": False, "error": str(e)}
