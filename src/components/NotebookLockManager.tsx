/**
 * Notebook lock manager component for handling notebook-level locking state.
 */

import { IDisposable } from '@lumino/disposable';
import { Signal } from '@lumino/signaling';
import { showDialog, Dialog } from '@jupyterlab/apputils';

import { NotebookPanel } from '@jupyterlab/notebook';
import { Cell } from '@jupyterlab/cells';

import { gitLockSignAPI } from '../services/api';
import {
  INotebookLockManager,
  ISignatureMetadata,
  INotebookStatus,
  IUserInfo
} from '../types';

/**
 * Manager class for notebook locking functionality.
 */
export class NotebookLockManager implements INotebookLockManager, IDisposable {
  private _notebookPanel: NotebookPanel;
  private _isLocked: boolean = false;
  private _signatureMetadata: ISignatureMetadata | null = null;
  private _isDisposed: boolean = false;
  private _stateChanged = new Signal<this, void>(this);
  public notificationSignal = new Signal<this, { msg: string; type: 'success' | 'error' }>(this);

  // Disabled keyboard shortcuts when notebook is locked
  private _disabledShortcuts = [
    // Cell creation and structure
    { key: 'Enter', ctrlKey: false, shiftKey: false, altKey: false, description: 'Enter edit mode' },
    { key: 'a', ctrlKey: false, shiftKey: false, altKey: false, description: 'Insert cell above' },
    { key: 'b', ctrlKey: false, shiftKey: false, altKey: false, description: 'Insert cell below' },
    { key: 'm', ctrlKey: false, shiftKey: false, altKey: false, description: 'Change to Markdown' },
    { key: 'y', ctrlKey: false, shiftKey: false, altKey: false, description: 'Change to code' },
    
    // Cell selection and manipulation
    { key: 'ArrowUp', ctrlKey: false, shiftKey: true, altKey: false, description: 'Extend selection up' },
    { key: 'ArrowDown', ctrlKey: false, shiftKey: true, altKey: false, description: 'Extend selection down' },
    { key: 'a', ctrlKey: true, shiftKey: false, altKey: false, description: 'Select all cells' },
    { key: 'x', ctrlKey: false, shiftKey: false, altKey: false, description: 'Cut cell' },
    { key: 'c', ctrlKey: false, shiftKey: false, altKey: false, description: 'Copy cell' },
    { key: 'v', ctrlKey: false, shiftKey: false, altKey: false, description: 'Paste cell' },
    { key: 'm', ctrlKey: false, shiftKey: true, altKey: false, description: 'Merge cells' },
    { key: 'd', ctrlKey: false, shiftKey: false, altKey: false, description: 'Delete cell (first D)' },
    { key: 'z', ctrlKey: false, shiftKey: false, altKey: false, description: 'Undo cell action' },
    
    // Kernel operations
    { key: '0', ctrlKey: false, shiftKey: false, altKey: false, description: 'Restart kernel (first 0)' }
  ];

  constructor(notebookPanel: NotebookPanel) {
    this._notebookPanel = notebookPanel;
    this._setupEventListeners();
    this._setupKeyboardOverrides();
    this._checkInitialStatus();
  }

  /**
   * Signal emitted when the lock state changes.
   */
  get stateChanged(): Signal<this, void> {
    return this._stateChanged;
  }

  /**
   * Whether the notebook is currently locked.
   */
  get isLocked(): boolean {
    return this._isLocked;
  }

  /**
   * Current signature metadata, if any.
   */
  get signatureMetadata(): ISignatureMetadata | null {
    return this._signatureMetadata;
  }

  /**
   * Whether this manager has been disposed.
   */
  get isDisposed(): boolean {
    return this._isDisposed;
  }

