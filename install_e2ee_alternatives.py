"""
Install E2EE encryption using alternative libraries that work on Windows
"""

import subprocess
import sys

def run_command(cmd, description):
    """Run a command and show status"""
    print(f"\n{description}...")
    print(f"Running: {cmd}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✅ Success!")
        return True
    else:
        print(f"❌ Failed!")
        print(f"Error: {result.stderr}")
        return False

def install_alternatives():
    """Install alternative E2EE libraries"""
    
    print("=" * 60)
    print("Installing E2EE Encryption Libraries for Windows")
    print("=" * 60)
    
    alternatives = [
        ("cryptography", "General-purpose cryptography library"),
        ("pynacl", "Python bindings to libsodium (NaCl)"),
        ("PyNaCl", "Alternative name for pynacl"),
    ]
    
    success_count = 0
    
    for package, description in alternatives:
        if run_command(f"pip install {package}", f"Installing {package}\n  {description}"):
            success_count += 1
    
    print("\n" + "=" * 60)
    print(f"Installation Summary: {success_count}/{len(alternatives)} packages installed")
    print("=" * 60)
    
    if success_count > 0:
        print("\n✅ You can now use encryption in Python!")
        print("\nExample usage with cryptography:")
        print("""
from cryptography.fernet import Fernet
key = Fernet.generate_key()
cipher_suite = Fernet(key)
encrypted_text = cipher_suite.encrypt(b"Hello, World!")
decrypted_text = cipher_suite.decrypt(encrypted_text)
        """)
        
        print("\nExample usage with pynacl:")
        print("""
import nacl.secret
import nacl.utils

# Generate a random secret key
key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
box = nacl.secret.SecretBox(key)

# Encrypt a message
message = b"Secret message"
encrypted = box.encrypt(message)

# Decrypt the message
decrypted = box.decrypt(encrypted)
        """)
    
    print("\nFor Matrix-specific E2EE, you have these options:")
    print("1. Use WSL and install python-olm there")
    print("2. Use Docker container with Linux")
    print("3. Use matrix-nio without E2E: pip install matrix-nio")
    print("4. Use the alternative libraries above for general encryption")
    
    return success_count > 0

if __name__ == "__main__":
    install_alternatives()
