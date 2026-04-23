#!/usr/bin/env python3
"""
Check Python dependencies for copane
"""

import sys
import importlib.util
import subprocess
import os
from pathlib import Path

def check_package(package_name, min_version=None):
    """Check if a package is installed."""
    try:
        spec = importlib.util.find_spec(package_name)
        if spec is None:
            return False, f"{package_name} not found"
        
        if min_version:
            # Try to get version
            try:
                module = importlib.import_module(package_name)
                if hasattr(module, '__version__'):
                    version = module.__version__
                    from packaging import version as pkg_version
                    if pkg_version.parse(version) < pkg_version.parse(min_version):
                        return False, f"{package_name} version {version} < {min_version}"
                else:
                    # Can't check version, assume it's OK
                    pass
            except ImportError:
                # Can't import version checking module
                pass
        
        return True, f"{package_name} OK"
    except Exception as e:
        return False, f"Error checking {package_name}: {e}"

def check_requirements():
    """Check all required packages."""
    requirements = [
        ("prompt_toolkit", "3.0.0"),
        ("openai", "1.0.0"),
        ("langsmith", "0.7.0"),
        ("openai-agents", "0.13.0"),
        ("python-dotenv", "1.0.0"),
    ]
    
    results = []
    all_ok = True
    
    print("Checking Python dependencies...")
    print("-" * 50)
    
    for package, min_version in requirements:
        ok, message = check_package(package, min_version)
        status = "✓" if ok else "✗"
        color = "\033[92m" if ok else "\033[91m"
        reset = "\033[0m"
        
        print(f"{color}{status} {package} >= {min_version}: {message}{reset}")
        results.append((package, ok, message))
        
        if not ok:
            all_ok = False
    
    print("-" * 50)
    
    # Check Python version
    python_version = sys.version_info
    if python_version.major == 3 and python_version.minor >= 12:
        print(f"\033[92m✓ Python {python_version.major}.{python_version.minor}.{python_version.micro} >= 3.12\033[0m")
    else:
        print(f"\033[91m✗ Python {python_version.major}.{python_version.minor}.{python_version.micro} < 3.12\033[0m")
        all_ok = False
    
    return all_ok, results

def check_virtualenv():
    """Check if we're in a virtual environment."""
    in_venv = sys.prefix != sys.base_prefix
    
    if in_venv:
        print(f"\n\033[92m✓ Running in virtual environment: {sys.prefix}\033[0m")
    else:
        print(f"\n\033[93m⚠ Not running in virtual environment\033[0m")
    
    return in_venv

def check_env_file():
    """Check if environment file exists."""
    env_file = os.path.expanduser("~/.copane.env")
    exists = os.path.exists(env_file)
    
    if exists:
        print(f"\033[92m✓ Environment file found: {env_file}\033[0m")
        
        # Check if it has API keys
        with open(env_file, 'r') as f:
            content = f.read()
        
        has_deepseek = "DEEPSEEK_API_KEY=" in content
        has_openai = "OPENAI_API_KEY=" in content
        
        if has_deepseek:
            print(f"\033[92m  ✓ DEEPSEEK_API_KEY configured\033[0m")
        else:
            print(f"\033[93m  ⚠ DEEPSEEK_API_KEY not configured\033[0m")
        
        if has_openai:
            print(f"\033[92m  ✓ OPENAI_API_KEY configured\033[0m")
        else:
            print(f"\033[93m  ⚠ OPENAI_API_KEY not configured\033[0m")
    else:
        print(f"\033[93m⚠ Environment file not found: {env_file}\033[0m")
        print(f"  Create it with: cp {Path(__file__).parent.parent / '.env.example'} {env_file}")
    
    return exists

def main():
    """Main function."""
    print("copane Dependency Checker")
    print("=" * 50)
    
    # Check virtual environment
    in_venv = check_virtualenv()
    
    # Check requirements
    all_ok, results = check_requirements()
    
    # Check environment file
    check_env_file()
    
    print("\n" + "=" * 50)
    
    if all_ok:
        print("\033[92m✓ All dependencies are satisfied!\033[0m")
        return 0
    else:
        print("\033[91m✗ Some dependencies are missing or outdated\033[0m")
        print("\nTo install missing dependencies:")
        print("1. Activate virtual environment:")
        print("   source ~/.vim/copane-venv/bin/activate")
        print("2. Install dependencies:")
        print("   pip install -e .")
        print("\nOr run the installation script:")
        print("   ./install.sh")
        return 1

if __name__ == "__main__":
    sys.exit(main())