  /**
   * Lock the notebook with GPG signature.
   */
  async lockNotebook(): Promise<boolean> {
    if (this._isDisposed || !this._notebookPanel.content?.model) {
      return false;
    }

    try {
      const notebookPath = this._notebookPanel.context.path;
      const notebookContent = this._notebookPanel.content.model.toJSON();

      console.log('🔒 Starting enhanced lock process with read-only enforcement...');
      const response = await gitLockSignAPI.lockNotebook(notebookPath, notebookContent);

      if (response.success && response.metadata) {
        console.log('✅ Lock API successful, updating state...');
        this._isLocked = true;
        this._signatureMetadata = response.metadata;
        
        // CRITICAL: Force reload notebook from disk to get updated metadata
        console.log('🔄 Forcing notebook reload to sync metadata...');
        await this._notebookPanel.context.revert();
        
        // Wait for reload to complete and cells to be reconstructed
        console.log('⏱️ Waiting 300ms for reload completion...');
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // NOW apply cell locking after reload is complete
        console.log('🛡️ Applying enhanced cell locking after reload...');
        this._applyCellLocking(true);
        
        // Double-check status to ensure metadata is properly loaded
        console.log('🔍 Double-checking lock status after 100ms delay...');
        setTimeout(async () => {
          await this.checkStatus();
          if (this._isLocked) {
            console.log('🔄 Re-applying cell locking for safety...');
            this._applyCellLocking(true);
          }
        }, 100);
        
        this._stateChanged.emit();
        return true;
      }

      return false;
    } catch (error) {
      console.error('Error locking notebook:', error);
      return false;
    }
  }

  /**
   * Unlock the notebook after signature verification.
   */
  async unlockNotebook(): Promise<boolean> {
    if (this._isDisposed || !this._notebookPanel.content?.model) {
      return false;
    }

    try {
      const notebookPath = this._notebookPanel.context.path;
      const notebookContent = this._notebookPanel.content.model.toJSON();

      const response = await gitLockSignAPI.unlockNotebook(notebookPath, notebookContent);

      if (response.success && response.metadata) {
        this._isLocked = response.metadata.locked;
        this._signatureMetadata = response.metadata;
        this._applyCellLocking(false);
        this.notificationSignal.emit({ msg: response.message || 'Notebook unlocked successfully!', type: 'success' });
        
        // Reload the notebook from disk to reflect the committed changes
        await this._notebookPanel.context.revert();
        this._stateChanged.emit();
        return true;
      } else {
        const errorMessage = response.error || 'An unknown error occurred during unlock.';
        this.notificationSignal.emit({ msg: errorMessage, type: 'error' });
        showDialog({
          title: 'Unlock Failed',
          body: errorMessage,
          buttons: [Dialog.okButton({ label: 'OK' })]
        });
        return false;
      }
    } catch (error: any) {
      const errorMessage = error.message || 'An unexpected error occurred.';
      console.error('Error unlocking notebook:', error);
      this.notificationSignal.emit({ msg: errorMessage, type: 'error' });
      showDialog({
        title: 'Unlock Error',
        body: `An unexpected error occurred: ${errorMessage}`,
        buttons: [Dialog.okButton({ label: 'OK' })]
      });
      return false;
    }
  }

  /**
   * Handle successful lock operation from LockButton.
   * This ensures immediate state synchronization after lock.
   */
  async handleLockSuccess(metadata: ISignatureMetadata): Promise<void> {
    console.log('🎯 NotebookLockManager: Handling lock success notification from LockButton...');
    
    this._isLocked = true;
    this._signatureMetadata = metadata;
    
    console.log('🛡️ NotebookLockManager: Applying immediate read-only enforcement after lock success...');
    this._applyCellLocking(true);
    
    this._stateChanged.emit();
    console.log('✅ NotebookLockManager: Lock success handled - cells should now be read-only');
  }

  /**
   * Handle successful unlock operation from LockButton.
   * This ensures immediate state synchronization after unlock.
   */
  async handleUnlockSuccess(): Promise<void> {
    console.log('🎯 NotebookLockManager: Handling unlock success notification from LockButton...');
    
    this._isLocked = false;
    this._signatureMetadata = null;
    
    console.log('🔓 NotebookLockManager: Removing read-only enforcement after unlock success...');
    this._applyCellLocking(false);
    
    this._stateChanged.emit();
    console.log('✅ NotebookLockManager: Unlock success handled - cells should now be editable');
  }

