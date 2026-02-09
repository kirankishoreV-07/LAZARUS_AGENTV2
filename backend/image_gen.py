"""
Image Generation Module — Lazarus V2
Uses Google's Nano Banana (Gemini native image gen) via the Gemini API.

Models:
  - Nano Banana:     gemini-2.5-flash-image      (fast, efficient)
  - Nano Banana Pro: gemini-3-pro-image-preview   (pro quality, thinking)

Supports:
  - Text prompt → image generation
  - Context-aware image suggestions (scan HTML for <img> tags)
  - Image upload/drawing integration
  - Element-targeted image replacement
"""

import os
import re
import json
import base64
import time
import logging
import hashlib
import requests
from typing import Optional
from simple_env import load_env

load_env()

logger = logging.getLogger('lazarus.image_gen')

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ══════════════════════════════════════════════════════════════
# IMAGE SCANNING — Find <img> placeholders in code
# ══════════════════════════════════════════════════════════════

def scan_images_in_code(artifacts: list[dict]) -> list[dict]:
    """
    Scan all artifacts for <img> tags and image references.
    Returns a list of image placeholders found with their context.
    """
    image_refs = []
    
    # Patterns to find image references
    img_tag_pattern = re.compile(
        r'<img\s+[^>]*src\s*=\s*["\']([^"\']*)["\'][^>]*>',
        re.IGNORECASE | re.DOTALL
    )
    bg_image_pattern = re.compile(
        r'background(?:-image)?\s*:\s*url\(["\']?([^"\')\s]+)["\']?\)',
        re.IGNORECASE
    )
    # Also match src={...} in JSX
    jsx_img_pattern = re.compile(
        r'<(?:img|Image)\s+[^>]*src\s*=\s*\{?\s*["\']([^"\'{}]*)["\']',
        re.IGNORECASE
    )
    
    for artifact in artifacts:
        filename = artifact.get('filename', '')
        content = artifact.get('content', '')
        
        # Skip non-frontend files
        if not any(filename.endswith(ext) for ext in ['.html', '.htm', '.tsx', '.jsx', '.css', '.scss', '.vue', '.svelte']):
            continue
        
        # Find img src attributes
        for match in img_tag_pattern.finditer(content):
            src = match.group(1)
            # Get surrounding context (50 chars before and after)
            start = max(0, match.start() - 100)
            end = min(len(content), match.end() + 100)
            context = content[start:end].strip()
            
            # Extract alt text if present
            alt_match = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', match.group(0), re.IGNORECASE)
            alt_text = alt_match.group(1) if alt_match else ''
            
            image_refs.append({
                'type': 'img_tag',
                'src': src,
                'alt': alt_text,
                'filename': filename,
                'line': content[:match.start()].count('\n') + 1,
                'context': context,
                'full_match': match.group(0),
                'is_placeholder': _is_placeholder_src(src),
            })
        
        # Find background-image urls
        for match in bg_image_pattern.finditer(content):
            src = match.group(1)
            start = max(0, match.start() - 80)
            end = min(len(content), match.end() + 80)
            context = content[start:end].strip()
            
            image_refs.append({
                'type': 'bg_image',
                'src': src,
                'alt': '',
                'filename': filename,
                'line': content[:match.start()].count('\n') + 1,
                'context': context,
                'full_match': match.group(0),
                'is_placeholder': _is_placeholder_src(src),
            })
        
        # Find JSX image components
        for match in jsx_img_pattern.finditer(content):
            src = match.group(1)
            start = max(0, match.start() - 80)
            end = min(len(content), match.end() + 80)
            context = content[start:end].strip()
            
            image_refs.append({
                'type': 'jsx_img',
                'src': src,
                'alt': '',
                'filename': filename,
                'line': content[:match.start()].count('\n') + 1,
                'context': context,
                'full_match': match.group(0),
                'is_placeholder': _is_placeholder_src(src),
            })
    
    return image_refs


