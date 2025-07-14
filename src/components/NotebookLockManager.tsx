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

  constructor(notebookPanel: NotebookPanel) {
    this._notebookPanel = notebookPanel;
    this._setupEventListeners();
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
      
      // Add lock indicator
      this._addLockIndicator(cell);
      
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
      
      // Remove lock indicator
      this._removeLockIndicator(cell);
      
      console.log(`✅ Cell unlocked - readOnly: ${cell.readOnly}, class removed: ${!cell.node.classList.contains('git-lock-sign-locked')}`);
    }
  }

  /**
   * Add visual lock indicator to a cell.
   */
  private _addLockIndicator(cell: Cell): void {
    // Check if indicator already exists
    if (cell.node.querySelector('.git-lock-sign-indicator')) {
      return;
    }

    const indicator = document.createElement('div');
    indicator.className = 'git-lock-sign-indicator';
    indicator.innerHTML = '🔒';
    indicator.title = 'This cell is locked and signed';
    
    // Add to cell header
    const cellHeader = cell.node.querySelector('.jp-Cell-inputWrapper');
    if (cellHeader) {
      cellHeader.appendChild(indicator);
    }
  }

  /**
   * Remove visual lock indicator from a cell.
   */
  private _removeLockIndicator(cell: Cell): void {
    const indicator = cell.node.querySelector('.git-lock-sign-indicator');
    if (indicator) {
      indicator.remove();
    }
  }
}
