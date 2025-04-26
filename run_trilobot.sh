#!/bin/bash
# Simplified Trilobot Startup Script

echo "===== Trilobot Startup Script (Simplified) ====="

# Define venv directory relative to script location
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON_EXEC="$VENV_DIR/bin/python"

# Check if venv directory exists
if [ ! -d "$VENV_DIR" ]; then
    echo "✗ ERROR: Virtual environment directory '$VENV_DIR' not found!"
    echo "  Please create it first: python3 -m venv --system-site-packages venv"
    echo "  Then activate and install requirements: source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate the virtual environment
echo "Activating virtual environment: $VENV_DIR"
source "$VENV_DIR/bin/activate"

# Verify activation
if [ -z "$VIRTUAL_ENV" ]; then
    echo "✗ ERROR: Failed to activate virtual environment!"
    echo "  The directory '$VENV_DIR' exists but activation failed."
    echo "  Ensure the venv was created correctly and try again."
    exit 1
else
    echo "✓ Virtual environment activated: $VIRTUAL_ENV"
fi

# Check if main.py exists
if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    echo "✗ ERROR: main.py not found in script directory '$SCRIPT_DIR'!"
    deactivate # Deactivate venv before exiting
    exit 1
fi

# Run the main application using the venv's Python
echo "Starting Trilobot application ($PYTHON_EXEC main.py)..."
"$PYTHON_EXEC" "$SCRIPT_DIR/main.py" 2> >(grep -v "^ALSA")

# Get the exit code from the python script
EXIT_CODE=$?

echo "Trilobot application finished with exit code: $EXIT_CODE"

# Deactivate the virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Deactivating virtual environment."
    deactivate
fi

exit $EXIT_CODE 