def _is_placeholder_src(src: str) -> bool:
    """Check if an image src is a placeholder (broken, placeholder service, or generic)."""
    placeholder_indicators = [
        'placeholder', 'via.placeholder', 'placehold', 'picsum',
        'dummyimage', 'fakeimg', 'lorempixel', 'placekitten',
        'fillmurray', 'placecage', 'loremflickr',
        'example.com', 'test.png', 'image.png', 'logo.png',
        '#', 'about:blank', 'data:image/svg',
    ]
    src_lower = src.lower()
    return any(p in src_lower for p in placeholder_indicators) or src.strip() == '' or src.startswith('#')


# ══════════════════════════════════════════════════════════════
# AI IMAGE SUGGESTION — Ask Gemini what image fits
# ══════════════════════════════════════════════════════════════

def suggest_image_prompt(context: str, alt_text: str = '', element_info: dict = None) -> str:
    """
    Use Gemini to suggest what image should go at a specific location
    based on surrounding HTML/code context.
    """
    if not GEMINI_API_KEY:
        return alt_text or "A modern web application illustration"
    
    element_desc = ""
    if element_info:
        element_desc = f"""
Selected element details:
- Tag: {element_info.get('tag', 'img')}
- Current src: {element_info.get('src', 'none')}
- Alt text: {element_info.get('alt', alt_text)}
- Surrounding text: {element_info.get('text', '')[:200]}
- Parent: {element_info.get('parentTag', '')}
- CSS classes: {element_info.get('className', '')}
"""
    
    prompt = f"""Based on this HTML/code context, suggest a short, specific image generation prompt.
The prompt should describe what image would best fit this location in the webpage.

Code context:
{context[:500]}
{element_desc}
{f'Alt text hint: {alt_text}' if alt_text else ''}

Rules:
- Return ONLY the image prompt, nothing else
- Be specific about style, colors, and content
- Keep it under 100 words
- Make it suitable for an AI image generator
- If it looks like a logo, describe a modern logo
- If it looks like a hero image, describe a relevant hero image
- Match the website's apparent theme and style

Image prompt:"""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        resp = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 200, "temperature": 0.7}
        }, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get('candidates', [])
            if candidates:
                return candidates[0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        logger.error(f"Image suggestion failed: {e}")
    
    return alt_text or "A modern, clean illustration for a web application"


# ══════════════════════════════════════════════════════════════
# PROMPT REFINEMENT — Convert conversational requests to image prompts
# ══════════════════════════════════════════════════════════════

def _refine_prompt(raw_prompt: str, style: str = "auto", website_context: str = "") -> str:
    """
    Use Gemini Flash (text model) to convert a user's conversational request
    into a proper, descriptive image generation prompt.
    
    e.g. "want to set a logo for this website" → 
         "A sleek, modern minimalist logo with clean geometric shapes, 
          gradient blue and white color scheme, on a transparent background"
    """
    if not GEMINI_API_KEY:
        return raw_prompt
    
    # Detect if the prompt is already a good descriptive image prompt
    # (doesn't need refinement if it directly describes an image)
    conversational_indicators = [
        'want to', 'want ti', 'i want', 'can you', 'please', 'make me',
        'set up', 'set a', 'create a', 'give me', 'help me', 'need a',
        'generate a', 'build a', 'design a', 'for this', 'for the',
        'for my', 'analyse', 'analyze', 'should be', 'would be',
        'this website', 'the website', 'the app', 'this app',
    ]
    prompt_lower = raw_prompt.lower().strip()
    is_conversational = any(indicator in prompt_lower for indicator in conversational_indicators)
    
    if not is_conversational and len(raw_prompt.split()) >= 5:
        # Prompt seems descriptive enough already, skip refinement
        logger.info(f"   Prompt looks descriptive, skipping refinement")
        return raw_prompt
    
    style_hint = ""
    if style and style != "auto":
        style_map = {
            "photorealistic": "photorealistic, like a real photograph",
            "illustration": "digital illustration style",
            "flat": "flat design, minimal vector style",
            "3d": "3D rendered style",
        }
        style_hint = f"\nDesired style: {style_map.get(style, style)}"
    
    context_hint = ""
    if website_context:
        context_hint = f"\n\nWebsite context (use this to understand what the website is about and tailor the image):\n{website_context[:800]}"
    
    refine_prompt = f"""You are an expert image prompt engineer. Convert the user's request into a specific, 
descriptive image generation prompt that an AI image model can use to create a high-quality image.

User's request: "{raw_prompt}"
{style_hint}{context_hint}

Rules:
- Output ONLY the refined image prompt, nothing else
- Do NOT include any explanations or commentary
- Be very specific about visual details: colors, composition, style, lighting, textures
- If they mention "logo", describe specific logo design details (shape, colors, typography style, background)
- If they mention "hero image" or "banner", describe composition and scene
- Keep it under 80 words but make it very descriptive
- Focus on what the image should LOOK like, not what it's for
- Never include instructions like "create" or "generate" — just describe the image
- For logos: specify clean background (white or transparent), modern design attributes

Refined prompt:"""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        resp = requests.post(url, json={
            "contents": [{"parts": [{"text": refine_prompt}]}],
            "generationConfig": {"maxOutputTokens": 150, "temperature": 0.7}
        }, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get('candidates', [])
            if candidates:
                refined = candidates[0]['content']['parts'][0]['text'].strip()
                # Clean up any quotes or prefixes
                refined = refined.strip('"').strip("'").strip()
                if refined.lower().startswith("refined prompt:"):
                    refined = refined[len("refined prompt:"):].strip()
                logger.info(f"   📝 Prompt refined: '{raw_prompt[:50]}...' → '{refined[:80]}...'")
                return refined
    except Exception as e:
        logger.error(f"   Prompt refinement failed: {e}")
    
    return raw_prompt

# Nano Banana model names (official from Google docs)
NANO_BANANA_MODEL = "gemini-2.5-flash-image"          # Fast & efficient
NANO_BANANA_PRO_MODEL = "gemini-3-pro-image-preview"   # Pro quality + thinking

def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    style: str = "auto",
    use_pro: bool = False,
    website_context: str = "",
) -> dict:
    """
    Generate an image using Google's Nano Banana models via the Gemini API.
    
    Uses :generateContent endpoint with responseModalities: ["TEXT", "IMAGE"]
    
    Args:
        prompt: Text description of the image to generate
        aspect_ratio: "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", etc.
        style: "auto", "photorealistic", "illustration", "flat", "3d"
        use_pro: If True, use Nano Banana Pro (gemini-3-pro-image-preview) for higher quality
    
    Returns:
        {
            "success": bool,
            "image_base64": str (base64-encoded image),
            "mime_type": str,
            "prompt_used": str,
            "model_used": str,
            "error": str (if failed)
        }
    """
    if not GEMINI_API_KEY:
        return {"success": False, "error": "GEMINI_API_KEY not configured"}
    
    # Step 1: Refine conversational prompts into descriptive image prompts
    refined_prompt = _refine_prompt(prompt, style, website_context)
    
    # Step 2: Enhance prompt with style prefix
    enhanced_prompt = refined_prompt
    if style and style != "auto":
        style_prefixes = {
            "photorealistic": "Photorealistic, high quality photograph of",
            "illustration": "Modern digital illustration of",
            "flat": "Flat design, minimal vector illustration of",
            "3d": "3D rendered, modern 3D illustration of",
        }
        prefix = style_prefixes.get(style, "")
        if prefix:
            enhanced_prompt = f"{prefix} {refined_prompt}"
    
    # Try Nano Banana Pro first if requested, then fall back to Nano Banana
    models_to_try = []
    if use_pro:
        models_to_try = [NANO_BANANA_PRO_MODEL, NANO_BANANA_MODEL]
    else:
        models_to_try = [NANO_BANANA_MODEL, NANO_BANANA_PRO_MODEL]
    
    for model_name in models_to_try:
        result = _call_nano_banana(model_name, enhanced_prompt, aspect_ratio)
        if result.get("success"):
            return result
        logger.warning(f"   Model {model_name} failed, trying next...")
    
    # Last resort: SVG fallback
    logger.warning("   All Nano Banana models failed, using SVG fallback")
    return _generate_svg_fallback(enhanced_prompt)


def _call_nano_banana(model_name: str, prompt: str, aspect_ratio: str = "1:1") -> dict:
    """
    Call a Nano Banana model using the standard Gemini :generateContent endpoint.
    
    REST API format (from official docs):
      POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
      Header: x-goog-api-key: API_KEY
      Body: { "contents": [{"parts": [{"text": "..."}]}],
              "generationConfig": { "responseModalities": ["TEXT", "IMAGE"],
                                     "imageConfig": {"aspectRatio": "..."} } }
    
    Response contains parts with either "text" or "inlineData" (base64 image).
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    
    # Build generation config
    generation_config = {
        "responseModalities": ["TEXT", "IMAGE"],
    }
    
    # Add image config for aspect ratio
    # Valid ratios: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9
    valid_ratios = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
    if aspect_ratio in valid_ratios:
        generation_config["imageConfig"] = {"aspectRatio": aspect_ratio}
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": generation_config,
    }
    
    logger.info(f"🎨 Generating image with {model_name}: '{prompt[:80]}...' | aspect={aspect_ratio}")
    
    try:
        gen_start = time.time()
        resp = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY,
            },
            json=payload,
            timeout=120,  # Nano Banana Pro can be slow (thinking)
        )
        gen_elapsed = time.time() - gen_start
        
        logger.info(f"   Response: HTTP {resp.status_code} in {gen_elapsed:.2f}s")
        
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get('candidates', [])
            
            if not candidates:
                logger.warning(f"   No candidates in response")
                return {"success": False, "error": "No candidates in response"}
            
            parts = candidates[0].get('content', {}).get('parts', [])
            
            # Find the image part (skip thought parts for Nano Banana Pro)
            image_data = None
            image_mime = None
            text_content = ""
            
            for part in parts:
                # Skip thinking/thought parts
                if part.get('thought'):
                    continue
                    
                if 'inlineData' in part:
                    image_data = part['inlineData'].get('data', '')
                    image_mime = part['inlineData'].get('mimeType', 'image/png')
                elif 'text' in part:
                    text_content += part['text']
            
            if image_data:
                logger.info(f"   ✅ Image generated with {model_name}: {len(image_data)} base64 chars")
                return {
                    "success": True,
                    "image_base64": image_data,
                    "mime_type": image_mime,
                    "prompt_used": prompt,
                    "model_used": model_name,
                    "description": text_content.strip() if text_content else None,
                }
            else:
                logger.warning(f"   No image data found in response parts")
                return {"success": False, "error": f"Model {model_name} returned text but no image"}
        
        elif resp.status_code == 429:
            logger.warning(f"   Rate limited by {model_name}")
            return {"success": False, "error": "Rate limited, please try again"}
        
        else:
            error_detail = ""
            try:
                err_json = resp.json()
                error_detail = err_json.get('error', {}).get('message', resp.text[:300])
            except:
                error_detail = resp.text[:300]
            logger.error(f"   ❌ {model_name} error {resp.status_code}: {error_detail}")
            return {"success": False, "error": f"API error {resp.status_code}: {error_detail}"}
    
    except requests.exceptions.Timeout:
        logger.error(f"   ❌ {model_name} timeout")
        return {"success": False, "error": "Image generation timed out"}
    except Exception as e:
        logger.error(f"   ❌ {model_name} error: {e}")
        return {"success": False, "error": str(e)}


def _generate_svg_fallback(prompt: str) -> dict:
    """
    Last resort fallback: Generate an SVG placeholder image with the prompt as text.
    This ensures something is always returned even if all image APIs fail.
    """
    logger.info(f"   🔄 Fallback: Generating SVG placeholder")
    
    # Create a nice gradient SVG with the prompt text
    # Hash the prompt for a unique color
    h = hashlib.md5(prompt.encode()).hexdigest()
    color1 = f"#{h[:6]}"
    color2 = f"#{h[6:12]}"
    
    short_prompt = prompt[:40] + ('...' if len(prompt) > 40 else '')
    
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{color1};stop-opacity:0.8"/>
      <stop offset="100%" style="stop-color:{color2};stop-opacity:0.8"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)" rx="16"/>
  <text x="256" y="240" text-anchor="middle" font-family="system-ui, sans-serif" font-size="16" fill="white" opacity="0.9">{short_prompt}</text>
  <text x="256" y="280" text-anchor="middle" font-family="system-ui, sans-serif" font-size="12" fill="white" opacity="0.5">AI Image Placeholder</text>
  <circle cx="256" cy="180" r="30" fill="none" stroke="white" stroke-width="2" opacity="0.3"/>
  <path d="M244 170 L268 190 L244 195 Z" fill="white" opacity="0.3"/>
</svg>'''
    
    svg_b64 = base64.b64encode(svg.encode('utf-8')).decode('utf-8')
    return {
        "success": True,
        "image_base64": svg_b64,
        "mime_type": "image/svg+xml",
        "prompt_used": prompt,
        "is_fallback": True,
    }


# ══════════════════════════════════════════════════════════════
# IMAGE REPLACEMENT — Update code with generated images
# ══════════════════════════════════════════════════════════════

def replace_image_in_code(
    artifacts: list[dict],
    target_filename: str,
    old_src: str,
    new_image_data: str,
    new_image_mime: str = 'image/png',
) -> list[dict]:
    """
    Replace an image source in the code with a base64 data URI.
    For the hackathon, we embed as data URIs. In production, we'd save to /public/assets/.
    
    Args:
        artifacts: List of {filename, content}
        target_filename: The file containing the image to replace
        old_src: The current src value to find and replace
        new_image_data: Base64-encoded image data
        new_image_mime: MIME type of the image
    
    Returns:
        Updated artifacts list
    """
    data_uri = f"data:{new_image_mime};base64,{new_image_data}"
    
    updated = []
    for artifact in artifacts:
        if artifact['filename'] == target_filename:
            new_content = artifact['content'].replace(old_src, data_uri)
            updated.append({'filename': artifact['filename'], 'content': new_content})
        else:
            updated.append(artifact)
    
    return updated


def embed_image_as_asset(
    artifacts: list[dict],
    image_base64: str,
    image_mime: str,
    filename_hint: str = 'generated',
) -> tuple[list[dict], str]:
    """
    Add a generated image as a new file in public/assets/ and return the path.
    
    Returns:
        (updated_artifacts, asset_path)
    """
    # Determine extension
    ext_map = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/svg+xml': '.svg',
        'image/webp': '.webp',
        'image/gif': '.gif',
    }
    ext = ext_map.get(image_mime, '.png')
    
    # Generate unique filename
    hash_suffix = hashlib.md5(image_base64[:100].encode()).hexdigest()[:8]
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', filename_hint)[:30]
    asset_filename = f"public/assets/{safe_name}_{hash_suffix}{ext}"
    asset_path = f"/assets/{safe_name}_{hash_suffix}{ext}"
    
    # For SVG, store as text; for binary images, store base64 with a marker
    if image_mime == 'image/svg+xml':
        content = base64.b64decode(image_base64).decode('utf-8')
    else:
        # Store as a data-url file marker (frontend will handle display)
        content = f"data:{image_mime};base64,{image_base64}"
    
    # Add to artifacts
    artifacts = list(artifacts)
    artifacts.append({
        'filename': asset_filename,
        'content': content,
    })
    
    return artifacts, asset_path
