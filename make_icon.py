from PIL import Image, ImageDraw

def create_high_res_icon():
    """Create a high-resolution 256x256 base image for the .ico file."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Outer green circle
    draw.ellipse([16, 16, 240, 240], fill="#1DB954")
    
    # Microphone body
    draw.rounded_rectangle([96, 56, 160, 152], radius=24, fill="white")
    
    # Microphone arc
    draw.arc([80, 112, 176, 200], start=0, end=180, fill="white", width=12)
    
    # Microphone stand
    draw.line([128, 200, 128, 224], fill="white", width=12)
    draw.line([96, 224, 160, 224], fill="white", width=12)
    
    return img

if __name__ == "__main__":
    # Generate the base image
    base_img = create_high_res_icon()
    
    # Save it as an .ico file with all the standard Windows sizes packed inside
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base_img.save("scribevibe.ico", format="ICO", sizes=icon_sizes)
    
    print("✅ scribevibe.ico successfully generated in your project folder!")