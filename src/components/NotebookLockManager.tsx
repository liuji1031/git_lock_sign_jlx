/**
 * Notebook lock manager component for handling notebook-level locking state.
 */

import { IDisposable } from '@lumino/disposable';
import { Signal } from '@lumino/signaling';

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

      const response = await gitLockSignAPI.lockNotebook(notebookPath, notebookContent);

      if (response.success && response.metadata) {
        this._isLocked = true;
        this._signatureMetadata = response.metadata;
        this._applyCellLocking(true);
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

      if (response.success) {
        this._isLocked = false;
        this._signatureMetadata = null;
        this._applyCellLocking(false);
        this._stateChanged.emit();
        return true;
      }

      return false;
    } catch (error) {
      console.error('Error unlocking notebook:', error);
      return false;
    }
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
      this._applyCellLocking(true);
    }
  }

  /**
   * Check initial lock status when manager is created.
   */
  private async _checkInitialStatus(): Promise<void> {
    await this.checkStatus();
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
    if (locked) {
      // Add locked styling and make read-only
      cell.node.classList.add('git-lock-sign-locked');
      cell.readOnly = true;
      
      // Add lock indicator
      this._addLockIndicator(cell);
    } else {
      // Remove locked styling and make editable
      cell.node.classList.remove('git-lock-sign-locked');
      cell.readOnly = false;
      
      // Remove lock indicator
      this._removeLockIndicator(cell);
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
