/**
 * User info display component for showing git user configuration.
 */

import React, { useState, useEffect } from 'react';

import { ReactWidget } from '@jupyterlab/apputils';
import { NotebookPanel } from '@jupyterlab/notebook';

import { gitLockSignAPI } from '../services/api';
import { IUserInfo } from '../types';

/**
 * Props for the UserInfoDisplay component.
 */
interface IUserInfoDisplayProps {
  notebookPanel: NotebookPanel;
}

/**
 * State for the user info display.
 */
interface IUserInfoState {
  userInfo: IUserInfo | null;
  loading: boolean;
  error: string | null;
}

/**
 * React component for displaying git user information.
 */
const UserInfoDisplayComponent: React.FC<IUserInfoDisplayProps> = ({
  notebookPanel
}) => {
  const [state, setState] = useState<IUserInfoState>({
    userInfo: null,
    loading: true,
    error: null
  });

  // Load user info when component mounts
  useEffect(() => {
    loadUserInfo();
  }, []);

  /**
   * Load git user information from the backend.
   */
  const loadUserInfo = async (): Promise<void> => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const response = await gitLockSignAPI.getUserInfo();

      if (response.success && response.user_info) {
        setState({
          userInfo: response.user_info,
          loading: false,
          error: null
        });
      } else {
        setState({
          userInfo: null,
          loading: false,
          error: response.error || 'Git user not configured'
        });
      }
    } catch (error) {
      setState({
        userInfo: null,
        loading: false,
        error: `Error loading user info: ${error}`
      });
    }
  };

  /**
   * Handle refresh button click.
   */
  const handleRefresh = (): void => {
    loadUserInfo();
  };

  /**
   * Render the user info content.
   */
  const renderContent = (): JSX.Element => {
    if (state.loading) {
      return (
        <div className="git-user-info-content loading">
          <span className="jp-Icon jp-CircularProgressIcon" />
          <span className="git-user-text">Loading git user...</span>
        </div>
      );
    }

    if (state.error || !state.userInfo) {
      return (
        <div className="git-user-info-content error">
          <span className="jp-Icon jp-ErrorIcon" />
          <span className="git-user-text">
            Git user not configured
          </span>
          <button
            className="git-user-refresh-btn"
            onClick={handleRefresh}
            title="Refresh git user info"
          >
            <span className="refresh-text">🔄</span>
          </button>
        </div>
      );
    }

    return (
      <div className="git-user-info-content success">
        <span className="jp-Icon jp-UserIcon" />
        <span className="git-user-text">
          Git User: <strong>{state.userInfo.name}</strong> &lt;{state.userInfo.email}&gt;
        </span>
        <button
          className="git-user-refresh-btn"
          onClick={handleRefresh}
          title="Refresh git user info"
        >
          <span className="refresh-text">🔄</span>
        </button>
      </div>
    );
  };

  return (
    <div className="git-user-info-display">
      {renderContent()}
    </div>
  );
};

/**
 * Widget wrapper for the UserInfoDisplay component.
 */
export class UserInfoDisplayWidget extends ReactWidget {
  private _notebookPanel: NotebookPanel;

  constructor(notebookPanel: NotebookPanel) {
    super();
    this._notebookPanel = notebookPanel;
    this.addClass('git-lock-sign-user-info-widget');
  }

  protected render(): JSX.Element {
    return (
      <UserInfoDisplayComponent
        notebookPanel={this._notebookPanel}
      />
    );
  }
}
