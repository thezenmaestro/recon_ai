"""
Shared test configuration and fixtures.
"""
import sys
import os

# Ensure the repo root is on sys.path so `src.*` and `observability.*` imports work.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
