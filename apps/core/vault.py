"""HashiCorp Vault integration for secure secrets management."""

import os
import logging
from typing import Optional, Dict, Any
import hvac
from django.core.cache import cache
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class VaultClient:
    """Manages secure retrieval of secrets from HashiCorp Vault."""
    
    def __init__(self):
        self.vault_url = os.getenv('VAULT_ADDR', 'http://vault:8200')
        self.vault_token = os.getenv('VAULT_TOKEN')
        self.vault_role = os.getenv('VAULT_ROLE', 'amatopay')
        self.enabled = os.getenv('VAULT_ENABLED', 'false').lower() == 'true'
        self._client: Optional[hvac.Client] = None
        
    @property
    def client(self) -> hvac.Client:
        """Lazy initialization of Vault client."""
        if not self.enabled:
            raise RuntimeError("Vault is not enabled. Set VAULT_ENABLED=true")
            
        if self._client is None:
            self._client = hvac.Client(
                url=self.vault_url,
                token=self.vault_token
            )
            
            if not self._client.is_authenticated():
                raise RuntimeError("Vault authentication failed")
                
        return self._client
    
    def get_secret(self, path: str, key: str, ttl: int = 300) -> Optional[str]:
        """
        Retrieve secret from Vault with caching.
        
        Args:
            path: Vault secret path (e.g., 'amatopay/gateway/cecf')
            key: Secret key within the path
            ttl: Cache TTL in seconds
            
        Returns:
            Secret value or None if not found
        """
        if not self.enabled:
            logger.warning(f"Vault disabled, cannot retrieve {path}/{key}")
            return None
            
        cache_key = f"vault:{path}:{key}"
        cached = cache.get(cache_key)
        if cached:
            return cached
            
        try:
            secret = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point='secret'
            )
            
            value = secret['data']['data'].get(key)
            if value:
                cache.set(cache_key, value, ttl)
                
            return value
            
        except Exception as e:
            logger.error(f"Failed to retrieve {path}/{key} from Vault: {e}")
            return None
    
    def set_secret(self, path: str, data: Dict[str, Any]) -> bool:
        """
        Store secret in Vault.
        
        Args:
            path: Vault secret path
            data: Dictionary of key-value pairs to store
            
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.warning(f"Vault disabled, cannot store secret at {path}")
            return False
            
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point='secret'
            )
            
            # Invalidate cache for updated secrets
            for key in data.keys():
                cache.delete(f"vault:{path}:{key}")
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to store secret at {path}: {e}")
            return False
    
    def rotate_key(self, path: str, key: str, new_value: str) -> bool:
        """Rotate a specific secret key."""
        try:
            # Read current secrets
            current = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point='secret'
            )
            
            data = current['data']['data']
            data[key] = new_value
            
            return self.set_secret(path, data)
            
        except Exception as e:
            logger.error(f"Failed to rotate {path}/{key}: {e}")
            return False


class EncryptedFieldManager:
    """Manages field-level encryption for sensitive database fields."""
    
    def __init__(self):
        vault = VaultClient()
        
        # Try to get encryption key from Vault first
        if vault.enabled:
            key = vault.get_secret('amatopay/encryption', 'database_field_key')
            if key:
                self.fernet = Fernet(key.encode())
                return
        
        # Fallback to environment variable
        env_key = os.getenv('DATABASE_ENCRYPTION_KEY')
        if not env_key:
            raise RuntimeError(
                "No encryption key found. Set DATABASE_ENCRYPTION_KEY or configure Vault"
            )
            
        self.fernet = Fernet(env_key.encode())
    
    def encrypt(self, value: str) -> str:
        """Encrypt a string value."""
        if not value:
            return value
        return self.fernet.encrypt(value.encode()).decode()
    
    def decrypt(self, encrypted_value: str) -> str:
        """Decrypt an encrypted string."""
        if not encrypted_value:
            return encrypted_value
        return self.fernet.decrypt(encrypted_value.encode()).decode()
    
    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet key."""
        return Fernet.generate_key().decode()


# Global instances
vault_client = VaultClient()
encrypted_field_manager = EncryptedFieldManager()
