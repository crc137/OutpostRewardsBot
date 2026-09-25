import os
from cryptography.fernet import Fernet

KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'secret.key')

def _load_or_create_key() -> bytes:
    env_key = os.environ.get('FERNET_KEY')
    if env_key:
        return env_key.encode()
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, 'rb') as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_PATH, 'wb') as f:
        f.write(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return key

_fernet = Fernet(_load_or_create_key())

def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode('utf-8')).decode('utf-8')

def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode('utf-8')).decode('utf-8')
