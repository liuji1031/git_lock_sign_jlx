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