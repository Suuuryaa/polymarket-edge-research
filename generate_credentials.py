"""
Polymarket API Credential Generator
===================================
Generates your API credentials (apiKey, secret, passphrase)
using your MetaMask private key.

IMPORTANT: This is a ONE-TIME setup. Save the credentials securely!
"""

import asyncio
import os
import json
from py_clob_client.client import ClobClient


def generate_api_credentials():
    """
    Generate Polymarket API credentials from your private key
    """
    
    print("=" * 80)
    print("🔑 POLYMARKET API CREDENTIAL GENERATOR")
    print("=" * 80)
    print()
    print("This script will generate your API credentials for trading.")
    print()
    print("⚠️  SECURITY WARNING:")
    print("   - Your private key will be used LOCALLY to sign a message")
    print("   - The private key never leaves your computer")
    print("   - Save the generated credentials SECURELY")
    print()
    print("=" * 80)
    print()
    
    # Get private key
    print("📝 Enter your MetaMask PRIVATE KEY:")
    print("   (Find it in MetaMask → Account Details → Show Private Key)")
    print()
    private_key = input("Private Key (starts with 0x): ").strip()
    
    # Validate format
    if not private_key.startswith("0x") or len(private_key) != 66:
        print("\n❌ Invalid private key format!")
        print("   Should be: 0x followed by 64 hex characters")
        print("   Example: 0x1234567890abcdef...")
        return
    
    print("\n" + "=" * 80)
    print("🔄 Generating API credentials...")
    print("=" * 80)
    
    try:
        # Initialize CLOB client
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,  # Polygon mainnet
            key=private_key
        )
        
        # Generate or derive credentials
        print("\n📡 Connecting to Polymarket...")
        credentials = client.create_or_derive_api_creds()
        
        print("\n✅ SUCCESS! API Credentials Generated:")
        print("=" * 80)
        print()
        print(f"API Key:    {credentials['apiKey']}")
        print(f"Secret:     {credentials['secret']}")
        print(f"Passphrase: {credentials['passphrase']}")
        print()
        print("=" * 80)
        
        # Save to file
        save_choice = input("\n💾 Save credentials to file? (y/n): ").strip().lower()
        
        if save_choice == 'y':
            credentials_data = {
                'api_key': credentials['apiKey'],
                'api_secret': credentials['secret'],
                'passphrase': credentials['passphrase'],
                'private_key': private_key  # Include for easy use later
            }
            
            filename = 'polymarket_credentials.json'
            
            with open(filename, 'w') as f:
                json.dump(credentials_data, f, indent=2)
            
            print(f"\n✅ Credentials saved to: {filename}")
            print()
            print("⚠️  IMPORTANT:")
            print(f"   1. Keep {filename} SECURE - it contains your private key!")
            print("   2. Add to .gitignore (never commit to git!)")
            print("   3. Back it up somewhere safe")
            print()
            
            # Create .gitignore
            with open('.gitignore', 'a') as f:
                f.write(f"\n{filename}\n")
            
            print(f"✅ Added {filename} to .gitignore")
        
        print("\n" + "=" * 80)
        print("🎯 NEXT STEPS:")
        print("=" * 80)
        print()
        print("1. Add these credentials to production_agent.py:")
        print()
        print("   config = {")
        print(f"       'api_key': '{credentials['apiKey']}',")
        print(f"       'api_secret': '{credentials['secret']}',")
        print(f"       'passphrase': '{credentials['passphrase']}',")
        print(f"       'private_key': '{private_key}',")
        print("       # ... rest of config")
        print("   }")
        print()
        print("2. Or load from file:")
        print()
        print("   import json")
        print("   with open('polymarket_credentials.json') as f:")
        print("       creds = json.load(f)")
        print("   config['api_key'] = creds['api_key']")
        print("   # etc.")
        print()
        print("3. Run the trading agent:")
        print()
        print("   python production_agent.py")
        print()
        print("=" * 80)
        print("🎉 You're ready to trade!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error generating credentials: {e}")
        print()
        print("Possible issues:")
        print("  - Invalid private key")
        print("  - Network connection problem")
        print("  - Polymarket API down")
        print()
        print("Double-check your private key and try again.")


if __name__ == "__main__":
    generate_api_credentials()
