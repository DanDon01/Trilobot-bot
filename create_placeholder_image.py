"""
Script to create a placeholder no-camera.png image
"""

try:
    from PIL import Image, ImageDraw, ImageFont
    import os

    # Create a 640x480 image with dark gray background
    img = Image.new('RGB', (640, 480), color=(50, 50, 50))
    draw = ImageDraw.Draw(img)

    # Draw a camera icon (simple rectangle with lens)
    draw.rectangle([(220, 180), (420, 300)], outline=(200, 200, 200), width=3)
    draw.ellipse([(290, 210), (350, 270)], outline=(200, 200, 200), width=3)
    
    # Add text
    try:
        font = ImageFont.load_default()
        draw.text((240, 320), "No Camera Available", fill=(255, 0, 0), font=font)
    except Exception as e:
        print(f"Font error: {e}")

    # Ensure static directory exists
    os.makedirs('static', exist_ok=True)
    
    # Save the image
    img.save('static/no-camera.png')
    print("Created static/no-camera.png")

except ImportError:
    print("Error: This script requires Pillow (PIL). Install with: pip install Pillow")
except Exception as e:
    print(f"Error creating image: {e}") 