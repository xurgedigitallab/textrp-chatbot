#!/usr/bin/env python3
"""
Test script to verify E2EE (python-olm) installation in Docker
"""

def test_e2ee():
    print("Testing E2EE installation...")
    print("=" * 50)
    
    # Test python-olm
    try:
        import olm
        print(f"✅ python-olm imported successfully!")
        print(f"   Version: {olm.__version__}")
        
        # Test basic functionality
        account = olm.Account()
        print(f"✅ Created Olm account")
        
        identity_keys = account.identity_keys
        print(f"✅ Generated identity keys")
        
        # Test one-time keys
        account.generate_one_time_keys(1)
        one_time_keys = account.one_time_keys
        print(f"✅ Generated one-time keys")
        
        print("\n🎉 E2EE (python-olm) is fully functional!")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import python-olm: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing python-olm: {e}")
        return False

def test_matrix_nio():
    print("\nTesting matrix-nio with E2E...")
    print("=" * 50)
    
    try:
        from nio import AsyncClient
        print("✅ matrix-nio imported successfully!")
        
        # Check if E2E is available
        try:
            from nio.crypto import OlmDevice
            print("✅ E2E support is available in matrix-nio!")
            return True
        except ImportError:
            print("⚠️  E2E support not available in matrix-nio")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import matrix-nio: {e}")
        return False

def test_alternatives():
    print("\nTesting alternative crypto libraries...")
    print("=" * 50)
    
    libraries = {
        'cryptography': None,
        'nacl': None,
    }
    
    # Test cryptography
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        cipher = Fernet(key)
        encrypted = cipher.encrypt(b"Test message")
        decrypted = cipher.decrypt(encrypted)
        libraries['cryptography'] = True
        print("✅ cryptography - Working")
    except Exception as e:
        libraries['cryptography'] = False
        print(f"❌ cryptography - Failed: {e}")
    
    # Test pynacl
    try:
        import nacl.secret
        import nacl.utils
        key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
        box = nacl.secret.SecretBox(key)
        encrypted = box.encrypt(b"Test message")
        decrypted = box.decrypt(encrypted)
        libraries['nacl'] = True
        print("✅ pynacl (PyNaCl) - Working")
    except Exception as e:
        libraries['nacl'] = False
        print(f"❌ pynacl (PyNaCl) - Failed: {e}")
    
    return all(libraries.values())

if __name__ == "__main__":
    print("E2EE Docker Test Suite")
    print("=" * 50)
    
    results = []
    results.append(("python-olm", test_e2ee()))
    results.append(("matrix-nio E2E", test_matrix_nio()))
    results.append(("Alternative Libraries", test_alternatives()))
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    print("=" * 50)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name:.<40} {status}")
    
    if all(r[1] for r in results):
        print("\n🎉 All tests passed! E2EE is ready to use!")
    else:
        print("\n⚠️  Some tests failed. Check the output above.")
