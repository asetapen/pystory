#!/usr/bin/env bash
# Setup pystory on this system
set -eo pipefail

# Check if pyenv is installed
if ! command -v pyenv &> /dev/null; then
  echo "pyenv is not installed. Please install pyenv."
  exit 1
fi

# Check if we are in a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
  echo "Creating the pystory virtual environment."
  pyenv virtualenv 3.11.2 pystory
  pyenv activate pystory
else
  # Check if virtual env ends with pystory
  if [[ $VIRTUAL_ENV != *"pystory"* ]]; then
    echo "In the wrong virtual environment. Please activate the pystory virtual environment."
  fi
fi

# Check if poetry is installed
if ! command -v poetry &> /dev/null; then
  echo "poetry is not installed. Please install poetry."
  exit 1
fi

# Install system dependencies
sudo apt install gnome-screenshot

# Install dependencies
poetry install

echo "Setup complete."
exit 0