  /**
   * Check the current lock status of the notebook.
   */
  async checkStatus(): Promise<INotebookStatus> {
    if (this._isDisposed || !this._notebookPanel.content?.model) {
      return {
        locked: false,
        signature_valid: false,
        message: 'Notebook not available'
      };
    }

    try {
      const notebookContent = this._notebookPanel.content.model.toJSON();
      const response = await gitLockSignAPI.checkNotebookStatus(notebookContent);

      if (response.success) {
        // Update internal state
        this._isLocked = response.locked || false;
        this._signatureMetadata = response.metadata || null;
        
        // Apply cell locking based on status
        this._applyCellLocking(this._isLocked);
        
        this._stateChanged.emit();

        return {
          locked: response.locked || false,
          signature_valid: response.signature_valid || false,
          message: response.message || 'Status checked',
          metadata: response.metadata
        };
      }

      return {
        locked: false,
        signature_valid: false,
        message: response.error || 'Failed to check status'
      };
    } catch (error) {
      console.error('Error checking notebook status:', error);
      return {
        locked: false,
        signature_valid: false,
        message: `Error: ${error}`
      };
    }
  }

  /**
   * Get git user information.
   */
  async getUserInfo(): Promise<IUserInfo | null> {
    try {
      const response = await gitLockSignAPI.getUserInfo();
      return response.success ? response.user_info || null : null;
    } catch (error) {
      console.error('Error getting user info:', error);
      return null;
    }
  }

  /**
   * Dispose of the manager and clean up resources.
   */
  dispose(): void {
    if (this._isDisposed) {
      return;
    }

    this._isDisposed = true;
    
    // Remove cell locking if currently locked
    if (this._isLocked) {
      this._applyCellLocking(false);
    }

    // Remove keyboard event listener
    document.removeEventListener('keydown', this._handleKeyDown, true);
    console.log('🎹 Keyboard override system disposed');

    // Clear references
    this._signatureMetadata = null;
    Signal.clearData(this);
  }

  /**
   * Set up event listeners for notebook changes.
   */
  private _setupEventListeners(): void {
    // Listen for notebook content changes
    if (this._notebookPanel.content?.model) {
      this._notebookPanel.content.model.contentChanged.connect(
        this._onContentChanged,
        this
      );
    }

    // Listen for new cells being added
    if (this._notebookPanel.content) {
      this._notebookPanel.content.modelChanged.connect(
        this._onModelChanged,
        this
      );
    }
  }

  /**
   * Handle notebook content changes.
   */
  private _onContentChanged(): void {
    // If notebook is locked and content changes, we might want to warn the user
    // For now, we'll just re-check the status
    if (this._isLocked) {
      console.warn('Content changed in locked notebook');
      // Optionally re-check status or show warning
    }
  }

  /**
   * Handle notebook model changes.
   */
  private _onModelChanged(): void {
    // Re-apply cell locking to any new cells
    if (this._isLocked) {
      console.log('📝 Model changed - applying enhanced locking to new cells...');
      
      // Use a small delay to ensure new cells are fully initialized
      setTimeout(() => {
        this._applyCellLocking(true);
      }, 50);
    }
  }

  /**
   * Check initial lock status when manager is created.
   */
  private async _checkInitialStatus(): Promise<void> {
    // Wait for notebook to fully load before checking status
    console.log('🚀 Enhanced initial status check - waiting 500ms for full initialization...');
    
    // Wait a bit for notebook to fully initialize
    await new Promise(resolve => setTimeout(resolve, 500));
    
    // Check status based on actual notebook metadata
    console.log('🔍 Checking status based on actual notebook metadata...');
    await this.checkStatus();
    
    // If locked, ensure cells are actually read-only
    if (this._isLocked) {
      console.log('🔍 Applying read-only enforcement based on metadata...');
      this._applyCellLocking(true);
      
      // Double-check after a short delay to handle any race conditions
      setTimeout(() => {
        if (this._isLocked) {
          console.log('🔄 Re-applying cell locking for safety (enhanced version)...');
          this._applyCellLocking(true);
        }
      }, 200);
    } else {
      console.log('✅ Notebook is not locked - no read-only enforcement needed');
    }
  }

