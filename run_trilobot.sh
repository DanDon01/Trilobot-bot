#!/bin/bash
# Trilobot Startup Script
# This script checks for required dependencies and helps troubleshoot common issues

echo "===== Trilobot Startup Script ====="
echo "Checking for required dependencies..."

# Function to check if a package is installed
check_package() {
    if dpkg -l | grep -q "$1"; then
        echo "✓ $1 is installed"
        return 0
    else
        echo "✗ $1 is NOT installed"
        return 1
    fi
}

# Function to install missing packages
install_packages() {
    echo ""
    echo "Some required packages are missing. Installing them now..."
    sudo apt-get update
    sudo apt-get install -y $@
    echo "Package installation complete."
    echo ""
}

# Check required packages
MISSING_PACKAGES=""

# Camera packages
check_package "python3-picamera2" || MISSING_PACKAGES="$MISSING_PACKAGES python3-picamera2"
check_package "python3-libcamera" || MISSING_PACKAGES="$MISSING_PACKAGES python3-libcamera"

# Bluetooth packages
check_package "bluetooth" || MISSING_PACKAGES="$MISSING_PACKAGES bluetooth"
check_package "pi-bluetooth" || MISSING_PACKAGES="$MISSING_PACKAGES pi-bluetooth"

# Controller packages
check_package "python3-evdev" || MISSING_PACKAGES="$MISSING_PACKAGES python3-evdev"
check_package "joystick" || MISSING_PACKAGES="$MISSING_PACKAGES joystick"

# PIL for mock camera
check_package "python3-pil" || MISSING_PACKAGES="$MISSING_PACKAGES python3-pil"

# Install missing packages if needed
if [ ! -z "$MISSING_PACKAGES" ]; then
    install_packages $MISSING_PACKAGES
fi

# Check if Bluetooth is running
if systemctl is-active bluetooth > /dev/null; then
    echo "✓ Bluetooth service is running"
else
    echo "✗ Bluetooth service is not running"
    echo "Starting Bluetooth service..."
    sudo systemctl start bluetooth
fi

# Check if camera is enabled
if vcgencmd get_camera | grep -q "detected=1"; then
    echo "✓ Camera is detected"
else
    echo "✗ Camera is not detected"
    echo "Enabling camera..."
    sudo raspi-config nonint do_camera 0
fi

# Define venv directory relative to script location
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
VENV_DIR="$SCRIPT_DIR/venv"

# Ensure virtual environment exists and activate it
if [ -d "$VENV_DIR" ]; then
    echo "Activating virtual environment: $VENV_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Verify activation
    if [ -z "$VIRTUAL_ENV" ]; then
        echo "✗ ERROR: Failed to activate virtual environment!"
        echo "  The directory '$VENV_DIR' exists but activation failed."
        echo "  Try recreating the venv: rm -rf venv && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        exit 1
    else
        echo "✓ Virtual environment activated: $VIRTUAL_ENV"
    fi
else
    echo "✗ ERROR: Virtual environment directory '$VENV_DIR' not found!"
    echo "  Please create it first: python3 -m venv venv"
    echo "  Then activate and install requirements: source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Run the test script first (using python from venv)
PYTHON_EXEC="$VIRTUAL_ENV/bin/python"
echo ""
echo "Running hardware test script ($PYTHON_EXEC test_hardware.py)..."
"$PYTHON_EXEC" test_hardware.py

# Ask if user wants to continue
echo ""
read -p "Do you want to start the Trilobot application now? (y/n): " choice
if [ "$choice" = "y" ] || [ "$choice" = "Y" ]; then
    echo "Starting Trilobot application ($PYTHON_EXEC main.py)..."
    "$PYTHON_EXEC" main.py
else
    echo "Startup cancelled by user."
fi 