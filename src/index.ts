import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { INotebookTracker } from '@jupyterlab/notebook';
import { IToolbarWidgetRegistry } from '@jupyterlab/apputils';
import { DocumentRegistry } from '@jupyterlab/docregistry';
import { NotebookPanel, INotebookModel } from '@jupyterlab/notebook';
import { IDisposable, DisposableDelegate } from '@lumino/disposable';

import { LockButtonWidget } from './components/LockButton';
import { CommitButtonWidget } from './components/CommitButton';
import { NotebookLockManager } from './components/NotebookLockManager';
import { UserInfoDisplayWidget } from './components/UserInfoDisplay';
import '../style/commit-button.css';

/**
 * Extension that adds lock button to notebook toolbar.
 */
class GitLockSignExtension implements DocumentRegistry.IWidgetExtension<NotebookPanel, INotebookModel> {
  private _managers = new Map<string, NotebookLockManager>();

  /**
   * Create a new extension for the notebook panel widget.
   */
  createNew(
    panel: NotebookPanel,
    context: DocumentRegistry.IContext<INotebookModel>
  ): IDisposable {
    // Create lock manager for this notebook
    const manager = new NotebookLockManager(panel);
    this._managers.set(context.path, manager);

    // Create user info display widget (includes refresh button)
    const userInfoDisplay = new UserInfoDisplayWidget(panel);
    
    // Create commit button widget
    const commitButton = new CommitButtonWidget(panel);
    
    // Create lock button widget
    const lockButton = new LockButtonWidget(panel);
    
    // Add widgets to toolbar in the new layout:
    // [Git User: John Doe <john@example.com>] [🔄 Refresh] ... [Commit] [Lock]
    panel.toolbar.insertItem(9, 'gitUserInfo', userInfoDisplay);
    panel.toolbar.insertItem(12, 'gitCommit', commitButton);
    panel.toolbar.insertItem(13, 'gitLockSign', lockButton);

    // Clean up when panel is disposed
    const disposable = new DisposableDelegate(() => {
      manager.dispose();
      this._managers.delete(context.path);
      userInfoDisplay.dispose();
      commitButton.dispose();
      lockButton.dispose();
    });

    return disposable;
  }

  /**
   * Get the lock manager for a specific notebook path.
   */
  getManager(path: string): NotebookLockManager | undefined {
    return this._managers.get(path);
  }
}

/**
 * Initialization data for the git_lock_sign_jlx extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'git_lock_sign_jlx:plugin',
  description: 'Git-based notebook locking and signing extension.',
  autoStart: true,
  requires: [INotebookTracker],
  optional: [ISettingRegistry, IToolbarWidgetRegistry],
  activate: (
    app: JupyterFrontEnd,
    notebookTracker: INotebookTracker,
    settingRegistry: ISettingRegistry | null,
    toolbarRegistry: IToolbarWidgetRegistry | null
  ) => {
    console.log('JupyterLab extension git_lock_sign_jlx is activated!');

    // Create the extension instance
    const extension = new GitLockSignExtension();

    // Register the extension with the notebook widget factory
    app.docRegistry.addWidgetExtension('Notebook', extension);

    // Load settings if available
    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('git_lock_sign_jlx settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for git_lock_sign_jlx.', reason);
        });
    }

    // Register toolbar widget if toolbar registry is available
    if (toolbarRegistry) {
      toolbarRegistry.addFactory(
        'Notebook',
        'gitLockSign',
        (panel: NotebookPanel) => new LockButtonWidget(panel)
      );
    }

    console.log('Git Lock Sign extension initialized successfully');
  }
};

export default plugin;