  /**
   * Apply or remove locking to all cells in the notebook.
   */
  private _applyCellLocking(locked: boolean): void {
    if (!this._notebookPanel.content) {
      return;
    }

    const notebook = this._notebookPanel.content;
    const cells = notebook.widgets;

    cells.forEach((cell: Cell) => {
      this._applyCellLockState(cell, locked);
    });

    // Also disable/enable notebook operations
    this._disableNotebookOperations(locked);
    
    // Also disable/enable individual cell action buttons
    this._disableCellActionButtons(locked);
  }

  /**
   * Apply lock state to a single cell.
   */
  private _applyCellLockState(cell: Cell, locked: boolean): void {
    console.log(`🔐 Applying multi-layer read-only enforcement to cell (locked: ${locked})`);
    
    if (locked) {
      // Multiple approaches to ensure read-only state
      cell.node.classList.add('git-lock-sign-locked');
      cell.readOnly = true;
      console.log('🔒 Setting cell.readOnly = true and adding CSS class');
      
      // Disable input areas directly for stronger enforcement
      const inputAreas = cell.node.querySelectorAll('.jp-InputArea-editor');
      console.log(`🔒 Setting contenteditable=false on ${inputAreas.length} input areas`);
      inputAreas.forEach(area => {
        const element = area as HTMLElement;
        element.setAttribute('contenteditable', 'false');
        element.style.pointerEvents = 'none';
        element.style.userSelect = 'none';
        element.style.cursor = 'not-allowed';
      });
      
      // Disable CodeMirror editors if present
      const codeMirrorElements = cell.node.querySelectorAll('.CodeMirror');
      console.log(`🚫 Disabling ${codeMirrorElements.length} CodeMirror editors with pointer-events: none`);
      codeMirrorElements.forEach(cm => {
        const element = cm as HTMLElement;
        element.style.pointerEvents = 'none';
        element.style.cursor = 'not-allowed';
        
        // Hide cursor
        const cursors = element.querySelectorAll('.CodeMirror-cursor');
        cursors.forEach(cursor => {
          (cursor as HTMLElement).style.display = 'none';
        });
      });
      console.log('👁️ Hiding CodeMirror cursors for read-only enforcement');
      
      // Disable any input elements
      const inputs = cell.node.querySelectorAll('input, textarea');
      console.log(`🔒 Disabling ${inputs.length} input/textarea elements`);
      inputs.forEach(input => {
        (input as HTMLInputElement).disabled = true;
      });
      
      console.log(`✅ Cell locked - readOnly: ${cell.readOnly}, class added: ${cell.node.classList.contains('git-lock-sign-locked')}`);
    } else {
      // Remove locked styling and make editable
      cell.node.classList.remove('git-lock-sign-locked');
      cell.readOnly = false;
      console.log('🔓 Removing cell.readOnly and CSS class');
      
      // Re-enable input areas
      const inputAreas = cell.node.querySelectorAll('.jp-InputArea-editor');
      console.log(`🔓 Re-enabling ${inputAreas.length} input areas`);
      inputAreas.forEach(area => {
        const element = area as HTMLElement;
        element.removeAttribute('contenteditable');
        element.style.pointerEvents = '';
        element.style.userSelect = '';
        element.style.cursor = '';
      });
      
      // Re-enable CodeMirror editors
      const codeMirrorElements = cell.node.querySelectorAll('.CodeMirror');
      console.log(`✅ Re-enabling ${codeMirrorElements.length} CodeMirror editors`);
      codeMirrorElements.forEach(cm => {
        const element = cm as HTMLElement;
        element.style.pointerEvents = '';
        element.style.cursor = '';
        
        // Show cursor
        const cursors = element.querySelectorAll('.CodeMirror-cursor');
        cursors.forEach(cursor => {
          (cursor as HTMLElement).style.display = '';
        });
      });
      
      // Re-enable input elements
      const inputs = cell.node.querySelectorAll('input, textarea');
      console.log(`✅ Re-enabling ${inputs.length} input/textarea elements`);
      inputs.forEach(input => {
        (input as HTMLInputElement).disabled = false;
      });
      
      console.log(`✅ Cell unlocked - readOnly: ${cell.readOnly}, class removed: ${!cell.node.classList.contains('git-lock-sign-locked')}`);
    }
  }


