import csv
import html
import json
import regex as re
import requests

from argparse import ArgumentParser
from hashlib import md5
from mimetypes import guess_extension
from pathlib import Path
from PIL import Image
from requests.utils import urlparse

def process(ctx, line):
    name = line[2] # C column for the name
    title = line[3] # D column for the chuuni title
    message = line[4] # E column for the message
    link = line[9] # J column for the media links

    # Aggregate all the unique characters from the submitted text fields
    ctx.unique_chars.update(name)
    ctx.unique_chars.update(title)
    ctx.unique_chars.update(message)

    # Generate a unique ID from name & title for use in sorting order and naming any associated files.
    ctx.hash_id = md5(f"{name}+{title}".encode("utf-8")).hexdigest()
    print(ctx.hash_id)

    msg = dict()
    msg["id"] = ctx.hash_id
    if name == "Mikururun":
        msg["decal_variant"] = 10 # Headpat decal
    else:
        msg["decal_variant"] = int(ctx.hash_id, 16) % 5
    msg["sender_name"] = name
    msg["sender_title"] = title
    msg["message"] = message
    media = process_media(ctx, link)
    if media["path"]:
        msg["media"] = media
    else:
        msg["media"] = None

    return msg

def process_media(ctx, link):
    media = dict()
    media["type"] = "YouTube"
    media["path"] = None
    url = urlparse(link)
    params = dict(p.split('=') for p in html.unescape(url.query).split('&') if url.query and p)

    if url.netloc == "youtu.be":
        media["video_id"] = url.path.strip("/")
    elif url.netloc == "www.youtube.com" and url.path.startswith("/watch/"):
        media["video_id"] = url.path.replace("/watch/", "")
    elif url.netloc == "www.youtube.com" and url.path.startswith("/live/"):
        media["video_id"] = url.path.replace("/live/", "")
    elif url.netloc == "www.youtube.com" and url.path.startswith("/embed"):
        media["type"] = "YouTubeClip"
        media["video_id"] = url.path.replace("/embed/", "")
        media["clip_id"] = params["clip"]
        media["clipt"] = params["clipt"]
    elif url.netloc == "www.youtube.com" and url.path.startswith("/watch"):
        media["video_id"] = params["v"]
    elif url.netloc == "drive.google.com" and url.path.startswith("/file/d/"):
        media["type"] = "Image"
        drive_id = url.path.replace("/file/d/", "").split("/")[0]
        link = f"https://drive.google.com/uc?export=download&id={drive_id}"
    else:
        media["type"] = "Image"

    if media["type"].startswith("YouTube") and media["video_id"]:
        media["path"] = f"https://i.ytimg.com/vi/{media['video_id']}/mqdefault.jpg"
        # YouTube's default MQ resolution for thumbnails is 320x180 which is still 16:9
        media["width"] = 320
        media["height"] = 180

    if link and media["type"] == "Image":
        path, width, height, thumb_path, thumb_width, thumb_height = download_image(ctx, link)
        media["path"] = path
        media["width"] = width
        media["height"] = height
        media["thumbnail"] = None
        if thumb_path:
            media["thumbnail"] = {
                "path": thumb_path,
                "width": thumb_width,
                "height": thumb_height
            }
        ctx.image_count += 1
    
    return media

def download_image(ctx, image_url):
    resp = requests.get(image_url, stream=True)
    filepath, w, h, thumb_filepath, thumb_w, thumb_h = None, None, None, None, None, None
    if resp.status_code == 200 and resp.headers['content-type'].startswith("image/"):
        ext = guess_extension(resp.headers['Content-Type'].partition(';')[0].strip())
        filepath = f"{ctx.image_path}/{ctx.hash_id}{ext}"
        w, h = None, None

        output = Path(filepath)
        if not output.exists():
            output.parent.mkdir(exist_ok=True, parents=True)
            with output.open("wb") as f:
                f.write(resp.content)

        with Image.open(filepath) as img:
            w, h = img.size

        thumb = f"{ctx.image_path}/{ctx.hash_id}_thumb.png"
        if Path(thumb).exists():
            thumb_filepath = thumb
            with Image.open(thumb) as img:
                thumb_w, thumb_h = img.size
    else:
        print("Error getting image from ", image_url)
    return filepath, w, h, thumb_filepath, thumb_w, thumb_h

def find_charsets(unique_chars):
    regex_str = (
        r"("
        r"(?P<charset_sans_kr>\p{IsHangul})"
        r"|"
        r"(?P<charset_sans_jp>"
        r"[\u2200-\u22FF]"
        r"|"
        r"[\u3000-\u9FFF]"
        r"|"
        r"[\uFF00-\uFFEF])"
        r")"
    )
    pattern = re.compile(regex_str, re.UNICODE)

    matches = pattern.findall("".join(unique_chars))
    charset_sans_kr = "".join(sorted(kr_char for _, kr_char, _ in matches if kr_char))
    charset_sans_jp = "".join(sorted(jp_char for _, _, jp_char in matches if jp_char))

    return charset_sans_kr, charset_sans_jp


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("spreadsheet_path")
    parser.add_argument("image_path")
    parser.add_argument("json_path")
    args = parser.parse_args()
    args.image_count = 0
    args.unique_chars = set()

    messages = []
    with open(args.spreadsheet_path, "r", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None) # Skip header row
        for i, line in enumerate(reader, start=1):
            if line[10]: # Skip row if Column K (11th) isn't blank
                continue
            print(i, line)
            msg = process(args, line)
            print(i, msg)
            messages.append(msg)
    
    print(f"\nTotal number of images: {args.image_count}")
    output = Path(args.json_path)
    output.parent.mkdir(exist_ok=True, parents=True)
    with output.open("w", encoding="utf-8") as f:
        charset_sans_kr, charset_sans_jp = find_charsets(args.unique_chars)
        print(f"KR chars: {charset_sans_kr}")
        print(f"JP chars: {charset_sans_jp}")
        data = {
            "charset_sans_kr": charset_sans_kr,
            "charset_sans_jp": charset_sans_jp,
            # Sort messages by hash_id to shuffle away from submission order before writing
            "messages": sorted(messages, key=lambda msg: msg["id"]),
        }
        json.dump(data, f, ensure_ascii=False, indent=4)
