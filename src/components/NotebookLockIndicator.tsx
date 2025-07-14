/**
 * Notebook-level lock indicator widget for toolbar.
 */

import React from 'react';
import { ReactWidget } from '@jupyterlab/apputils';

/**
 * Props for the NotebookLockIndicator component.
 */
interface INotebookLockIndicatorProps {
  isLocked: boolean;
  signatureInfo?: any;
}

/**
 * React component for the notebook lock indicator.
 */
const NotebookLockIndicatorComponent: React.FC<INotebookLockIndicatorProps> = ({
  isLocked,
  signatureInfo
}) => {
  if (!isLocked) {
    return null;
  }

  const getTooltipText = (): string => {
    if (signatureInfo) {
      return `Notebook locked by ${signatureInfo.user_name} (${signatureInfo.user_email}) at ${new Date(signatureInfo.timestamp).toLocaleString()}`;
    }
    return 'Notebook is locked and signed';
  };

  return (
    <div 
      className="git-lock-sign-notebook-indicator"
      title={getTooltipText()}
    >
      <span className="lock-icon">🔒</span>
      <span className="lock-text">Locked</span>
    </div>
  );
};

/**
 * Widget wrapper for the NotebookLockIndicator component.
 */
export class NotebookLockIndicatorWidget extends ReactWidget {
  private _isLocked: boolean = false;
  private _signatureInfo: any = null;

  constructor() {
    super();
    this.addClass('git-lock-sign-notebook-indicator-widget');
  }

  /**
   * Update the lock status and signature info.
   */
  updateStatus(isLocked: boolean, signatureInfo?: any): void {
    this._isLocked = isLocked;
    this._signatureInfo = signatureInfo;
    this.update();
  }

  protected render(): JSX.Element {
    return (
      <NotebookLockIndicatorComponent
        isLocked={this._isLocked}
        signatureInfo={this._signatureInfo}
      />
    );
  }
}