  /**
   * Set up keyboard override system to disable shortcuts when locked.
   */
  private _setupKeyboardOverrides(): void {
    // Add event listener to capture keyboard events before JupyterLab processes them
    document.addEventListener('keydown', this._handleKeyDown, true);
    console.log('🎹 Keyboard override system initialized');
  }

  /**
   * Handle keydown events to block disabled shortcuts when notebook is locked.
   */
  private _handleKeyDown = (event: KeyboardEvent): void => {
    // Only intercept if this notebook is locked and focused
    if (!this._isLocked || this._isDisposed) {
      return;
    }

    // Check if the event is targeting this notebook
    if (!this._isEventTargetingThisNotebook(event)) {
      return;
    }

    // Check if this is a disabled shortcut
    const disabledShortcut = this._findDisabledShortcut(event);
    if (disabledShortcut) {
      console.log(`🚫 Blocking disabled shortcut: ${disabledShortcut.description}`);
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      
      // Show user feedback
      this._showShortcutBlockedMessage(disabledShortcut.description);
      return;
    }

    // Special handling for double-key shortcuts (DD for delete, 00 for restart)
    this._handleDoubleKeyShortcuts(event);
  };

  /**
   * Check if the keyboard event is targeting this notebook.
   */
  private _isEventTargetingThisNotebook(event: KeyboardEvent): boolean {
    const target = event.target as HTMLElement;
    if (!target) return false;

    // Check if the event target is within this notebook panel
    return this._notebookPanel.node.contains(target);
  }

  /**
   * Find if the current key combination matches a disabled shortcut.
   */
  private _findDisabledShortcut(event: KeyboardEvent): any {
    return this._disabledShortcuts.find(shortcut => {
      return (
        shortcut.key.toLowerCase() === event.key.toLowerCase() &&
        shortcut.ctrlKey === event.ctrlKey &&
        shortcut.shiftKey === event.shiftKey &&
        shortcut.altKey === event.altKey
      );
    });
  }

  /**
   * Handle double-key shortcuts like DD (delete) and 00 (restart kernel).
   */
  private _handleDoubleKeyShortcuts(event: KeyboardEvent): void {
    // This is a simplified implementation - in a full implementation,
    // you'd need to track the timing and sequence of key presses
    if (event.key === 'd' || event.key === '0') {
      // For now, just block these keys entirely when locked
      console.log(`🚫 Blocking potential double-key shortcut: ${event.key}`);
      event.preventDefault();
      event.stopPropagation();
      this._showShortcutBlockedMessage(`Key '${event.key}' (potential double-key shortcut)`);
    }
  }

