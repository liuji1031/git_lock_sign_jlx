/**
 * API service for communicating with the git-lock-sign backend.
 */

import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

import {
  ILockNotebookRequest,
  ILockNotebookResponse,
  IUnlockNotebookRequest,
  IUnlockNotebookResponse,
  ICommitNotebookRequest,
  ICommitNotebookResponse,
  IUserInfoResponse,
  INotebookStatusRequest,
  INotebookStatusResponse
} from '../types';

/**
 * API service class for git-lock-sign operations.
 */
export class GitLockSignAPI {
  private _serverSettings: ServerConnection.ISettings;

  constructor() {
    this._serverSettings = ServerConnection.makeSettings();
  }

  /**
   * Lock and sign a notebook.
   */
  async lockNotebook(
    notebookPath: string,
    notebookContent: any,
    commitMessage?: string
  ): Promise<ILockNotebookResponse> {
    const url = this._getApiUrl('lock-notebook');
    const request: ILockNotebookRequest = {
      notebook_path: notebookPath,
      notebook_content: notebookContent,
      commit_message: commitMessage
    };

    try {
      const response = await this._makeRequest(url, {
        method: 'POST',
        body: JSON.stringify(request)
      });

      return response as ILockNotebookResponse;
    } catch (error) {
      console.error('Error locking notebook:', error);
      return {
        success: false,
        error: `Failed to lock notebook: ${error}`
      };
    }
  }

  /**
   * Unlock a notebook after signature verification.
   */
  async unlockNotebook(
    notebookPath: string,
    notebookContent: any
  ): Promise<IUnlockNotebookResponse> {
    const url = this._getApiUrl('unlock-notebook');
    const request: IUnlockNotebookRequest = {
      notebook_path: notebookPath,
      notebook_content: notebookContent
    };

    try {
      const response = await this._makeRequest(url, {
        method: 'POST',
        body: JSON.stringify(request)
      });

      return response as IUnlockNotebookResponse;
    } catch (error) {
      console.error('Error unlocking notebook:', error);
      return {
        success: false,
        error: `Failed to unlock notebook: ${error}`
      };
    }
  }

  /**
   * Get git user information.
   */
  async getUserInfo(): Promise<IUserInfoResponse> {
    const url = this._getApiUrl('user-info');

    try {
      const response = await this._makeRequest(url, {
        method: 'GET'
      });

      return response as IUserInfoResponse;
    } catch (error) {
      console.error('Error getting user info:', error);
      return {
        success: false,
        error: `Failed to get user info: ${error}`
      };
    }
  }

  /**
   * Check notebook lock status and signature validity.
   */
  async checkNotebookStatus(
    notebookContent: any,
    notebookPath?: string
  ): Promise<INotebookStatusResponse> {
    const url = this._getApiUrl('notebook-status');
    const request: INotebookStatusRequest = {
      notebook_content: notebookContent,
      notebook_path: notebookPath
    };

    try {
      const response = await this._makeRequest(url, {
        method: 'POST',
        body: JSON.stringify(request)
      });

      return response as INotebookStatusResponse;
    } catch (error) {
      console.error('Error checking notebook status:', error);
      return {
        success: false,
        error: `Failed to check notebook status: ${error}`
      };
    }
  }

  /**
   * Commit notebook changes to git.
   */
  async commitNotebook(
    request: ICommitNotebookRequest
  ): Promise<ICommitNotebookResponse> {
    const url = this._getApiUrl('commit-notebook');

    try {
      const response = await this._makeRequest(url, {
        method: 'POST',
        body: JSON.stringify(request)
      });

      return response as ICommitNotebookResponse;
    } catch (error) {
      console.error('Error committing notebook:', error);
      return {
        success: false,
        error: `Failed to commit notebook: ${error}`
      };
    }
  }

  /**
   * Get git repository status for a notebook.
   */
  async getRepositoryStatus(notebookPath: string): Promise<any> {
    const url = this._getApiUrl('repository-status');
    const request = {
      notebook_path: notebookPath
    };

    try {
      const response = await this._makeRequest(url, {
        method: 'POST',
        body: JSON.stringify(request)
      });

      return response;
    } catch (error) {
      console.error('Error getting repository status:', error);
      return {
        success: false,
        error: `Failed to get repository status: ${error}`
      };
    }
  }

  /**
   * Make an HTTP request to the backend API.
   */
  private async _makeRequest(
    url: string,
    options: RequestInit
  ): Promise<any> {
    const settings = this._serverSettings;
    
    // Set default headers
    const headers = new Headers(options.headers);
    headers.set('Content-Type', 'application/json');
    
    // Add authentication token if available
    if (settings.token) {
      headers.set('Authorization', `token ${settings.token}`);
    }

    const requestOptions: RequestInit = {
      ...options,
      headers
    };

    const response = await ServerConnection.makeRequest(
      url,
      requestOptions,
      settings
    );

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      
      try {
        const errorData = await response.json();
        if (errorData.error) {
          errorMessage = errorData.error;
        }
      } catch {
        // If we can't parse the error response, use the default message
      }
      
      throw new Error(errorMessage);
    }

    return await response.json();
  }

  /**
   * Get the full API URL for an endpoint.
   */
  private _getApiUrl(endpoint: string): string {
    return URLExt.join(
      this._serverSettings.baseUrl,
      'git-lock-sign',
      endpoint
    );
  }
}

/**
 * Singleton instance of the API service.
 */
export const gitLockSignAPI = new GitLockSignAPI();
