"""Git Lock Sign JupyterLab Extension."""
try:
    from ._version import __version__
except ImportError:
    # Fallback when using the package in dev mode without installing
    # in editable mode with pip. It is highly recommended to install
    # the package from a stable release or in editable mode:
    # https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs
    import warnings

    warnings.warn("Importing 'git_lock_sign_jlx' outside a proper installation.")
    __version__ = "dev"


def _jupyter_server_extension_points():
    """Entry point for the server extension."""
    from .extension import GitLockSignExtension

    return [
        {
            "module": "git_lock_sign_jlx.extension",
            "app": GitLockSignExtension,
        }
    ]


# For backward compatibility
_jupyter_server_extension_paths = _jupyter_server_extension_points
