"""
Jupyter server extension for git-based notebook locking and signing.
"""

from jupyter_server.extension.application import ExtensionApp
from jupyter_server.utils import url_path_join

from .handlers import (
    LockNotebookHandler,
    UnlockNotebookHandler,
    CommitNotebookHandler,
    UserInfoHandler,
    NotebookStatusHandler,
    GitRepositoryStatusHandler
)


class GitLockSignExtension(ExtensionApp):
    """Jupyter server extension for git-based notebook locking and signing."""
    
    name = "git_lock_sign_jlx"
    
    def initialize_handlers(self):
        """Initialize the request handlers."""
        handlers = [
            (r"/git-lock-sign/lock-notebook", LockNotebookHandler),
            (r"/git-lock-sign/unlock-notebook", UnlockNotebookHandler),
            (r"/git-lock-sign/commit-notebook", CommitNotebookHandler),
            (r"/git-lock-sign/user-info", UserInfoHandler),
            (r"/git-lock-sign/notebook-status", NotebookStatusHandler),
            (r"/git-lock-sign/repository-status", GitRepositoryStatusHandler),
        ]
        
        # Add the handlers to the web app with proper base URL
        self.handlers.extend([
            (url_path_join(self.settings.get('base_url', '/'), handler[0]), handler[1])
            for handler in handlers
        ])


def _jupyter_server_extension_points():
    """Entry point for the server extension."""
    return [
        {
            "module": "git_lock_sign_jlx.extension",
            "app": GitLockSignExtension,
        }
    ]


# For backward compatibility
_jupyter_server_extension_paths = _jupyter_server_extension_points
