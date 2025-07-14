/**
 * Type definitions for git-based notebook locking and signing.
 */

export interface ISignatureMetadata {
  locked: boolean;
  signature: string;
  user_name: string;
  user_email: string;
  timestamp: string;
  content_hash: string;
  unlocked_by_user_name?: string;
  unlock_timestamp?: string;
}

export interface IUserInfo {
  name: string;
  email: string;
}

export interface INotebookStatus {
  locked: boolean;
  signature_valid: boolean;
  message: string;
  metadata?: ISignatureMetadata;
}

export interface IApiResponse<T = any> {
  success: boolean;
  message?: string;
  error?: string;
  data?: T;
}

export interface ILockNotebookRequest {
  notebook_path: string;
  notebook_content: any;
  commit_message?: string;
}

export interface ILockNotebookResponse extends IApiResponse {
  metadata?: ISignatureMetadata;
  commit_hash?: string;
  signed?: boolean;
}

export interface IUnlockNotebookRequest {
  notebook_path: string;
  notebook_content: any;
}

export interface IUnlockNotebookResponse extends IApiResponse {
  metadata?: ISignatureMetadata;
  commit_hash?: string;
  signature_verification_passed?: boolean;
  was_gpg_signed?: boolean;
}

export interface IUserInfoResponse extends IApiResponse {
  user_info?: IUserInfo;
}

export interface INotebookStatusRequest {
  notebook_content: any;
  notebook_path?: string;
}

export interface INotebookStatusResponse extends IApiResponse {
  locked?: boolean;
  signature_valid?: boolean;
  metadata?: ISignatureMetadata;
}

export interface ILockButtonState {
  locked: boolean;
  loading: boolean;
  error: string | null;
  signatureInfo: ISignatureMetadata | null;
}

export enum LockButtonAction {
  LOCK = 'lock',
  UNLOCK = 'unlock'
}

export interface ICommitNotebookRequest {
  notebook_path: string;
  notebook_content: any;
  commit_message: string;
}

export interface ICommitNotebookResponse extends IApiResponse {
  commit_hash?: string;
  signed?: boolean;
}

export interface INotebookLockManager {
  isLocked: boolean;
  signatureMetadata: ISignatureMetadata | null;
  lockNotebook(): Promise<boolean>;
  unlockNotebook(): Promise<boolean>;
  checkStatus(): Promise<INotebookStatus>;
  getUserInfo(): Promise<IUserInfo | null>;
}
