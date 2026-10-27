import io
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw

p = Path(sys.argv[1])
rows = [json.loads(line) for line in (p / 'samples.jsonl').read_text().splitlines()]
rows = [r for r in rows if 'offset' in r]
selected = [rows[int(i * (len(rows)-1) / 11)] for i in range(12)]
sheet = Image.new('RGB', (4*380, 3*405), '#202020')
draw = ImageDraw.Draw(sheet)
with (p / 'frames.bin').open('rb') as stream:
    for i, r in enumerate(selected):
        stream.seek(r['offset'])
        data = stream.read(r['length'])
        try:
            frame = Image.open(io.BytesIO(data)).convert('RGB')
            frame.thumbnail((370, 375))
        except OSError:
            continue
        x, y = (i%4)*380, (i//4)*405
        sheet.paste(frame, (x, y+25))
        draw.text((x+5,y+5), f"{r['t']:.2f}s", fill='white')
sheet.save(p / 'contact-sheet.jpg', quality=90)
print(p / 'contact-sheet.jpg')
