"""
Service for GPG signing and verification operations.
"""

import logging
import tempfile
from typing import Optional

import gnupg


logger = logging.getLogger(__name__)


class GPGService:
    """Service for GPG signing and verification operations."""
    
    def __init__(self):
        """Initialize the GPG service."""
        self.gpg = gnupg.GPG()
        self._default_key = None
    
    def sign_content(self, content: str) -> Optional[str]:
        """
        Sign content using the default GPG key.
        
        Args:
            content: Content to sign (typically a hash)
            
        Returns:
            GPG signature as string, or None if signing failed
        """
        try:
            # Get the default signing key
            default_key = self._get_default_key()
            if not default_key:
                logger.error("No default GPG key found for signing")
                return None
            
            # Sign the content
            signed_data = self.gpg.sign(
                content,
                keyid=default_key,
                detach=True,
                clearsign=False
            )
            
            if signed_data.status == 'signature created':
                signature = str(signed_data)
                logger.info(f"Content signed successfully with key {default_key}")
                return signature
            else:
                logger.error(f"GPG signing failed: {signed_data.status}")
                return None
                
        except Exception as e:
            logger.error(f"Error signing content: {str(e)}")
            return None
    
    def verify_signature(self, content: str, signature: str) -> bool:
        """
        Verify a GPG signature against content.
        
        Args:
            content: Original content that was signed
            signature: GPG signature to verify
            
        Returns:
            True if signature is valid, False otherwise
        """
        try:
            # Create temporary files for content and signature
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as content_file:
                content_file.write(content)
                content_file_path = content_file.name
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as sig_file:
                sig_file.write(signature)
                sig_file_path = sig_file.name
            
            try:
                # Verify the signature
                with open(content_file_path, 'rb') as cf:
                    verified = self.gpg.verify_file(cf, sig_file_path)
                
                is_valid = verified.valid
                
                if is_valid:
                    logger.info(f"Signature verified successfully. Key ID: {verified.key_id}")
                else:
                    logger.warning(f"Signature verification failed: {verified.status}")
                
                return is_valid
                
            finally:
                # Clean up temporary files
                import os
                try:
                    os.unlink(content_file_path)
                    os.unlink(sig_file_path)
                except OSError:
                    pass
                    
        except Exception as e:
            logger.error(f"Error verifying signature: {str(e)}")
            return False
    
    def _get_default_key(self) -> Optional[str]:
        """
        Get the default GPG key for signing.
        
        Returns:
            Key ID of default signing key, or None if not found
        """
        if self._default_key:
            return self._default_key
        
        try:
            # Get list of secret keys (private keys available for signing)
            secret_keys = self.gpg.list_keys(True)  # True for secret keys
            
            if not secret_keys:
                logger.error("No GPG secret keys found")
                return None
            
            # Use the first available secret key as default
            default_key = secret_keys[0]['keyid']
            self._default_key = default_key
            
            logger.info(f"Using default GPG key: {default_key}")
            return default_key
            
        except Exception as e:
            logger.error(f"Error getting default GPG key: {str(e)}")
            return None
    
    def get_key_info(self, key_id: Optional[str] = None) -> Optional[dict]:
        """
        Get information about a GPG key.
        
        Args:
            key_id: Key ID to get info for, or None for default key
            
        Returns:
            Dictionary with key information, or None if not found
        """
        try:
            if not key_id:
                key_id = self._get_default_key()
                if not key_id:
                    return None
            
            # Get key information
            keys = self.gpg.list_keys(True)  # Secret keys
            for key in keys:
                if key['keyid'] == key_id:
                    return {
                        'keyid': key['keyid'],
                        'fingerprint': key['fingerprint'],
                        'uids': key['uids'],
                        'length': key['length'],
                        'algo': key['algo'],
                        'expires': key['expires'],
                        'trust': key['trust']
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting key info: {str(e)}")
            return None
    
    def is_gpg_available(self) -> bool:
        """
        Check if GPG is available and working.
        
        Returns:
            True if GPG is available, False otherwise
        """
        try:
            # Try to list keys to test GPG availability
            self.gpg.list_keys()
            return True
        except Exception as e:
            logger.error(f"GPG not available: {str(e)}")
            return False
    
    def has_signing_key(self) -> bool:
        """
        Check if there's at least one signing key available.
        
        Returns:
            True if signing key is available, False otherwise
        """
        try:
            secret_keys = self.gpg.list_keys(True)
            return len(secret_keys) > 0
        except Exception as e:
            logger.error(f"Error checking for signing keys: {str(e)}")
            return False
