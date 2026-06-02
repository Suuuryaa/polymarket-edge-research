#!/usr/bin/env python3
"""
Setup Checker for Polymarket Trading Agent
==========================================
Verifies all dependencies and configuration are correct
"""

import sys
import subprocess
import importlib
from pathlib import Path


def print_header(text):
    """Print formatted header"""
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)


def check_python_version():
    """Check Python version"""
    print("\n🐍 Checking Python Version...")
    
    version = sys.version_info
    print(f"   Current: Python {version.major}.{version.minor}.{version.micro}")
    
    if version.major >= 3 and version.minor >= 9:
        print("   ✅ Python version OK (3.9+)")
        return True
    else:
        print("   ❌ Python 3.9+ required")
        print("   Install with: brew install python@3.11")
        return False


def check_dependencies():
    """Check required Python packages"""
    print("\n📦 Checking Dependencies...")
    
    required = [
        'aiohttp',
        'web3',
        'eth_account',
    ]
    
    all_ok = True
    
    for package in required:
        try:
            importlib.import_module(package)
            print(f"   ✅ {package}")
        except ImportError:
            print(f"   ❌ {package} not found")
            all_ok = False
    
    if not all_ok:
        print("\n   Install missing packages:")
        print("   pip install -r requirements.txt")
    
    return all_ok


def check_files():
    """Check required files exist"""
    print("\n📄 Checking Project Files...")
    
    required_files = [
        'polymarket_agent.py',
        'custom_strategies.py',
        'config.py',
        'requirements.txt',
        'README.md',
        'paper_trading.py',
        'SETUP_GUIDE.md'
    ]
    
    all_ok = True
    
    for filename in required_files:
        path = Path(filename)
        if path.exists():
            size = path.stat().st_size
            print(f"   ✅ {filename} ({size:,} bytes)")
        else:
            print(f"   ❌ {filename} missing")
            all_ok = False
    
    return all_ok


def check_virtual_env():
    """Check if virtual environment is active"""
    print("\n🔧 Checking Virtual Environment...")
    
    in_venv = hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )
    
    if in_venv:
        print("   ✅ Virtual environment active")
        print(f"   Path: {sys.prefix}")
        return True
    else:
        print("   ⚠️  Virtual environment not active")
        print("   Recommended: source venv/bin/activate")
        return False


def test_import_agent():
    """Test importing the main agent"""
    print("\n🧪 Testing Agent Import...")
    
    try:
        # Add current directory to path
        sys.path.insert(0, str(Path.cwd()))
        
        import polymarket_agent
        print("   ✅ polymarket_agent.py imports successfully")
        
        # Check key classes exist
        assert hasattr(polymarket_agent, 'PolymarketAgent')
        assert hasattr(polymarket_agent, 'MomentumStrategy')
        assert hasattr(polymarket_agent, 'RiskManager')
        print("   ✅ All key classes found")
        
        return True
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        return False


def test_paper_trading():
    """Test paper trading simulator"""
    print("\n🎮 Testing Paper Trading Simulator...")
    
    try:
        import paper_trading
        print("   ✅ paper_trading.py imports successfully")
        
        assert hasattr(paper_trading, 'PaperTradingSimulator')
        print("   ✅ Simulator class found")
        
        return True
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        return False


def check_network():
    """Check network connectivity"""
    print("\n🌐 Checking Network...")
    
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        print("   ✅ Internet connection OK")
        return True
    except OSError:
        print("   ❌ No internet connection")
        return False


def provide_next_steps(results):
    """Provide guidance based on check results"""
    print_header("SUMMARY")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✅ All checks passed! You're ready to go.")
        print("\n📚 Next Steps:")
        print("   1. Read SETUP_GUIDE.md for detailed instructions")
        print("   2. Test with paper trading:")
        print("      python paper_trading.py")
        print("   3. Once comfortable, configure real API access")
        print("   4. Start with conservative settings")
    else:
        print("\n⚠️  Some checks failed. Fix these issues:")
        
        if not results['python']:
            print("\n   • Install Python 3.9+:")
            print("     brew install python@3.11")
        
        if not results['dependencies']:
            print("\n   • Install required packages:")
            print("     pip install -r requirements.txt")
        
        if not results['files']:
            print("\n   • Download missing files")
            print("     Make sure all files are in the same folder")
        
        if not results['venv']:
            print("\n   • Create and activate virtual environment:")
            print("     python3 -m venv venv")
            print("     source venv/bin/activate")
        
        if not results['agent'] or not results['paper']:
            print("\n   • Fix import errors")
            print("     Check that all files are present and not corrupted")
    
    print("\n" + "="*70)


def main():
    """Run all checks"""
    print_header("🔍 POLYMARKET AGENT SETUP CHECKER")
    print("\nThis script will verify your setup is correct...")
    
    results = {
        'python': check_python_version(),
        'dependencies': check_dependencies(),
        'files': check_files(),
        'venv': check_virtual_env(),
        'agent': test_import_agent(),
        'paper': test_paper_trading(),
        'network': check_network(),
    }
    
    provide_next_steps(results)
    
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