  /**
   * Show a message to the user when a shortcut is blocked.
   */
  private _showShortcutBlockedMessage(shortcutDescription: string): void {
    // Create a temporary notification
    const notification = document.createElement('div');
    notification.className = 'git-lock-sign-shortcut-blocked';
    notification.innerHTML = `🔒 Shortcut blocked: ${shortcutDescription}`;
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: var(--jp-warn-color3);
      border: 1px solid var(--jp-warn-color1);
      border-radius: 4px;
      padding: 8px 12px;
      z-index: 10000;
      font-size: 12px;
      color: var(--jp-warn-color0);
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    `;

    document.body.appendChild(notification);

    // Remove after 2 seconds
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 2000);
  }

  /**
   * Disable notebook toolbar buttons when locked.
   */
  private _disableNotebookOperations(disabled: boolean): void {
    if (!this._notebookPanel.content) {
      return;
    }

    console.log(`${disabled ? '🚫' : '✅'} ${disabled ? 'Disabling' : 'Enabling'} notebook operations...`);

    // Disable toolbar buttons by finding them in the DOM
    const toolbarNode = this._notebookPanel.toolbar.node;
    const toolbarButtons = toolbarNode.querySelectorAll('button, .jp-ToolbarButton');
    
    toolbarButtons.forEach(button => {
      const buttonElement = button as HTMLElement;
      const title = buttonElement.title || buttonElement.getAttribute('data-command') || '';
      
      // Check if this is a button we want to disable
      const shouldDisable = title.toLowerCase().includes('insert') ||
                           title.toLowerCase().includes('cut') ||
                           title.toLowerCase().includes('copy') ||
                           title.toLowerCase().includes('paste') ||
                           title.toLowerCase().includes('delete') ||
                           buttonElement.className.includes('insert') ||
                           buttonElement.className.includes('cut') ||
                           buttonElement.className.includes('copy') ||
                           buttonElement.className.includes('paste');
      
      if (shouldDisable) {
        if (disabled) {
          buttonElement.style.opacity = '0.5';
          buttonElement.style.pointerEvents = 'none';
          buttonElement.setAttribute('data-original-title', buttonElement.title);
          buttonElement.title = 'Disabled - notebook is locked';
        } else {
          buttonElement.style.opacity = '';
          buttonElement.style.pointerEvents = '';
          const originalTitle = buttonElement.getAttribute('data-original-title');
          if (originalTitle) {
            buttonElement.title = originalTitle;
            buttonElement.removeAttribute('data-original-title');
          }
        }
      }
    });

    // Disable context menus on cells
    const cells = this._notebookPanel.content.widgets;
    cells.forEach(cell => {
      if (disabled) {
        cell.node.addEventListener('contextmenu', this._blockContextMenu, true);
      } else {
        cell.node.removeEventListener('contextmenu', this._blockContextMenu, true);
      }
    });
  }

  /**
   * Block context menu events on locked cells.
   */
  private _blockContextMenu = (event: MouseEvent): void => {
    if (this._isLocked) {
      event.preventDefault();
      event.stopPropagation();
      this._showShortcutBlockedMessage('Context menu');
    }
  };

  /**
   * Disable notebook actions when locked - expanded to cover entire notebook including "Click to add cell" area.
   */
  private _disableCellActionButtons(disabled: boolean): void {
    if (!this._notebookPanel.content) {
      return;
    }

    console.log(`${disabled ? '🚫' : '✅'} ${disabled ? 'Blocking' : 'Unblocking'} notebook actions...`);

    if (disabled) {
      // Block clicks on the entire notebook container to catch "Click to add cell" area
      this._notebookPanel.content.node.addEventListener('click', this._blockNotebookClicks, true);
      console.log('🚫 Added click blocker to entire notebook container');
    } else {
      // Remove notebook-level click blocker
      this._notebookPanel.content.node.removeEventListener('click', this._blockNotebookClicks, true);
      console.log('✅ Removed click blocker from notebook container');
    }
  }

  /**
   * Block all interactive actions within the notebook when locked - including "Click to add cell" area.
   */
  private _blockNotebookClicks = (event: MouseEvent): void => {
    if (!this._isLocked) {
      return;
    }

    const target = event.target as HTMLElement;
    if (!target) {
      return;
    }

    // Check for various types of interactive elements
    const isBlockableAction = 
      // Regular buttons and toolbars
      target.closest('button') ||
      target.closest('.jp-ToolbarButton') ||
      target.closest('.jp-Button') ||
      target.closest('[role="button"]') ||
      target.closest('.jp-Cell-toolbar') ||
      target.closest('[data-command]') ||
      
      // "Click to add cell" area and related elements
      target.closest('.jp-Notebook-footer') ||
      target.closest('.jp-Notebook-addCellButton') ||
      target.classList.contains('jp-Notebook-footer') ||
      target.classList.contains('jp-Notebook-addCellButton') ||
      
      // Check for add-cell functionality by attributes
      (target.getAttribute('title') && target.getAttribute('title')!.toLowerCase().includes('add')) ||
      (target.getAttribute('aria-label') && target.getAttribute('aria-label')!.toLowerCase().includes('add')) ||
      
      // Check for click-to-add areas by class patterns
      target.className.includes('add') ||
      target.className.includes('Add') ||
      
      // Check parent elements for add-cell functionality
      target.parentElement?.className.includes('add') ||
      target.parentElement?.getAttribute('title')?.toLowerCase().includes('add');

    if (isBlockableAction) {
      console.log('🚫 Blocking notebook action click:', {
        className: target.className,
        title: target.title,
        ariaLabel: target.getAttribute('aria-label'),
        tagName: target.tagName
      });
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      this._showShortcutBlockedMessage('Notebook action blocked');
    }
  };

}
