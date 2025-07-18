# git_lock_sign_jlx


A JupyterLab extension to let the user sign and lock jupyter notebook with git commit signatures.

## Setup

1. Create and activate conda environment
```bash
conda create -n jlx --override-channels --strict-channel-priority -c conda-forge -c nodefaults jupyterlab=4 nodejs=18 git copier=7 jinja2-time
conda activate jlx
```

2. Install dependencies
```bash
jlpm install
```

3. Build extension
```bash
jlpm build
```

4. Install the extension
```bash
jupyter labextension develop --overwrite ./
```

5. Confirm installation
```bash
jupyter labextension list
```

## Run JupyterLab with the extension

1. Initialize an empty git repository
```bash
cd </path/to/your/project>
git init
```

2. Set up git user, email and signing key
```bash
git config user.name "Your Name"
git config user.email "your.email@example.com"
git config user.signingkey "your-gpg-key-id"
```

3. Start JupyterLab with the extension
```bash
conda activate jlx
jupyter lab --log-level=INFO --ServerApp.jpserver_extensions="{'git_lock_sign_jlx': True}"
```

## Functionalities

### `Commit` button

When the user clicks the `Commit` button, the extension will show a new popup window to let the user enter the commit message to commit the new changes made to the notebook.

### `Lock` button

When the user clicks the `Lock` button, the extension will show a new popup window to let the user enter the lock message to lock the notebook. The lock functionality requires that the user has a GPG signing key set up in the git config.

After a successful lock, the button will show "Unlock" instead. Unlocking requires the same user name, email and GPG signing key configured in the terminal.

After locking, the cells become read-only. All other cell manipulations are disabled as well, e.g., moving cells up/down, deleting cells, etc.

---

## Key Functions: Commit & Lock Functionality

### Backend (Python)
- **GitService.commit_and_sign_file(file_path, commit_message)** (`git_lock_sign_jlx/services/git_service.py`)
  - Stages and commits a notebook file to git with GPG signature.
- **GitService.amend_commit_with_file(file_path, commit_message)** (`git_lock_sign_jlx/services/git_service.py`)
  - Amends the last commit to include updated notebook metadata.
- **GitService.verify_commit_signature(file_path, commit_hash)** (`git_lock_sign_jlx/services/git_service.py`)
  - Verifies the GPG signature of a specific commit.
- **NotebookService.generate_content_hash(notebook_content)** (`git_lock_sign_jlx/services/notebook_service.py`)
  - Generates a SHA-256 hash of the notebook's essential content for integrity checks.
- **NotebookService.save_signature_metadata(notebook_path, notebook_content, signature_metadata)** (`git_lock_sign_jlx/services/notebook_service.py`)
  - Saves signature/lock metadata into the notebook file.
- **GPGService.can_sign_with_key(key_id)** (`git_lock_sign_jlx/services/gpg_service.py`)
  - Checks if the user can sign with a specific GPG key.
- **UserService.get_user_info()** (`git_lock_sign_jlx/services/user_service.py`)
  - Retrieves the current git user's name and email.

### Frontend (TypeScript/React)
- **LockButtonWidget** (`src/components/LockButton.tsx`)
  - UI component for the lock/unlock button in the notebook toolbar.
- **CommitButtonWidget** (`src/components/CommitButton.tsx`)
  - UI component for the commit button in the notebook toolbar.
- **NotebookLockManager** (`src/components/NotebookLockManager.tsx`)
  - Manages notebook lock state, disables editing when locked, and coordinates lock/unlock actions.
- **gitLockSignAPI** (`src/services/api.ts`)
  - Provides methods to call backend endpoints for lock, unlock, commit, and status operations.
- **NotebookLockManager.lockNotebook()** (`src/components/NotebookLockManager.tsx`)
  - Triggers the lock workflow: collects metadata, calls backend, updates UI.
- **NotebookLockManager.commitNotebook()** (`src/components/NotebookLockManager.tsx`)
  - Triggers the commit workflow: collects commit message, calls backend, updates UI.

See the codebase for more details on each function's parameters and usage.
